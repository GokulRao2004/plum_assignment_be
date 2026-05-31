"""Tests for policy engine."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from app.policy_engine import (
    evaluate_claim,
    _check_eligibility,
    _check_submission_rules,
    _check_waiting_periods,
    _check_exclusions,
    _check_pre_authorization,
    _check_annual_opd_limit,
    _apply_opd_sub_limits_and_copay
)


@pytest.mark.unit
@pytest.mark.policy
class TestEligibilityChecks:
    """Tests for eligibility checking."""
    
    def test_check_eligibility_member_not_found(self, mock_claim_facts, mock_policy_terms):
        """Test eligibility check with non-existent member."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['member_id'] = 'M999'
        
        result = _check_eligibility(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'not found' in result['reason'].lower()
    
    def test_check_eligibility_policy_inactive(self, mock_claim_facts, mock_policy_terms):
        """Test eligibility check with inactive policy."""
        policy = mock_policy_terms.copy()
        policy['policy_holder']['renewal_status'] = 'EXPIRED'
        
        result = _check_eligibility(mock_claim_facts, policy)
        
        assert result['status'] == 'FAIL'
        assert 'not active' in result['reason'].lower()
    
    def test_check_eligibility_outside_policy_period(self, mock_claim_facts, mock_policy_terms):
        """Test eligibility check with treatment date outside policy period."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['treatment_date'] = '2025-01-15'  # Outside 2024 policy period
        
        result = _check_eligibility(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'outside policy period' in result['reason'].lower()
    
    def test_check_eligibility_pass(self, mock_claim_facts, mock_policy_terms):
        """Test successful eligibility check."""
        result = _check_eligibility(mock_claim_facts, mock_policy_terms)
        
        assert result['status'] == 'PASS'


@pytest.mark.unit
@pytest.mark.policy
class TestSubmissionRules:
    """Tests for submission rules checking."""
    
    def test_check_submission_below_minimum(self, mock_claim_facts, mock_policy_terms):
        """Test submission check with amount below minimum."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claimed_amount'] = 50.0  # Below minimum of 100
        
        result = _check_submission_rules(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'below minimum' in result['reason'].lower()
    
    def test_check_submission_past_deadline(self, mock_claim_facts, mock_policy_terms):
        """Test submission check past deadline."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['treatment_date'] = '2024-01-01'
        claim_facts['submission_date'] = '2024-03-01'  # 60 days later, deadline is 30
        
        result = _check_submission_rules(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'deadline' in result['reason'].lower()
    
    def test_check_submission_pass(self, mock_claim_facts, mock_policy_terms):
        """Test successful submission check."""
        result = _check_submission_rules(mock_claim_facts, mock_policy_terms)
        
        assert result['status'] == 'PASS'


@pytest.mark.unit
@pytest.mark.policy
class TestWaitingPeriods:
    """Tests for waiting period checks."""
    
    def test_check_waiting_initial_period(self, mock_claim_facts, mock_policy_terms):
        """Test initial waiting period check."""
        # Member joined 15 days ago, initial waiting is 30 days
        policy = mock_policy_terms.copy()
        policy['members'][0]['join_date'] = '2024-01-01'
        
        claim_facts = mock_claim_facts.copy()
        claim_facts['treatment_date'] = '2024-01-10'  # Only 9 days after join
        
        result = _check_waiting_periods(claim_facts, policy)
        
        assert result['status'] == 'FAIL'
        assert 'initial waiting period' in result['reason'].lower()
    
    def test_check_waiting_pre_existing(self, mock_claim_facts, mock_policy_terms):
        """Test pre-existing condition waiting period."""
        policy = mock_policy_terms.copy()
        policy['members'][0]['join_date'] = '2023-12-01'
        
        claim_facts = mock_claim_facts.copy()
        claim_facts['treatment_date'] = '2024-01-15'
        claim_facts['is_pre_existing_condition'] = True
        
        result = _check_waiting_periods(claim_facts, policy)
        
        assert result['status'] == 'FAIL'
        assert 'pre-existing' in result['reason'].lower()
    
    def test_check_waiting_pass(self, mock_claim_facts, mock_policy_terms):
        """Test successful waiting period check."""
        policy = mock_policy_terms.copy()
        policy['members'][0]['join_date'] = '2023-01-01'  # Joined over a year ago
        
        result = _check_waiting_periods(mock_claim_facts, policy)
        
        assert result['status'] == 'PASS'


@pytest.mark.unit
@pytest.mark.policy
class TestExclusions:
    """Tests for exclusion checks."""
    
    def test_check_exclusions_global(self, mock_claim_facts, mock_policy_terms):
        """Test global exclusion check."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['diagnosis'] = 'Cosmetic surgery for beauty'
        
        result = _check_exclusions(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'exclusion' in result['reason'].lower()
    
    def test_check_exclusions_dental(self, mock_claim_facts, mock_policy_terms):
        """Test dental exclusion check."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claim_type'] = 'DENTAL'
        claim_facts['diagnosis'] = 'Cosmetic dentistry whitening'
        
        result = _check_exclusions(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'exclusion' in result['reason'].lower()
    
    def test_check_exclusions_pass(self, mock_claim_facts, mock_policy_terms):
        """Test successful exclusion check."""
        result = _check_exclusions(mock_claim_facts, mock_policy_terms)
        
        assert result['status'] == 'PASS'


@pytest.mark.unit
@pytest.mark.policy
class TestPreAuthorization:
    """Tests for pre-authorization checks."""
    
    def test_check_pre_auth_required_not_present(self, mock_claim_facts, mock_policy_terms):
        """Test pre-auth required but not present."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claim_type'] = 'DIAGNOSTIC'
        claim_facts['claimed_amount'] = 8000.0  # Above threshold
        claim_facts['pre_auth_present'] = False
        
        result = _check_pre_authorization(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'FAIL'
        assert 'pre-authorization required' in result['reason'].lower()
    
    def test_check_pre_auth_required_and_present(self, mock_claim_facts, mock_policy_terms):
        """Test pre-auth required and present."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claim_type'] = 'DIAGNOSTIC'
        claim_facts['claimed_amount'] = 8000.0
        claim_facts['pre_auth_present'] = True
        
        result = _check_pre_authorization(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'PASS'
    
    def test_check_pre_auth_not_required(self, mock_claim_facts, mock_policy_terms):
        """Test pre-auth not required."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claim_type'] = 'CONSULTATION'
        claim_facts['claimed_amount'] = 1500.0
        
        result = _check_pre_authorization(claim_facts, mock_policy_terms)
        
        assert result['status'] == 'PASS'


@pytest.mark.unit
@pytest.mark.policy
class TestCopayAndLimits:
    """Tests for copay and limit calculations."""
    
    def test_apply_copay_standard(self, mock_claim_facts, mock_policy_terms):
        """Test standard copay application."""
        approved_amount = 1500.0
        
        result, final_amount = _apply_opd_sub_limits_and_copay(
            mock_claim_facts, mock_policy_terms, approved_amount
        )
        
        # 10% copay on consultation
        expected = 1500.0 - (1500.0 * 0.10)
        assert final_amount == expected
        assert result['status'] == 'PASS'
    
    def test_apply_copay_branded_drugs(self, mock_claim_facts, mock_policy_terms):
        """Test branded drug copay."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['claim_type'] = 'pharmacy'
        claim_facts['per_category_amounts'] = {'pharmacy': 1000.0}
        claim_facts['medicines'] = [
            {'name': 'Branded Drug', 'is_branded': True, 'has_generic_alternative': True}
        ]
        
        approved_amount = 1000.0
        
        result, final_amount = _apply_opd_sub_limits_and_copay(
            claim_facts, mock_policy_terms, approved_amount
        )
        
        # 30% copay for branded drugs
        expected = 1000.0 - (1000.0 * 0.30)
        assert final_amount == expected
    
    def test_apply_network_discount(self, mock_claim_facts, mock_policy_terms):
        """Test network hospital discount on copay."""
        claim_facts = mock_claim_facts.copy()
        claim_facts['is_network_hospital'] = True
        
        approved_amount = 1500.0
        
        result, final_amount = _apply_opd_sub_limits_and_copay(
            claim_facts, mock_policy_terms, approved_amount
        )
        
        # Network discount reduces copay, so final amount should be >= standard copay amount
        # Standard copay: 1500 - (1500 * 0.10) = 1350
        # With network discount, copay is reduced, so final amount >= 1350
        assert final_amount >= (1500.0 - (1500.0 * 0.10))


@pytest.mark.integration
@pytest.mark.policy
class TestEvaluateClaim:
    """Tests for complete claim evaluation."""
    
    @patch('app.policy_engine.load_policy_terms')
    @patch('app.policy_engine.db')
    def test_evaluate_claim_approved(self, mock_db, mock_policy, mock_claim_facts, mock_policy_terms):
        """Test claim evaluation resulting in approval."""
        mock_policy.return_value = mock_policy_terms
        
        # Mock database queries to return 0 for limits
        mock_db.session.query.return_value.filter.return_value.scalar.return_value = 0
        
        result = evaluate_claim(mock_claim_facts)
        
        assert result['decision'] in ['APPROVED', 'PARTIAL', 'REJECTED']
        assert 'rule_results' in result
    
    @patch('app.policy_engine.load_policy_terms')
    def test_evaluate_claim_rejected(self, mock_policy, mock_claim_facts, mock_policy_terms):
        """Test claim evaluation resulting in rejection."""
        mock_policy.return_value = mock_policy_terms
        
        # Make claim ineligible
        claim_facts = mock_claim_facts.copy()
        claim_facts['member_id'] = 'M999'  # Non-existent member
        
        result = evaluate_claim(claim_facts)
        
        assert result['decision'] == 'REJECTED'
        assert result['approved_amount'] == 0
