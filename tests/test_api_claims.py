"""Tests for claims API endpoints."""
import pytest
import json
from io import BytesIO
from unittest.mock import patch, MagicMock
from decimal import Decimal


@pytest.mark.api
class TestClaimsListEndpoint:
    """Tests for GET /claims endpoint."""
    
    def test_list_claims_empty(self, client, session):
        """Test listing claims when database is empty."""
        response = client.get('/claims')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['count'] == 0
        assert data['claims'] == []
    
    def test_list_claims_with_data(self, client, session, sample_claim):
        """Test listing claims with data."""
        response = client.get('/claims')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['count'] == 1
        assert len(data['claims']) == 1
        assert data['claims'][0]['member_id'] == 'M001'
        assert data['claims'][0]['status'] == 'PENDING'


@pytest.mark.api
class TestClaimDetailEndpoint:
    """Tests for GET /claims/<claim_id> endpoint."""
    
    def test_get_claim_not_found(self, client, session):
        """Test getting a non-existent claim."""
        # Use a valid UUID format
        import uuid
        non_existent_id = str(uuid.uuid4())
        response = client.get(f'/claims/{non_existent_id}')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_get_claim_success(self, client, session, sample_claim):
        """Test getting an existing claim."""
        response = client.get(f'/claims/{sample_claim.id}')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'claim' in data
        assert data['claim']['id'] == sample_claim.id
        assert data['claim']['member_id'] == 'M001'
    
    def test_get_claim_with_documents(self, client, session, sample_claim_with_documents):
        """Test getting claim with documents."""
        claim = sample_claim_with_documents
        response = client.get(f'/claims/{claim.id}')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['claim']['documents']) == 1
        assert data['claim']['documents'][0]['doc_tag'] == 'PRESCRIPTION'


@pytest.mark.api
class TestCreateClaimEndpoint:
    """Tests for POST /claims endpoint."""
    
    def test_create_claim_missing_documents(self, client, session, sample_claim_data):
        """Test creating claim without documents."""
        response = client.post('/claims', data=sample_claim_data)
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'document' in data['message'].lower()
    
    def test_create_claim_missing_required_fields(self, client, session):
        """Test creating claim with missing required fields."""
        data = {
            'member_id': 'M001',
            # Missing other required fields
        }
        
        # Create a dummy file
        data['documents'] = (BytesIO(b'test content'), 'test.pdf')
        data['document_tags'] = 'PRESCRIPTION'
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        response_data = json.loads(response.data)
        assert 'error' in response_data
    
    def test_create_claim_document_tag_mismatch(self, client, session, sample_claim_data):
        """Test creating claim with mismatched document count and tags."""
        data = sample_claim_data.copy()
        data['documents'] = [
            (BytesIO(b'test content 1'), 'test1.pdf'),
            (BytesIO(b'test content 2'), 'test2.pdf')
        ]
        data['document_tags'] = ['PRESCRIPTION']  # Only one tag for two documents
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        response_data = json.loads(response.data)
        assert 'match' in response_data['message'].lower()
    
    @patch('app.routes.claims.process_claim_documents')
    @patch('app.routes.claims.load_policy_terms')
    def test_create_claim_success(self, mock_policy, mock_task, client, session, sample_claim_data, tmp_path):
        """Test successful claim creation."""
        # Mock policy terms
        mock_policy.return_value = {
            'document_requirements': {
                'CONSULTATION': {
                    'required': ['PRESCRIPTION'],
                    'optional': []
                }
            }
        }
        
        # Mock Celery task with proper return value
        mock_task_result = MagicMock()
        mock_task_result.id = 'test-task-id'
        mock_task.delay.return_value = mock_task_result
        
        # Use BytesIO for file upload - send as list
        data = {
            'member_id': sample_claim_data['member_id'],
            'patient_name': sample_claim_data['patient_name'],
            'relationship': sample_claim_data['relationship'],
            'claim_type': sample_claim_data['claim_type'],
            'treatment_date': sample_claim_data['treatment_date'],
            'submission_date': sample_claim_data['submission_date'],
            'claimed_amount': sample_claim_data['claimed_amount'],
            'hospital_name': sample_claim_data['hospital_name'],
            'pre_auth_present': sample_claim_data.get('pre_auth_present', 'false'),
            'documents': [(BytesIO(b'test prescription content'), 'prescription.pdf')],
            'document_tags': ['PRESCRIPTION']
        }
        
        response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 202
        response_data = json.loads(response.data)
        assert 'claim_id' in response_data
        assert response_data['status'] == 'PROCESSING'
        assert 'task_id' in response_data
    
    @patch('app.utils.policy_loader.load_policy_terms')
    def test_create_claim_incomplete_documents(self, mock_policy, client, session, sample_claim_data, tmp_path):
        """Test claim creation with incomplete documents."""
        # Mock policy terms
        mock_policy.return_value = {
            'document_requirements': {
                'CONSULTATION': {
                    'required': ['PRESCRIPTION', 'HOSPITAL_BILL'],
                    'optional': []
                }
            }
        }
        
        data = sample_claim_data.copy()
        
        # Create test file
        test_file = tmp_path / "prescription.pdf"
        test_file.write_bytes(b'test content')
        
        with open(test_file, 'rb') as f:
            data['documents'] = [(f, 'prescription.pdf')]
            data['document_tags'] = ['PRESCRIPTION']  # Missing HOSPITAL_BILL
            
            response = client.post('/claims', data=data, content_type='multipart/form-data')
        
        assert response.status_code == 400
        response_data = json.loads(response.data)
        assert response_data['status'] == 'DOCS_INCOMPLETE'
        assert 'missing' in response_data


@pytest.mark.api
class TestTaskStatusEndpoint:
    """Tests for GET /tasks/<task_id> endpoint."""
    
    @patch('app.routes.claims.celery')
    def test_get_task_status_pending(self, mock_celery, client):
        """Test getting status of pending task."""
        mock_result = MagicMock()
        mock_result.state = 'PENDING'
        mock_celery.AsyncResult.return_value = mock_result
        
        response = client.get('/tasks/test-task-id')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['state'] == 'PENDING'
    
    @patch('app.routes.claims.celery')
    def test_get_task_status_processing(self, mock_celery, client):
        """Test getting status of processing task."""
        mock_result = MagicMock()
        mock_result.state = 'PROCESSING'
        mock_result.info = {'step': 'OCR', 'progress': 50}
        mock_celery.AsyncResult.return_value = mock_result
        
        response = client.get('/tasks/test-task-id')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['state'] == 'PROCESSING'
        assert data['progress'] == 50
    
    @patch('app.routes.claims.celery')
    def test_get_task_status_success(self, mock_celery, client):
        """Test getting status of completed task."""
        mock_result = MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'decision': 'APPROVED', 'approved_amount': 1350.0}
        mock_celery.AsyncResult.return_value = mock_result
        
        response = client.get('/tasks/test-task-id')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['state'] == 'SUCCESS'
        assert data['result']['decision'] == 'APPROVED'
