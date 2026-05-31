"""Pytest configuration and fixtures for the test suite."""
import os
import pytest
from datetime import datetime, date
from decimal import Decimal
from flask import Flask
from app import create_app
from app.database import db as _db
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.models.claim_trace import ClaimTrace


@pytest.fixture(scope='session')
def app():
    """Create application for the tests."""
    # Set testing environment
    os.environ['FLASK_ENV'] = 'testing'
    
    # Create app with testing config
    _app = create_app('testing')
    
    # Establish application context
    ctx = _app.app_context()
    ctx.push()
    
    yield _app
    
    ctx.pop()


@pytest.fixture(scope='session')
def db(app):
    """Create database for the tests."""
    # Create all tables
    _db.create_all()
    
    yield _db
    
    # Drop all tables after tests
    _db.drop_all()


@pytest.fixture(scope='function')
def session(db):
    """Create a new database session for a test."""
    connection = db.engine.connect()
    transaction = connection.begin()
    
    # Bind session to connection
    from sqlalchemy.orm import scoped_session, sessionmaker
    session_factory = sessionmaker(bind=connection)
    session = scoped_session(session_factory)
    
    # Replace the db.session with our test session
    db.session = session
    
    yield session
    
    # Rollback transaction and close connection
    session.remove()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope='function')
def client(app, session):
    """Create a test client for the app."""
    return app.test_client()


@pytest.fixture
def sample_claim_data():
    """Sample claim data for testing."""
    return {
        'member_id': 'M001',
        'patient_name': 'John Doe',
        'relationship': 'SELF',
        'claim_type': 'CONSULTATION',
        'treatment_date': '2024-01-15',
        'submission_date': '2024-01-20',
        'claimed_amount': '1500.00',
        'hospital_name': 'Apollo Hospital',
        'pre_auth_present': 'false'
    }


@pytest.fixture
def sample_claim(session):
    """Create a sample claim in the database."""
    claim = Claim(
        member_id='M001',
        patient_name='John Doe',
        relationship='SELF',
        claim_type='CONSULTATION',
        treatment_date=date(2024, 1, 15),
        submission_date=date(2024, 1, 20),
        claimed_amount=Decimal('1500.00'),
        hospital_name='Apollo Hospital',
        is_network_hospital=True,
        pre_auth_present=False,
        status='PENDING'
    )
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return claim


@pytest.fixture
def sample_claim_with_documents(session, sample_claim, tmp_path):
    """Create a sample claim with documents."""
    # Create test document file
    doc_file = tmp_path / "prescription.pdf"
    doc_file.write_text("Test prescription content")
    
    document = ClaimDocument(
        claim_id=sample_claim.id,
        file_path=str(doc_file),
        original_filename='prescription.pdf',
        mime_type='application/pdf',
        doc_tag='PRESCRIPTION',
        ocr_text='Test OCR text',
        extracted_fields={
            'doctor_name': 'Dr. Smith',
            'patient_name': 'John Doe',
            'diagnosis': 'Common Cold',
            'medicines': [
                {'name': 'Paracetamol', 'dosage': '500mg'}
            ]
        },
        doc_confidence=Decimal('0.95')
    )
    session.add(document)
    session.commit()
    session.refresh(sample_claim)
    return sample_claim


@pytest.fixture
def sample_claim_trace(session, sample_claim):
    """Create a sample claim trace."""
    trace = ClaimTrace(
        claim_id=sample_claim.id,
        step='DOC_PRESENCE_CHECK',
        status='PASS',
        details={
            'claim_type': 'CONSULTATION',
            'required': ['PRESCRIPTION'],
            'uploaded': ['PRESCRIPTION']
        }
    )
    session.add(trace)
    session.commit()
    return trace


@pytest.fixture
def mock_policy_terms():
    """Mock policy terms for testing."""
    return {
        "policy_holder": {
            "policy_number": "POL123456",
            "policy_start_date": "2024-01-01",
            "policy_end_date": "2024-12-31",
            "renewal_status": "ACTIVE"
        },
        "members": [
            {
                "member_id": "M001",
                "name": "John Doe",
                "relationship": "SELF",
                "join_date": "2024-01-01"
            }
        ],
        "coverage": {
            "annual_opd_limit": 50000.0,
            "per_claim_limit": 10000.0,
            "family_floater": {
                "enabled": False
            }
        },
        "opd_categories": {
            "consultation": {
                "covered": True,
                "sub_limit": 5000.0,
                "copay_percent": 10.0,
                "requires_prescription": True
            },
            "diagnostic": {
                "covered": True,
                "sub_limit": 10000.0,
                "copay_percent": 20.0,
                "pre_auth_threshold": 5000.0
            },
            "pharmacy": {
                "covered": True,
                "sub_limit": 5000.0,
                "copay_percent": 10.0,
                "branded_drug_copay_percent": 30.0,
                "generic_mandatory": True
            }
        },
        "submission_rules": {
            "minimum_claim_amount": 100.0,
            "deadline_days_from_treatment": 30
        },
        "waiting_periods": {
            "initial_waiting_period_days": 30,
            "pre_existing_conditions_days": 365
        },
        "exclusions": {
            "conditions": ["cosmetic surgery", "experimental treatment"],
            "dental_exclusions": ["cosmetic dentistry"],
            "vision_exclusions": ["contact lenses"]
        },
        "network_hospitals": [
            "Apollo Hospital",
            "Fortis Hospital",
            "Max Hospital"
        ],
        "fraud_thresholds": {
            "high_value_claim_threshold": 10000.0,
            "same_day_claims_max": 2,
            "monthly_claims_max": 5
        },
        "document_requirements": {
            "CONSULTATION": {
                "required": ["PRESCRIPTION"],
                "optional": ["HOSPITAL_BILL"]
            },
            "DIAGNOSTIC": {
                "required": ["PRESCRIPTION", "LAB_REPORT"],
                "optional": ["HOSPITAL_BILL"]
            },
            "PHARMACY": {
                "required": ["PRESCRIPTION", "PHARMACY_BILL"],
                "optional": []
            }
        }
    }


@pytest.fixture
def mock_ocr_result():
    """Mock OCR processing result."""
    return {
        'claim_id': 'test-claim-id',
        'documents_processed': 1,
        'documents_skipped': 0,
        'errors': [],
        'documents_summary': [
            {
                'document_id': 'test-doc-id',
                'doc_tag': 'PRESCRIPTION',
                'inferred_doc_type': 'PRESCRIPTION',
                'status': 'SUCCESS',
                'confidence': 0.95,
                'page_count': 1,
                'quality_flags': [],
                'fraud_summary': {},
                'manual_review': False,
                'manual_review_reasons': []
            }
        ]
    }


@pytest.fixture
def mock_claim_facts():
    """Mock claim facts for policy engine testing."""
    return {
        "claim_id": "test-claim-id",
        "member_id": "M001",
        "claim_type": "CONSULTATION",
        "treatment_date": "2024-01-15",
        "submission_date": "2024-01-20",
        "claimed_amount": 1500.0,
        "hospital_name": "Apollo Hospital",
        "is_network_hospital": True,
        "diagnosis": "Common Cold",
        "per_category_amounts": {
            "consultation": 1500.0
        },
        "is_pre_existing_condition": False,
        "is_maternity": False,
        "is_dental_procedure": False,
        "is_vision_item": False,
        "same_day_claims_count": 1,
        "monthly_claims_count": 1,
        "high_value_flag": False,
        "pre_auth_present": False,
        "procedures": [],
        "medicines": [
            {"name": "Paracetamol", "is_branded": False}
        ],
        "tests": [],
        "fraud_summary": {
            "duplicate_stamp_terms": [],
            "alteration_flags": [],
            "partial_flags": [],
            "duplicate_pages_detected": False
        },
        "session_count_ytd": 0
    }
