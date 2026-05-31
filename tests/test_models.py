"""Tests for database models."""
import pytest
from datetime import datetime, date
from decimal import Decimal
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.models.claim_trace import ClaimTrace


@pytest.mark.unit
@pytest.mark.models
class TestClaimModel:
    """Tests for Claim model."""
    
    def test_create_claim(self, session):
        """Test creating a new claim."""
        claim = Claim(
            member_id='M001',
            patient_name='John Doe',
            relationship='SELF',
            claim_type='CONSULTATION',
            treatment_date=date(2024, 1, 15),
            submission_date=date(2024, 1, 20),
            claimed_amount=Decimal('1500.00'),
            hospital_name='Apollo Hospital',
            status='PENDING'
        )
        session.add(claim)
        session.commit()
        
        assert claim.id is not None
        assert claim.member_id == 'M001'
        assert claim.status == 'PENDING'
        assert claim.claimed_amount == Decimal('1500.00')
    
    def test_claim_relationships(self, session, sample_claim_with_documents):
        """Test claim relationships with documents and traces."""
        claim = sample_claim_with_documents
        
        assert len(claim.documents) == 1
        assert claim.documents[0].doc_tag == 'PRESCRIPTION'
    
    def test_claim_defaults(self, session):
        """Test claim default values."""
        claim = Claim(
            member_id='M001',
            claim_type='CONSULTATION',
            treatment_date=date(2024, 1, 15),
            submission_date=date(2024, 1, 20),
            claimed_amount=Decimal('1500.00')
        )
        session.add(claim)
        session.commit()
        
        assert claim.status == 'PENDING'
        assert claim.is_network_hospital is False
        assert claim.pre_auth_present is False
        assert claim.created_at is not None
        assert claim.updated_at is not None
    
    def test_claim_update(self, session, sample_claim):
        """Test updating claim fields."""
        claim = sample_claim
        original_updated_at = claim.updated_at
        
        claim.status = 'COMPLETED'
        claim.decision = 'APPROVED'
        claim.approved_amount = Decimal('1350.00')
        session.commit()
        
        assert claim.status == 'COMPLETED'
        assert claim.decision == 'APPROVED'
        assert claim.approved_amount == Decimal('1350.00')


@pytest.mark.unit
@pytest.mark.models
class TestClaimDocumentModel:
    """Tests for ClaimDocument model."""
    
    def test_create_document(self, session, sample_claim):
        """Test creating a claim document."""
        document = ClaimDocument(
            claim_id=sample_claim.id,
            file_path='/path/to/file.pdf',
            original_filename='prescription.pdf',
            mime_type='application/pdf',
            doc_tag='PRESCRIPTION'
        )
        session.add(document)
        session.commit()
        
        assert document.id is not None
        assert document.claim_id == sample_claim.id
        assert document.doc_tag == 'PRESCRIPTION'
    
    def test_document_with_extracted_fields(self, session, sample_claim):
        """Test document with extracted fields."""
        document = ClaimDocument(
            claim_id=sample_claim.id,
            file_path='/path/to/file.pdf',
            doc_tag='PRESCRIPTION',
            ocr_text='Sample OCR text',
            extracted_fields={
                'doctor_name': 'Dr. Smith',
                'diagnosis': 'Common Cold'
            },
            doc_confidence=Decimal('0.95')
        )
        session.add(document)
        session.commit()
        
        assert document.extracted_fields['doctor_name'] == 'Dr. Smith'
        assert document.doc_confidence == Decimal('0.95')


@pytest.mark.unit
@pytest.mark.models
class TestClaimTraceModel:
    """Tests for ClaimTrace model."""
    
    def test_create_trace(self, session, sample_claim):
        """Test creating a claim trace."""
        trace = ClaimTrace(
            claim_id=sample_claim.id,
            step='DOC_PRESENCE_CHECK',
            status='PASS',
            details={'message': 'All documents present'}
        )
        session.add(trace)
        session.commit()
        
        assert trace.id is not None
        assert trace.claim_id == sample_claim.id
        assert trace.step == 'DOC_PRESENCE_CHECK'
        assert trace.status == 'PASS'
    
    def test_trace_ordering(self, session, sample_claim):
        """Test trace creation timestamps."""
        trace1 = ClaimTrace(
            claim_id=sample_claim.id,
            step='STEP_1',
            status='PASS',
            details={}
        )
        session.add(trace1)
        session.commit()
        
        trace2 = ClaimTrace(
            claim_id=sample_claim.id,
            step='STEP_2',
            status='PASS',
            details={}
        )
        session.add(trace2)
        session.commit()
        
        assert trace2.created_at >= trace1.created_at
