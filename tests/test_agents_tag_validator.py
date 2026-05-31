"""Tests for tag validation agent."""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from app.agents.tag_validator import (
    validate_document_fields,
    validate_prescription_fields,
    validate_hospital_bill_fields,
    validate_lab_report_fields,
    validate_pharmacy_bill_fields,
    adjust_confidence_for_validation,
    validate_tags_for_claim
)


@pytest.mark.unit
@pytest.mark.agents
class TestDocumentFieldValidation:
    """Tests for document field validation functions."""
    
    def test_validate_prescription_pass(self):
        """Test prescription validation with all required fields."""
        extracted_fields = {
            'doctor_name': 'Dr. Smith',
            'patient_name': 'John Doe',
            'diagnosis': 'Common Cold',
            'medicines': [{'name': 'Paracetamol'}],
            'date': '2024-01-15',
            'doctor_reg_no': 'REG123'
        }
        
        result = validate_prescription_fields(extracted_fields)
        
        assert result['valid'] is True
        assert result['severity'] == 'PASS'
        assert len(result['missing_fields']) == 0
    
    def test_validate_prescription_missing_doctor(self):
        """Test prescription validation with missing doctor name."""
        extracted_fields = {
            'patient_name': 'John Doe',
            'diagnosis': 'Common Cold'
        }
        
        result = validate_prescription_fields(extracted_fields)
        
        assert result['valid'] is False
        assert result['severity'] == 'FAIL'
        assert 'doctor_name' in result['missing_fields']
    
    def test_validate_prescription_missing_diagnosis_and_medicines(self):
        """Test prescription validation with missing diagnosis and medicines."""
        extracted_fields = {
            'doctor_name': 'Dr. Smith',
            'patient_name': 'John Doe'
        }
        
        result = validate_prescription_fields(extracted_fields)
        
        assert result['valid'] is False
        assert result['severity'] == 'FAIL'
        assert 'diagnosis_or_medicines' in result['missing_fields']
    
    def test_validate_hospital_bill_pass(self):
        """Test hospital bill validation with all required fields."""
        extracted_fields = {
            'bill_no': 'BILL123',
            'total_amount': 1500.0,
            'hospital_name': 'Apollo Hospital',
            'patient_name': 'John Doe',
            'bill_date': '2024-01-15',
            'line_items': [{'description': 'Consultation', 'amount': 1500.0}]
        }
        
        result = validate_hospital_bill_fields(extracted_fields)
        
        assert result['valid'] is True
        assert result['severity'] == 'PASS'
    
    def test_validate_hospital_bill_missing_bill_no(self):
        """Test hospital bill validation with missing bill number."""
        extracted_fields = {
            'total_amount': 1500.0
        }
        
        result = validate_hospital_bill_fields(extracted_fields)
        
        assert result['valid'] is False
        assert result['severity'] == 'FAIL'
        assert 'bill_no' in result['missing_fields']
    
    def test_validate_lab_report_pass(self):
        """Test lab report validation with tests."""
        extracted_fields = {
            'tests': [
                {'name': 'CBC', 'result': 'Normal'}
            ],
            'lab_name': 'PathLab',
            'patient_name': 'John Doe',
            'report_date': '2024-01-15'
        }
        
        result = validate_lab_report_fields(extracted_fields)
        
        assert result['valid'] is True
        assert result['severity'] == 'PASS'
    
    def test_validate_lab_report_no_tests(self):
        """Test lab report validation without tests."""
        extracted_fields = {
            'lab_name': 'PathLab'
        }
        
        result = validate_lab_report_fields(extracted_fields)
        
        assert result['valid'] is False
        assert result['severity'] == 'FAIL'
        assert 'tests' in result['missing_fields']
    
    def test_validate_pharmacy_bill_pass(self):
        """Test pharmacy bill validation with all required fields."""
        extracted_fields = {
            'net_amount': 500.0,
            'medicines': [
                {'name': 'Paracetamol', 'amount': 500.0}
            ],
            'pharmacy_name': 'MedPlus',
            'bill_no': 'PH123',
            'date': '2024-01-15',
            'patient_name': 'John Doe'
        }
        
        result = validate_pharmacy_bill_fields(extracted_fields)
        
        assert result['valid'] is True
        assert result['severity'] == 'PASS'
    
    def test_validate_pharmacy_bill_missing_medicines(self):
        """Test pharmacy bill validation without medicines."""
        extracted_fields = {
            'net_amount': 500.0
        }
        
        result = validate_pharmacy_bill_fields(extracted_fields)
        
        assert result['valid'] is False
        assert result['severity'] == 'FAIL'
        assert 'medicines' in result['missing_fields']


@pytest.mark.unit
@pytest.mark.agents
class TestConfidenceAdjustment:
    """Tests for confidence adjustment based on validation."""
    
    def test_adjust_confidence_pass(self):
        """Test confidence adjustment for passed validation."""
        current = Decimal('0.95')
        validation_result = {'severity': 'PASS'}
        
        adjusted = adjust_confidence_for_validation(current, validation_result)
        
        assert adjusted == Decimal('0.95')
    
    def test_adjust_confidence_warn(self):
        """Test confidence adjustment for warning."""
        current = Decimal('0.95')
        validation_result = {'severity': 'WARN'}
        
        adjusted = adjust_confidence_for_validation(current, validation_result)
        
        assert adjusted == Decimal('0.95') * Decimal('0.9')
    
    def test_adjust_confidence_fail(self):
        """Test confidence adjustment for failure."""
        current = Decimal('0.95')
        validation_result = {'severity': 'FAIL'}
        
        adjusted = adjust_confidence_for_validation(current, validation_result)
        
        assert adjusted == Decimal('0.95') * Decimal('0.7')
    
    def test_adjust_confidence_none(self):
        """Test confidence adjustment with None input."""
        validation_result = {'severity': 'WARN'}
        
        adjusted = adjust_confidence_for_validation(None, validation_result)
        
        assert adjusted == Decimal('0.5') * Decimal('0.9')


@pytest.mark.integration
@pytest.mark.agents
@pytest.mark.skip(reason="Requires complex database transaction handling")
class TestValidateTagsForClaim:
    """Tests for validate_tags_for_claim function."""
    
    def test_validate_tags_claim_not_found(self, session):
        """Test validation with non-existent claim."""
        result = validate_tags_for_claim('non-existent-id')
        
        assert result['overall_status'] == 'FAIL'
        assert 'error' in result
    
    def test_validate_tags_success(self, session, sample_claim_with_documents):
        """Test successful tag validation."""
        result = validate_tags_for_claim(sample_claim_with_documents.id)
        
        assert result['claim_id'] == sample_claim_with_documents.id
        assert result['total_documents'] == 1
        assert result['overall_status'] in ['PASS', 'WARN']
    
    def test_validate_tags_with_failures(self, session, sample_claim):
        """Test tag validation with document failures."""
        from app.models.claim_document import ClaimDocument
        
        # Add document with missing fields
        doc = ClaimDocument(
            claim_id=sample_claim.id,
            file_path='/test/path.pdf',
            doc_tag='PRESCRIPTION',
            extracted_fields={
                'patient_name': 'John Doe'
                # Missing doctor_name and diagnosis
            }
        )
        session.add(doc)
        session.commit()
        
        result = validate_tags_for_claim(sample_claim.id)
        
        assert result['overall_status'] == 'FAIL'
        assert result['failed'] > 0
