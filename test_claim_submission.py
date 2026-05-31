"""
Test script for complete claim submission workflow.

This script demonstrates the end-to-end claim processing pipeline:
1. Submit claim with documents
2. Automatic OCR processing
3. Tag validation
4. Claim facts aggregation
5. Policy evaluation
6. Final decision
"""

import requests
import json
import time

# Configuration
BASE_URL = "http://localhost:5000"
CLAIMS_ENDPOINT = f"{BASE_URL}/claims"

def submit_claim_with_documents(
    member_id,
    claim_type,
    treatment_date,
    submission_date,
    claimed_amount,
    hospital_name,
    documents_data,
    patient_name=None,
    relationship=None
):
    """
    Submit a claim with documents.
    
    Args:
        member_id: Member ID
        claim_type: Type of claim (CONSULTATION, DIAGNOSTIC, etc.)
        treatment_date: Treatment date (YYYY-MM-DD)
        submission_date: Submission date (YYYY-MM-DD)
        claimed_amount: Claimed amount
        hospital_name: Hospital name
        documents_data: List of tuples (file_path, doc_tag)
        patient_name: Optional patient name
        relationship: Optional relationship
    
    Returns:
        Response JSON
    """
    # Prepare form data
    data = {
        "member_id": member_id,
        "claim_type": claim_type,
        "treatment_date": treatment_date,
        "submission_date": submission_date,
        "claimed_amount": str(claimed_amount),
        "hospital_name": hospital_name
    }
    
    if patient_name:
        data["patient_name"] = patient_name
    
    if relationship:
        data["relationship"] = relationship
    
    # Prepare files
    files = []
    for file_path, doc_tag in documents_data:
        files.append(("documents", (file_path.split("/")[-1], open(file_path, "rb"), "application/pdf")))
        data["document_tags"] = data.get("document_tags", []) + [doc_tag]
    
    # Submit request
    response = requests.post(CLAIMS_ENDPOINT, data=data, files=files)
    
    # Close files
    for _, file_tuple in files:
        file_tuple[1].close()
    
    return response


def test_successful_claim():
    """Test a successful claim submission with complete documents."""
    print("=" * 80)
    print("TEST 1: Successful Claim Submission")
    print("=" * 80)
    
    response = submit_claim_with_documents(
        member_id="EMP001",
        claim_type="CONSULTATION",
        treatment_date="2024-05-15",
        submission_date="2024-05-20",
        claimed_amount=1500,
        hospital_name="Apollo Hospitals",
        patient_name="Rajesh Kumar",
        relationship="SELF",
        documents_data=[
            ("uploads/sample_prescription.pdf", "PRESCRIPTION"),
            ("uploads/sample_hospital_bill.pdf", "HOSPITAL_BILL")
        ]
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    if response.status_code == 201:
        result = response.json()
        print(f"✓ Claim ID: {result['claim_id']}")
        print(f"✓ Status: {result['status']}")
        print(f"✓ Decision: {result['decision']}")
        print(f"✓ Approved Amount: ₹{result['approved_amount']}")
        print(f"✓ Confidence: {result['confidence']:.2%}")
    else:
        print("✗ Claim submission failed")
    
    print()


def test_incomplete_documents():
    """Test claim submission with missing required documents."""
    print("=" * 80)
    print("TEST 2: Incomplete Documents (Missing PRESCRIPTION)")
    print("=" * 80)
    
    response = submit_claim_with_documents(
        member_id="EMP002",
        claim_type="CONSULTATION",
        treatment_date="2024-05-16",
        submission_date="2024-05-21",
        claimed_amount=1200,
        hospital_name="Fortis Healthcare",
        patient_name="Priya Singh",
        relationship="SELF",
        documents_data=[
            ("uploads/sample_hospital_bill.pdf", "HOSPITAL_BILL")
        ]
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    if response.status_code == 400:
        result = response.json()
        print(f"✓ Expected failure: {result['status']}")
        print(f"✓ Missing documents: {result.get('missing', [])}")
    else:
        print("✗ Expected 400 status code")
    
    print()


def test_diagnostic_claim():
    """Test a diagnostic claim with lab report."""
    print("=" * 80)
    print("TEST 3: Diagnostic Claim with Lab Report")
    print("=" * 80)
    
    response = submit_claim_with_documents(
        member_id="EMP003",
        claim_type="DIAGNOSTIC",
        treatment_date="2024-05-17",
        submission_date="2024-05-22",
        claimed_amount=2500,
        hospital_name="Max Healthcare",
        patient_name="Amit Verma",
        relationship="SELF",
        documents_data=[
            ("uploads/sample_prescription.pdf", "PRESCRIPTION"),
            ("uploads/sample_lab_report.pdf", "LAB_REPORT"),
            ("uploads/sample_hospital_bill.pdf", "HOSPITAL_BILL")
        ]
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    if response.status_code == 201:
        result = response.json()
        print(f"✓ Claim ID: {result['claim_id']}")
        print(f"✓ Decision: {result['decision']}")
        print(f"✓ Approved Amount: ₹{result['approved_amount']}")
        print(f"✓ Confidence: {result['confidence']:.2%}")
    else:
        print("✗ Claim submission failed")
    
    print()


def test_pharmacy_claim():
    """Test a pharmacy claim."""
    print("=" * 80)
    print("TEST 4: Pharmacy Claim")
    print("=" * 80)
    
    response = submit_claim_with_documents(
        member_id="EMP004",
        claim_type="PHARMACY",
        treatment_date="2024-05-18",
        submission_date="2024-05-23",
        claimed_amount=800,
        hospital_name="MedPlus Pharmacy",
        patient_name="Sneha Reddy",
        relationship="SELF",
        documents_data=[
            ("uploads/sample_prescription.pdf", "PRESCRIPTION"),
            ("uploads/sample_pharmacy_bill.pdf", "PHARMACY_BILL")
        ]
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    if response.status_code == 201:
        result = response.json()
        print(f"✓ Claim ID: {result['claim_id']}")
        print(f"✓ Decision: {result['decision']}")
        print(f"✓ Approved Amount: ₹{result['approved_amount']}")
        print(f"✓ Confidence: {result['confidence']:.2%}")
    else:
        print("✗ Claim submission failed")
    
    print()


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "CLAIM SUBMISSION WORKFLOW TESTS" + " " * 26 + "║")
    print("╚" + "=" * 78 + "╝")
    print("\n")
    
    try:
        # Test 1: Successful claim
        test_successful_claim()
        time.sleep(1)
        
        # Test 2: Incomplete documents
        test_incomplete_documents()
        time.sleep(1)
        
        # Test 3: Diagnostic claim
        test_diagnostic_claim()
        time.sleep(1)
        
        # Test 4: Pharmacy claim
        test_pharmacy_claim()
        
    except FileNotFoundError as e:
        print(f"\n✗ Error: Sample document files not found")
        print(f"  Please ensure sample PDFs exist in the uploads/ directory")
        print(f"  {str(e)}")
    except requests.exceptions.ConnectionError:
        print(f"\n✗ Error: Could not connect to {BASE_URL}")
        print(f"  Please ensure the Flask server is running")
    except Exception as e:
        print(f"\n✗ Unexpected error: {str(e)}")
    
    print("\n" + "=" * 80)
    print("Tests completed")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
