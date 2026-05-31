"""
ClaimFacts Aggregator & Fraud Metrics Agent

This module aggregates claim data from multiple sources and computes
fraud detection metrics to build a comprehensive claim_facts dictionary
for policy evaluation.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Any, Optional

from sqlalchemy import func, extract

from app.database import db
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.models.claim_trace import ClaimTrace
from app.utils.policy_loader import load_policy_terms


# ============================================================================
# Helper Functions
# ============================================================================

def extract_diagnosis_from_documents(documents: List[ClaimDocument]) -> str:
    """
    Extract diagnosis from prescription documents.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        Diagnosis string or "Unknown"
    """
    # Priority: PRESCRIPTION documents
    for doc in documents:
        if doc.doc_tag.upper() == "PRESCRIPTION" and doc.extracted_fields:
            diagnosis = doc.extracted_fields.get("diagnosis")
            if diagnosis and diagnosis.strip():
                return diagnosis.strip()
    
    # Fallback: Check other documents
    for doc in documents:
        if doc.extracted_fields:
            diagnosis = doc.extracted_fields.get("diagnosis")
            if diagnosis and diagnosis.strip():
                return diagnosis.strip()
    
    return "Unknown"


def is_network_hospital(hospital_name: str, policy_terms: Dict[str, Any]) -> bool:
    """
    Check if hospital is in the network.
    
    Args:
        hospital_name: Name of the hospital
        policy_terms: Policy terms dictionary
    
    Returns:
        True if hospital is in network, False otherwise
    """
    if not hospital_name:
        return False
    
    network_hospitals = policy_terms.get("network_hospitals", [])
    hospital_name_lower = hospital_name.lower().strip()
    
    for network_hospital in network_hospitals:
        if network_hospital.lower().strip() in hospital_name_lower:
            return True
        if hospital_name_lower in network_hospital.lower().strip():
            return True
    
    return False


def categorize_line_item(description: str, doc_tag: str) -> str:
    """
    Categorize a line item based on description and document tag.
    
    Args:
        description: Line item description
        doc_tag: Document tag (e.g., HOSPITAL_BILL, PHARMACY_BILL)
    
    Returns:
        Category name (consultation, diagnostic, pharmacy, dental, vision, alternative_medicine)
    """
    description_lower = description.lower()
    doc_tag_upper = doc_tag.upper()
    
    # Pharmacy items
    if doc_tag_upper == "PHARMACY_BILL":
        return "pharmacy"
    
    # Dental items
    if doc_tag_upper == "DENTAL_BILL" or "dental" in description_lower:
        return "dental"
    
    # Vision items
    if "glasses" in description_lower or "lens" in description_lower or \
       "eye" in description_lower or "vision" in description_lower or \
       "spectacle" in description_lower:
        return "vision"
    
    # Alternative medicine
    if "ayurved" in description_lower or "homeopath" in description_lower or \
       "unani" in description_lower or "siddha" in description_lower or \
       "naturopath" in description_lower:
        return "alternative_medicine"
    
    # Diagnostic items
    if any(keyword in description_lower for keyword in [
        "test", "lab", "x-ray", "xray", "scan", "mri", "ct", "ultrasound",
        "ecg", "ekg", "blood", "urine", "pathology", "radiology", "diagnostic"
    ]):
        return "diagnostic"
    
    # Consultation items (default for hospital bills)
    if any(keyword in description_lower for keyword in [
        "consultation", "doctor", "physician", "visit", "opd", "checkup"
    ]):
        return "consultation"
    
    # Default based on doc_tag
    if doc_tag_upper == "HOSPITAL_BILL":
        return "consultation"
    elif doc_tag_upper == "LAB_REPORT":
        return "diagnostic"
    
    # Final fallback
    return "consultation"


def aggregate_per_category_amounts(documents: List[ClaimDocument]) -> Dict[str, float]:
    """
    Aggregate amounts by category from document line items.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        Dictionary mapping category to total amount
    """
    category_amounts = {}
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        doc_tag = doc.doc_tag
        
        # Process hospital bills
        if doc_tag.upper() == "HOSPITAL_BILL":
            line_items = doc.extracted_fields.get("line_items", [])
            for item in line_items:
                description = item.get("description", "")
                amount = float(item.get("amount", 0))
                
                category = categorize_line_item(description, doc_tag)
                category_amounts[category] = category_amounts.get(category, 0.0) + amount
        
        # Process pharmacy bills
        elif doc_tag.upper() == "PHARMACY_BILL":
            medicines = doc.extracted_fields.get("medicines", [])
            total = 0.0
            for med in medicines:
                amount = float(med.get("amount", 0))
                total += amount
            
            if total > 0:
                category_amounts["pharmacy"] = category_amounts.get("pharmacy", 0.0) + total
            else:
                # Fallback to net_amount
                net_amount = doc.extracted_fields.get("net_amount")
                if net_amount:
                    category_amounts["pharmacy"] = category_amounts.get("pharmacy", 0.0) + float(net_amount)
        
        # Process lab reports
        elif doc_tag.upper() == "LAB_REPORT":
            # Lab reports typically don't have amounts in extracted_fields
            # We'll rely on the claim's claimed_amount or hospital bill
            pass
        
        # Process dental bills
        elif doc_tag.upper() == "DENTAL_BILL":
            total_amount = doc.extracted_fields.get("total_amount")
            if total_amount:
                category_amounts["dental"] = category_amounts.get("dental", 0.0) + float(total_amount)
    
    return category_amounts


def extract_procedures_from_documents(documents: List[ClaimDocument]) -> List[str]:
    """
    Extract procedures from documents (dental, vision, etc.).
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        List of procedure names
    """
    procedures = []
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        # Check for procedures in extracted fields
        if "procedures" in doc.extracted_fields:
            doc_procedures = doc.extracted_fields["procedures"]
            if isinstance(doc_procedures, list):
                procedures.extend(doc_procedures)
        
        # Check for procedure in diagnosis or treatment
        if "procedure" in doc.extracted_fields:
            procedures.append(doc.extracted_fields["procedure"])
        
        # For dental bills, check treatment field
        if doc.doc_tag.upper() == "DENTAL_BILL":
            if "treatment" in doc.extracted_fields:
                procedures.append(doc.extracted_fields["treatment"])
    
    return procedures


def extract_line_items_from_documents(documents: List[ClaimDocument]) -> List[Dict[str, Any]]:
    """
    Extract line items from hospital bills and dental bills.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        List of line item dictionaries with description and amount
    """
    line_items = []
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        # Check for line_items in extracted fields
        doc_line_items = doc.extracted_fields.get("line_items", [])
        if isinstance(doc_line_items, list) and doc_line_items:
            for item in doc_line_items:
                if isinstance(item, dict):
                    line_items.append({
                        "description": item.get("description", item.get("item", "")),
                        "amount": float(item.get("amount", 0))
                    })
    
    return line_items


def extract_medicines_from_documents(documents: List[ClaimDocument]) -> List[Dict[str, Any]]:
    """
    Extract medicines with branded flag from documents.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        List of medicine dictionaries with is_branded flag
    """
    medicines = []
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        doc_medicines = doc.extracted_fields.get("medicines", [])
        if isinstance(doc_medicines, list):
            for med in doc_medicines:
                if isinstance(med, dict):
                    # Add is_branded flag if not present (default to False)
                    if "is_branded" not in med:
                        med["is_branded"] = False
                    if "has_generic_alternative" not in med:
                        med["has_generic_alternative"] = True
                    medicines.append(med)
                elif isinstance(med, str):
                    # Convert string to dict
                    medicines.append({
                        "name": med,
                        "is_branded": False,
                        "has_generic_alternative": True
                    })
    
    return medicines


def extract_tests_from_documents(documents: List[ClaimDocument]) -> List[str]:
    """
    Extract diagnostic tests from documents.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        List of test names
    """
    tests = []
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        # Check for tests in lab reports
        if doc.doc_tag.upper() == "LAB_REPORT":
            doc_tests = doc.extracted_fields.get("tests", [])
            if isinstance(doc_tests, list):
                for test in doc_tests:
                    if isinstance(test, dict):
                        test_name = test.get("name", test.get("test_name", ""))
                        if test_name:
                            tests.append(test_name)
                    elif isinstance(test, str):
                        tests.append(test)
        
        # Check for test_name field
        if "test_name" in doc.extracted_fields:
            tests.append(doc.extracted_fields["test_name"])
    
    return tests


def extract_fraud_summary_from_documents(documents: List[ClaimDocument]) -> Dict[str, Any]:
    """
    Extract fraud summary from OCR pipeline results.
    
    Args:
        documents: List of ClaimDocument objects
    
    Returns:
        Aggregated fraud summary dictionary
    """
    fraud_summary = {
        "duplicate_stamp_terms": [],
        "alteration_flags": [],
        "partial_flags": [],
        "duplicate_pages_detected": False
    }
    
    for doc in documents:
        if not doc.extracted_fields:
            continue
        
        doc_fraud = doc.extracted_fields.get("fraud_summary", {})
        if doc_fraud:
            # Aggregate duplicate stamps
            if doc_fraud.get("duplicate_stamp_terms"):
                fraud_summary["duplicate_stamp_terms"].extend(doc_fraud["duplicate_stamp_terms"])
            
            # Aggregate alteration flags
            if doc_fraud.get("alteration_flags"):
                fraud_summary["alteration_flags"].extend(doc_fraud["alteration_flags"])
            
            # Aggregate partial flags
            if doc_fraud.get("partial_flags"):
                fraud_summary["partial_flags"].extend(doc_fraud["partial_flags"])
            
            # Set duplicate pages flag if any document has it
            if doc_fraud.get("duplicate_pages_detected"):
                fraud_summary["duplicate_pages_detected"] = True
    
    return fraud_summary


def count_alternative_medicine_sessions_ytd(member_id: str, treatment_date: datetime.date, policy_terms: Dict[str, Any]) -> int:
    """
    Count alternative medicine sessions for member in current policy year.
    
    Args:
        member_id: Member ID
        treatment_date: Treatment date
        policy_terms: Policy terms dictionary
    
    Returns:
        Count of sessions year-to-date
    """
    # Get policy year start
    holder = policy_terms.get("policy_holder", {})
    policy_start = datetime.strptime(holder["policy_start_date"], "%Y-%m-%d").date()
    
    # Calculate current policy year start
    if treatment_date.month >= policy_start.month and treatment_date.day >= policy_start.day:
        year_start = date(treatment_date.year, policy_start.month, policy_start.day)
    else:
        year_start = date(treatment_date.year - 1, policy_start.month, policy_start.day)
    
    # Query count of alternative medicine claims
    count = db.session.query(func.count(Claim.id)).filter(
        Claim.member_id == member_id,
        Claim.claim_type == "ALTERNATIVE_MEDICINE",
        Claim.treatment_date >= year_start,
        Claim.treatment_date < treatment_date,
        Claim.status == "COMPLETED",
        Claim.decision.in_(["APPROVED", "PARTIAL"])
    ).scalar()
    
    return count or 0


def check_pre_existing_condition(diagnosis: str, claim_type: str) -> bool:
    diagnosis_lower = diagnosis.lower()
    
    # Common pre-existing conditions
    pre_existing_keywords = [
        "diabetes", "diabetic", "hypertension", "blood pressure", "thyroid",
        "asthma", "copd", "heart disease", "cardiac", "kidney disease",
        "renal", "liver disease", "hepatic", "cancer", "tumor", "chronic"
    ]
    
    for keyword in pre_existing_keywords:
        if keyword in diagnosis_lower:
            return True
    
    return False


def check_maternity(diagnosis: str, claim_type: str) -> bool:
    """
    Check if claim is maternity-related.
    
    Args:
        diagnosis: Diagnosis string
        claim_type: Claim type
    
    Returns:
        True if maternity-related
    """
    diagnosis_lower = diagnosis.lower()
    
    maternity_keywords = [
        "pregnancy", "pregnant", "maternity", "prenatal", "antenatal",
        "postnatal", "delivery", "childbirth", "obstetric", "gynecolog"
    ]
    
    for keyword in maternity_keywords:
        if keyword in diagnosis_lower:
            return True
    
    return False


def check_dental_procedure(diagnosis: str, claim_type: str) -> bool:
    """
    Check if claim is for dental procedure.
    
    Args:
        diagnosis: Diagnosis string
        claim_type: Claim type
    
    Returns:
        True if dental procedure
    """
    if claim_type.upper() == "DENTAL":
        return True
    
    diagnosis_lower = diagnosis.lower()
    
    dental_keywords = [
        "dental", "tooth", "teeth", "gum", "root canal", "extraction",
        "filling", "crown", "bridge", "denture", "orthodontic"
    ]
    
    for keyword in dental_keywords:
        if keyword in diagnosis_lower:
            return True
    
    return False


def check_vision_item(diagnosis: str, claim_type: str) -> bool:
    """
    Check if claim is for vision item.
    
    Args:
        diagnosis: Diagnosis string
        claim_type: Claim type
    
    Returns:
        True if vision item
    """
    if claim_type.upper() == "VISION":
        return True
    
    diagnosis_lower = diagnosis.lower()
    
    vision_keywords = [
        "vision", "eye", "glasses", "spectacle", "lens", "contact lens",
        "cataract", "glaucoma", "retina", "ophthalm"
    ]
    
    for keyword in vision_keywords:
        if keyword in diagnosis_lower:
            return True
    
    return False


def count_same_day_claims(member_id: str, treatment_date: datetime.date) -> int:
    """
    Count claims for the same member on the same treatment date.
    
    Args:
        member_id: Member ID
        treatment_date: Treatment date
    
    Returns:
        Count of same-day claims
    """
    count = db.session.query(func.count(Claim.id)).filter(
        Claim.member_id == member_id,
        Claim.treatment_date == treatment_date
    ).scalar()
    
    return count or 0


def count_monthly_claims(member_id: str, treatment_date: datetime.date) -> int:
    """
    Count claims for the same member in the same month.
    
    Args:
        member_id: Member ID
        treatment_date: Treatment date
    
    Returns:
        Count of monthly claims
    """
    year = treatment_date.year
    month = treatment_date.month
    
    count = db.session.query(func.count(Claim.id)).filter(
        Claim.member_id == member_id,
        extract('year', Claim.treatment_date) == year,
        extract('month', Claim.treatment_date) == month
    ).scalar()
    
    return count or 0


def check_high_value_flag(claimed_amount: float, policy_terms: Dict[str, Any]) -> bool:
    """
    Check if claim amount exceeds high value threshold.
    
    Args:
        claimed_amount: Claimed amount
        policy_terms: Policy terms dictionary
    
    Returns:
        True if high value claim
    """
    fraud_thresholds = policy_terms.get("fraud_thresholds", {})
    high_value_threshold = float(fraud_thresholds.get("high_value_claim_threshold", 0))
    
    return claimed_amount > high_value_threshold


# ============================================================================
# Main Agent Function
# ============================================================================

def build_claim_facts(claim_id: str) -> Dict[str, Any]:
    """
    Build comprehensive claim_facts dictionary for policy evaluation.
    
    This function:
    1. Loads claim and documents from database
    2. Extracts and aggregates data from multiple sources
    3. Computes fraud detection metrics
    4. Creates ClaimTrace for audit trail
    5. Returns claim_facts dictionary
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Dictionary with claim facts:
        {
            "claim_id": str,
            "policy_id": str,
            "member_id": str,
            "claim_type": str,
            "treatment_date": str (YYYY-MM-DD),
            "submission_date": str (YYYY-MM-DD),
            "claimed_amount": float,
            "hospital_name": str,
            "is_network_hospital": bool,
            "diagnosis": str,
            "per_category_amounts": dict,
            "is_pre_existing_condition": bool,
            "is_maternity": bool,
            "is_dental_procedure": bool,
            "is_vision_item": bool,
            "same_day_claims_count": int,
            "monthly_claims_count": int,
            "high_value_flag": bool,
            "pre_auth_present": bool,
            "procedures": list,
            "medicines": list,
            "tests": list,
            "fraud_summary": dict,
            "session_count_ytd": int
        }
    """
    try:
        # Load claim from database
        claim = db.session.query(Claim).filter_by(id=claim_id).first()
        
        if not claim:
            raise ValueError(f"Claim not found: {claim_id}")
        
        # Load claim documents
        documents = db.session.query(ClaimDocument).filter_by(claim_id=claim_id).all()
        
        # Load policy terms
        policy_terms = load_policy_terms()
        
        # Extract basic claim data
        member_id = claim.member_id
        claim_type = claim.claim_type
        treatment_date = claim.treatment_date
        submission_date = claim.submission_date
        claimed_amount = float(claim.claimed_amount)
        hospital_name = claim.hospital_name or ""
        
        # Derive diagnosis from documents
        diagnosis = extract_diagnosis_from_documents(documents)
        
        # Check if network hospital
        network_hospital = is_network_hospital(hospital_name, policy_terms)
        
        # Aggregate per-category amounts
        per_category_amounts = aggregate_per_category_amounts(documents)
        
        # If no line items found, use claim_type and claimed_amount
        if not per_category_amounts:
            category = claim_type.lower()
            per_category_amounts[category] = claimed_amount
        
        # Compute flags
        pre_existing = check_pre_existing_condition(diagnosis, claim_type)
        maternity = check_maternity(diagnosis, claim_type)
        dental = check_dental_procedure(diagnosis, claim_type)
        vision = check_vision_item(diagnosis, claim_type)
        
        # Compute fraud metrics
        same_day_count = count_same_day_claims(member_id, treatment_date)
        monthly_count = count_monthly_claims(member_id, treatment_date)
        high_value = check_high_value_flag(claimed_amount, policy_terms)
        
        # Extract additional fields for policy evaluation
        procedures = extract_procedures_from_documents(documents)
        medicines = extract_medicines_from_documents(documents)
        tests = extract_tests_from_documents(documents)
        fraud_summary = extract_fraud_summary_from_documents(documents)
        line_items = extract_line_items_from_documents(documents)
        
        # Get pre-auth status from claim
        pre_auth_present = claim.pre_auth_present if hasattr(claim, 'pre_auth_present') else False
        
        # Count sessions for alternative medicine
        session_count_ytd = 0
        if claim_type.upper() == "ALTERNATIVE_MEDICINE":
            session_count_ytd = count_alternative_medicine_sessions_ytd(member_id, treatment_date, policy_terms)
        
        # Build claim_facts dictionary
        claim_facts = {
            "claim_id": claim_id,
            "policy_id": claim.policy_id if hasattr(claim, 'policy_id') else policy_terms.get("policy_id"),
            "member_id": member_id,
            "claim_type": claim_type,
            "treatment_date": treatment_date.isoformat(),
            "submission_date": submission_date.isoformat(),
            "claimed_amount": claimed_amount,
            "hospital_name": hospital_name,
            "is_network_hospital": network_hospital,
            "diagnosis": diagnosis,
            "per_category_amounts": per_category_amounts,
            "is_pre_existing_condition": pre_existing,
            "is_maternity": maternity,
            "is_dental_procedure": dental,
            "is_vision_item": vision,
            "same_day_claims_count": same_day_count,
            "monthly_claims_count": monthly_count,
            "high_value_flag": high_value,
            "pre_auth_present": pre_auth_present,
            "procedures": procedures,
            "medicines": medicines,
            "tests": tests,
            "fraud_summary": fraud_summary,
            "line_items": line_items,
            "session_count_ytd": session_count_ytd
        }
        
        # Create ClaimTrace for audit trail
        trace_details = {
            "member_id": member_id,
            "claim_type": claim_type,
            "diagnosis": diagnosis,
            "is_network_hospital": network_hospital,
            "categories": list(per_category_amounts.keys()),
            "flags": {
                "pre_existing": pre_existing,
                "maternity": maternity,
                "dental": dental,
                "vision": vision,
                "high_value": high_value
            },
            "fraud_metrics": {
                "same_day_claims": same_day_count,
                "monthly_claims": monthly_count,
                "fraud_summary": fraud_summary
            },
            "extracted_data": {
                "procedures_count": len(procedures),
                "medicines_count": len(medicines),
                "tests_count": len(tests),
                "line_items_count": len(line_items),
                "session_count_ytd": session_count_ytd
            }
        }
        
        trace = ClaimTrace(
            claim_id=claim_id,
            step="CLAIM_FACTS_AGGREGATION",
            status="INFO",
            details=trace_details
        )
        db.session.add(trace)
        db.session.commit()
        
        return claim_facts
        
    except Exception as e:
        db.session.rollback()
        
        # Create error trace
        trace = ClaimTrace(
            claim_id=claim_id,
            step="CLAIM_FACTS_AGGREGATION",
            status="FAIL",
            details={
                "error": str(e)
            }
        )
        db.session.add(trace)
        db.session.commit()
        
        raise Exception(f"Failed to build claim facts: {str(e)}")


# ============================================================================
# Utility Functions
# ============================================================================

def get_claim_facts_summary(claim_id: str) -> Dict[str, Any]:
    """
    Get claim facts summary from ClaimTrace.
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Dictionary with claim facts summary or None if not found
    """
    trace = db.session.query(ClaimTrace).filter_by(
        claim_id=claim_id,
        step="CLAIM_FACTS_AGGREGATION"
    ).order_by(ClaimTrace.created_at.desc()).first()
    
    if not trace:
        return {
            "claim_id": claim_id,
            "aggregation_run": False,
            "message": "Claim facts aggregation has not been run"
        }
    
    return {
        "claim_id": claim_id,
        "aggregation_run": True,
        "status": trace.status,
        "details": trace.details,
        "created_at": trace.created_at.isoformat()
    }


def rebuild_claim_facts(claim_id: str) -> Dict[str, Any]:
    """
    Rebuild claim facts (useful after document updates).
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Updated claim_facts dictionary
    """
    return build_claim_facts(claim_id)
