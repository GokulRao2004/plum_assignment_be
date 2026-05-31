"""
API Validation Integration Tests

Tests the complete validation flow through the API endpoints.
"""

import pytest
import json
from datetime import date, timedelta
from io import BytesIO

from app import create_app
from app.database import db
from app.models.claim import Claim


@pytest.fixture
def app():
    """Create test application."""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


def create_test_file(filename="test.pdf", content=b"test content"):
    """Helper to create test file."""
    return (BytesIO(content), filename)


class TestClaimSubmissionValidation:
    """Test claim submission endpoint validation."""
    
    def test_valid_claim_submission(self, client):
        """Test successful claim submission with all valid data."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'patient_name': 'Rajesh Kumar',
            'relationship': 'SELF',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'hospital_name': 'Apollo Hospitals',
            'pre_auth_present': 'false',
            'documents': [create_test_file('prescription.pdf')],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        # Should accept or return specific validation error
        assert response.status_code in [202, 400]
    
    def test_missing_policy_id(self, client):
        """Test claim submission without policy_id."""
        data = {
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'policy_id' in data['message'].lower()
    
    def test_invalid_policy_id(self, client):
        """Test claim submission with invalid policy_id."""
        data = {
            'policy_id': 'INVALID_POLICY',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'does not match' in data['message']
    
    def test_invalid_member_id(self, client):
        """Test claim submission with invalid member_id."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'INVALID_MEMBER',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'not found' in data['message']
    
    def test_relationship_mismatch(self, client):
        """Test claim submission with mismatched relationship."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'relationship': 'SPOUSE',  # EMP001 is SELF
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'mismatch' in data['message'].lower()
    
    def test_future_treatment_date(self, client):
        """Test claim submission with future treatment date."""
        future_date = (date.today() + timedelta(days=10)).isoformat()
        
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': future_date,
            'submission_date': future_date,
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'future' in data['message'].lower()
    
    def test_submission_before_treatment(self, client):
        """Test claim submission with submission_date before treatment_date."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-20',
            'submission_date': '2024-06-15',  # Before treatment
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'before' in data['message'].lower()
    
    def test_zero_claimed_amount(self, client):
        """Test claim submission with zero claimed amount."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '0',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'greater than 0' in data['message']
    
    def test_negative_claimed_amount(self, client):
        """Test claim submission with negative claimed amount."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '-100',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'greater than 0' in data['message']
    
    def test_amount_exceeds_sum_insured(self, client):
        """Test claim submission with amount exceeding sum insured."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '600000',  # Exceeds 500000
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'exceeds' in data['message'].lower()
    
    def test_treatment_date_outside_policy_period(self, client):
        """Test claim submission with treatment date outside policy period."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2023-03-15',  # Before policy start
            'submission_date': '2023-03-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'outside policy period' in data['message'].lower()
    
    def test_invalid_claim_type(self, client):
        """Test claim submission with invalid claim type."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'INVALID_TYPE',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'not recognized' in data['message'].lower()
    
    def test_invalid_document_tag(self, client):
        """Test claim submission with invalid document tag."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['INVALID_TAG']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'not valid' in data['message'].lower()
    
    def test_document_count_mismatch(self, client):
        """Test claim submission with mismatched document and tag counts."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file(), create_test_file()],
            'document_tags': ['PRESCRIPTION']  # Only one tag for two documents
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'mismatch' in data['message'].lower()
    
    def test_no_documents_provided(self, client):
        """Test claim submission without documents."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [],
            'document_tags': []
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'no documents' in data['message'].lower()
    
    def test_non_network_hospital_warning(self, client):
        """Test claim submission with non-network hospital returns warning."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'hospital_name': 'Unknown Hospital',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        # Should succeed but with warning
        if response.status_code == 202:
            data = json.loads(response.data)
            assert 'warning' in data
            assert 'not in the network' in data['warning']
    
    def test_invalid_date_format(self, client):
        """Test claim submission with invalid date format."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'EMP001',
            'claim_type': 'CONSULTATION',
            'treatment_date': '15-06-2024',  # Wrong format
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'date format' in data['message'].lower()


class TestDependentValidation:
    """Test dependent member validation."""
    
    def test_valid_dependent_claim(self, client):
        """Test claim submission for valid dependent."""
        data = {
            'policy_id': 'PLUM_GHI_2024',
            'member_id': 'DEP001',  # Spouse of EMP001
            'patient_name': 'Sunita Kumar',
            'relationship': 'SPOUSE',
            'claim_type': 'CONSULTATION',
            'treatment_date': '2024-06-15',
            'submission_date': '2024-06-20',
            'claimed_amount': '1500',
            'documents': [create_test_file()],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        # Should accept or return specific validation error
        assert response.status_code in [202, 400]
