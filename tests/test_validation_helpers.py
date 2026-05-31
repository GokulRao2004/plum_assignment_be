"""
Unit Tests for Validation Helpers

Tests all validation functions against policy_terms.json rules.
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from app.utils.validation_helpers import (
    validate_policy_id,
    validate_member_id,
    validate_relationship,
    validate_dependent_member,
    validate_claim_type,
    validate_treatment_date,
    validate_submission_date,
    validate_claimed_amount,
    validate_hospital_name,
    validate_document_tags,
    validate_diagnosis_against_exclusions,
    validate_procedures_against_coverage,
    validate_alternative_medicine_system,
    validate_per_category_amounts,
    validate_family_floater_relationships
)


@pytest.fixture
def mock_policy_terms():
    """Mock policy terms for testing."""
    return {
        "policy_id": "PLUM_GHI_2024",
        "policy_holder": {
            "policy_start_date": "2024-04-01",
            "policy_end_date": "2025-03-31"
        },
        "coverage": {
            "sum_insured_per_employee": 500000,
            "family_floater": {
                "enabled": True,
                "covered_relationships": ["SELF", "SPOUSE", "CHILDREN", "PARENTS"]
            }
        },
        "opd_categories": {
            "consultation": {"covered": True},
            "diagnostic": {"covered": True},
            "pharmacy": {"covered": True},
            "dental": {
                "covered": True,
                "excluded_procedures": ["Teeth Whitening", "Veneers", "Orthodontic Treatment"]
            },
            "vision": {
                "covered": True,
                "excluded_items": ["LASIK Surgery", "Cosmetic Eye Surgery"]
            },
            "alternative_medicine": {
                "covered": True,
                "covered_systems": ["Ayurveda", "Homeopathy", "Unani"]
            }
        },
        "exclusions": {
            "conditions": ["Self-inflicted injuries", "Substance abuse treatment", "Cosmetic procedures"],
            "dental_exclusions": ["Teeth whitening", "Orthodontic treatment"],
            "vision_exclusions": ["LASIK", "Refractive surgery"]
        },
        "network_hospitals": ["Apollo Hospitals", "Fortis Healthcare", "Max Healthcare"],
        "members": [
            {
                "member_id": "EMP001",
                "name": "Rajesh Kumar",
                "relationship": "SELF"
            },
            {
                "member_id": "DEP001",
                "name": "Sunita Kumar",
                "relationship": "SPOUSE",
                "primary_member_id": "EMP001"
            },
            {
                "member_id": "DEP002",
                "name": "Arjun Kumar",
                "relationship": "CHILD",
                "primary_member_id": "EMP001"
            }
        ]
    }


class TestPolicyIdValidation:
    def test_valid_policy_id(self, mock_policy_terms):
        is_valid, error = validate_policy_id("PLUM_GHI_2024", mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_invalid_policy_id(self, mock_policy_terms):
        is_valid, error = validate_policy_id("INVALID_POLICY", mock_policy_terms)
        assert is_valid is False
        assert "does not match" in error
    
    def test_empty_policy_id(self, mock_policy_terms):
        is_valid, error = validate_policy_id("", mock_policy_terms)
        assert is_valid is False
        assert "required" in error.lower()


class TestMemberIdValidation:
    def test_valid_member_id(self, mock_policy_terms):
        is_valid, error, member = validate_member_id("EMP001", mock_policy_terms)
        assert is_valid is True
        assert error is None
        assert member is not None
        assert member["name"] == "Rajesh Kumar"
    
    def test_invalid_member_id(self, mock_policy_terms):
        is_valid, error, member = validate_member_id("INVALID_MEMBER", mock_policy_terms)
        assert is_valid is False
        assert "not found" in error
        assert member is None
    
    def test_empty_member_id(self, mock_policy_terms):
        is_valid, error, member = validate_member_id("", mock_policy_terms)
        assert is_valid is False
        assert "required" in error.lower()


class TestRelationshipValidation:
    def test_matching_relationship(self, mock_policy_terms):
        member = mock_policy_terms["members"][0]  # SELF
        is_valid, error = validate_relationship("SELF", member)
        assert is_valid is True
        assert error is None
    
    def test_mismatched_relationship(self, mock_policy_terms):
        member = mock_policy_terms["members"][0]  # SELF
        is_valid, error = validate_relationship("SPOUSE", member)
        assert is_valid is False
        assert "does not match" in error
    
    def test_empty_relationship(self, mock_policy_terms):
        member = mock_policy_terms["members"][0]
        is_valid, error = validate_relationship("", member)
        assert is_valid is True  # Relationship is optional


class TestDependentMemberValidation:
    def test_valid_dependent(self, mock_policy_terms):
        member = mock_policy_terms["members"][1]  # DEP001 (SPOUSE)
        is_valid, error = validate_dependent_member(member, mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_self_member(self, mock_policy_terms):
        member = mock_policy_terms["members"][0]  # EMP001 (SELF)
        is_valid, error = validate_dependent_member(member, mock_policy_terms)
        assert is_valid is True  # SELF members don't need validation
    
    def test_dependent_without_primary(self, mock_policy_terms):
        member = {
            "member_id": "DEP999",
            "relationship": "SPOUSE"
            # Missing primary_member_id
        }
        is_valid, error = validate_dependent_member(member, mock_policy_terms)
        assert is_valid is False
        assert "no primary member" in error.lower()


class TestClaimTypeValidation:
    def test_valid_covered_claim_type(self, mock_policy_terms):
        is_valid, error, config = validate_claim_type("consultation", mock_policy_terms)
        assert is_valid is True
        assert error is None
        assert config is not None
    
    def test_invalid_claim_type(self, mock_policy_terms):
        is_valid, error, config = validate_claim_type("invalid_type", mock_policy_terms)
        assert is_valid is False
        assert "not recognized" in error
    
    def test_uncovered_claim_type(self, mock_policy_terms):
        mock_policy_terms["opd_categories"]["test_type"] = {"covered": False}
        is_valid, error, config = validate_claim_type("test_type", mock_policy_terms)
        assert is_valid is False
        assert "not covered" in error


class TestTreatmentDateValidation:
    def test_valid_treatment_date(self, mock_policy_terms):
        treatment_date = date(2024, 6, 15)  # Within policy period
        is_valid, error = validate_treatment_date(treatment_date, mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_future_treatment_date(self, mock_policy_terms):
        future_date = date.today() + timedelta(days=10)
        is_valid, error = validate_treatment_date(future_date, mock_policy_terms)
        assert is_valid is False
        assert "cannot be in the future" in error
    
    def test_treatment_date_before_policy_start(self, mock_policy_terms):
        treatment_date = date(2024, 3, 15)  # Before policy start
        is_valid, error = validate_treatment_date(treatment_date, mock_policy_terms)
        assert is_valid is False
        assert "outside policy period" in error
    
    def test_treatment_date_after_policy_end(self, mock_policy_terms):
        treatment_date = date(2025, 4, 15)  # After policy end
        is_valid, error = validate_treatment_date(treatment_date, mock_policy_terms)
        assert is_valid is False
        assert "outside policy period" in error


class TestSubmissionDateValidation:
    def test_valid_submission_date(self):
        treatment_date = date(2024, 6, 15)
        submission_date = date(2024, 6, 20)
        is_valid, error = validate_submission_date(submission_date, treatment_date)
        assert is_valid is True
        assert error is None
    
    def test_same_day_submission(self):
        treatment_date = date(2024, 6, 15)
        submission_date = date(2024, 6, 15)
        is_valid, error = validate_submission_date(submission_date, treatment_date)
        assert is_valid is True
    
    def test_submission_before_treatment(self):
        treatment_date = date(2024, 6, 15)
        submission_date = date(2024, 6, 10)
        is_valid, error = validate_submission_date(submission_date, treatment_date)
        assert is_valid is False
        assert "cannot be before" in error


class TestClaimedAmountValidation:
    def test_valid_claimed_amount(self, mock_policy_terms):
        is_valid, error = validate_claimed_amount(Decimal("5000"), mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_zero_claimed_amount(self, mock_policy_terms):
        is_valid, error = validate_claimed_amount(Decimal("0"), mock_policy_terms)
        assert is_valid is False
        assert "greater than 0" in error
    
    def test_negative_claimed_amount(self, mock_policy_terms):
        is_valid, error = validate_claimed_amount(Decimal("-100"), mock_policy_terms)
        assert is_valid is False
        assert "greater than 0" in error
    
    def test_amount_exceeds_sum_insured(self, mock_policy_terms):
        is_valid, error = validate_claimed_amount(Decimal("600000"), mock_policy_terms)
        assert is_valid is False
        assert "exceeds sum insured" in error


class TestHospitalNameValidation:
    def test_network_hospital(self, mock_policy_terms):
        is_valid, is_network, warning = validate_hospital_name("Apollo Hospitals", mock_policy_terms)
        assert is_valid is True
        assert is_network is True
        assert warning is None
    
    def test_non_network_hospital(self, mock_policy_terms):
        is_valid, is_network, warning = validate_hospital_name("Unknown Hospital", mock_policy_terms)
        assert is_valid is True
        assert is_network is False
        assert "not in the network" in warning
    
    def test_partial_match_network_hospital(self, mock_policy_terms):
        is_valid, is_network, warning = validate_hospital_name("Apollo Hospitals Delhi", mock_policy_terms)
        assert is_valid is True
        assert is_network is True


class TestDocumentTagsValidation:
    def test_valid_document_tags(self):
        tags = ["PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT"]
        is_valid, error = validate_document_tags(tags)
        assert is_valid is True
        assert error is None
    
    def test_invalid_document_tag(self):
        tags = ["PRESCRIPTION", "INVALID_TAG"]
        is_valid, error = validate_document_tags(tags)
        assert is_valid is False
        assert "not valid" in error


class TestDiagnosisExclusionsValidation:
    def test_valid_diagnosis(self, mock_policy_terms):
        is_valid, error = validate_diagnosis_against_exclusions("Fever", "CONSULTATION", mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_excluded_diagnosis(self, mock_policy_terms):
        is_valid, error = validate_diagnosis_against_exclusions("Cosmetic surgery", "CONSULTATION", mock_policy_terms)
        assert is_valid is False
        assert "excluded" in error.lower()
    
    def test_dental_exclusion(self, mock_policy_terms):
        is_valid, error = validate_diagnosis_against_exclusions("Teeth whitening", "DENTAL", mock_policy_terms)
        assert is_valid is False
        assert "excluded" in error.lower()


class TestProceduresCoverageValidation:
    def test_valid_dental_procedure(self, mock_policy_terms):
        procedures = ["Root Canal Treatment"]
        is_valid, error = validate_procedures_against_coverage(procedures, "DENTAL", mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_excluded_dental_procedure(self, mock_policy_terms):
        procedures = ["Teeth Whitening"]
        is_valid, error = validate_procedures_against_coverage(procedures, "DENTAL", mock_policy_terms)
        assert is_valid is False
        assert "excluded" in error.lower()
    
    def test_excluded_vision_item(self, mock_policy_terms):
        procedures = ["LASIK Surgery"]
        is_valid, error = validate_procedures_against_coverage(procedures, "VISION", mock_policy_terms)
        assert is_valid is False
        assert "excluded" in error.lower()


class TestAlternativeMedicineSystemValidation:
    def test_covered_system(self, mock_policy_terms):
        is_valid, error = validate_alternative_medicine_system("Ayurveda treatment", mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_uncovered_system(self, mock_policy_terms):
        is_valid, error = validate_alternative_medicine_system("Acupuncture treatment", mock_policy_terms)
        assert is_valid is False
        assert "not covered" in error


class TestPerCategoryAmountsValidation:
    def test_matching_amounts(self):
        per_category = {"consultation": 1000.0, "diagnostic": 500.0}
        is_valid, error = validate_per_category_amounts(per_category, 1500.0)
        assert is_valid is True
        assert error is None
    
    def test_mismatched_amounts(self):
        per_category = {"consultation": 1000.0, "diagnostic": 500.0}
        is_valid, error = validate_per_category_amounts(per_category, 2000.0)
        assert is_valid is False
        assert "does not match" in error


class TestFamilyFloaterRelationshipsValidation:
    def test_covered_relationship(self, mock_policy_terms):
        member = mock_policy_terms["members"][1]  # SPOUSE
        is_valid, error = validate_family_floater_relationships(member, mock_policy_terms)
        assert is_valid is True
        assert error is None
    
    def test_uncovered_relationship(self, mock_policy_terms):
        member = {
            "member_id": "TEST001",
            "relationship": "UNCLE"  # Not in covered_relationships
        }
        is_valid, error = validate_family_floater_relationships(member, mock_policy_terms)
        assert is_valid is False
        assert "not covered" in error
