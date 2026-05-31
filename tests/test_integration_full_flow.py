"""Integration tests for full claim processing flow."""
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from decimal import Decimal
from app.models.claim import Claim


@pytest.mark.integration
@pytest.mark.slow
class TestFullClaimFlow:
    """Integration tests for complete claim processing flow."""
    
    @patch('app.routes.claims.process_claim_documents')
    @patch('app.routes.claims.load_policy_terms')
    def test_full_claim_submission_to_processing(
        self, mock_policy, mock_task, client, session, mock_policy_terms, tmp_path
    ):
        """Test full flow from claim submission to processing."""
        # Setup mocks
        mock_policy.return_value = mock_policy_terms
        mock_task_result = MagicMock()
        mock_task_result.id = 'test-task-id'
        mock_task.delay.return_value = mock_task_result
        
        # Create test file
        test_file = tmp_path / "prescription.pdf"
        test_file.write_bytes(b'test prescription content')
        
        # Submit claim
        data = {
            'member_id': 'M001',
            'patient_name': 'John Doe',
            'relationship': 'SELF',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-01-15',
            'submission_date': '2024-01-20',
            'claimed_amount': '1500.00',
            'hospital_name': 'Apollo Hospital',
            'pre_auth_present': 'false',
            'documents': [(BytesIO(b'test prescription content'), 'prescription.pdf')],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        # Verify response
        assert response.status_code == 202
        response_data = response.get_json()
        assert 'claim_id' in response_data
        assert response_data['status'] == 'PROCESSING'
        
        # Verify claim was created in database
        from app.models.claim import Claim
        claim = session.query(Claim).filter_by(id=response_data['claim_id']).first()
        assert claim is not None
        assert claim.member_id == 'M001'
        assert claim.status == 'PROCESSING'
    
    @patch('app.routes.claims.load_policy_terms')
    def test_full_claim_rejection_incomplete_docs(
        self, mock_policy, client, session, mock_policy_terms, tmp_path
    ):
        """Test full flow with incomplete documents leading to rejection."""
        # Setup policy requiring multiple documents
        policy = mock_policy_terms.copy()
        policy['document_requirements']['CONSULTATION'] = {
            'required': ['PRESCRIPTION', 'HOSPITAL_BILL'],
            'optional': []
        }
        mock_policy.return_value = policy
        
        # Create test file
        test_file = tmp_path / "prescription.pdf"
        test_file.write_bytes(b'test prescription content')
        
        # Submit claim with only one document
        with open(test_file, 'rb') as f:
            data = {
                'member_id': 'M001',
                'patient_name': 'John Doe',
                'relationship': 'SELF',
                'claim_type': 'CONSULTATION',
                'treatment_date': '2024-01-15',
                'submission_date': '2024-01-20',
                'claimed_amount': '1500.00',
                'hospital_name': 'Apollo Hospital',
                'pre_auth_present': 'false',
                'documents': [(f, 'prescription.pdf')],
                'document_tags': ['PRESCRIPTION']
            }
            
            response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        # Verify rejection
        assert response.status_code == 400
        response_data = response.get_json()
        assert response_data['status'] == 'DOCS_INCOMPLETE'
        assert 'HOSPITAL_BILL' in response_data['missing']
    
    def test_claim_retrieval_after_creation(
        self, client, session, sample_claim_with_documents
    ):
        """Test retrieving claim details after creation."""
        claim = sample_claim_with_documents
        
        # Get claim details
        response = client.get(f'/claims/{claim.id}')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['claim']['id'] == claim.id
        assert len(data['claim']['documents']) == 1
        assert len(data['claim']['traces']) >= 0
    
    def test_list_claims_after_multiple_submissions(
        self, client, session, sample_claim
    ):
        """Test listing claims after multiple submissions."""
        # Create additional claims
        from app.models.claim import Claim
        from datetime import date
        
        claim2 = Claim(
            member_id='M002',
            claim_type='DIAGNOSTIC',
            treatment_date=date(2024, 1, 16),
            submission_date=date(2024, 1, 21),
            claimed_amount=Decimal('2000.00'),
            status='PENDING'
        )
        session.add(claim2)
        session.commit()
        
        # List all claims
        response = client.get('/claims')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] >= 2
        assert len(data['claims']) >= 2
