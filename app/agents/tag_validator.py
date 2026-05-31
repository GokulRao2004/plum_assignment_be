"""
Tag Content Validation Agent

This module validates that extracted fields from OCR documents match
the expected schema for their document tags.
"""

from decimal import Decimal
from typing import Dict, List, Any, Optional

from app.database import db
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.models.claim_trace import ClaimTrace


# ============================================================================
# Validation Rules by Document Tag
# ============================================================================

def validate_prescription_fields(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate PRESCRIPTION document fields.
    
    Required: doctor_name, patient_name, and (diagnosis OR medicines list)
    
    Args:
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result:
        {
            "valid": bool,
            "severity": "PASS" | "WARN" | "FAIL",
            "missing_fields": list,
            "message": str
        }
    """
    if not extracted_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": ["all_fields"],
            "message": "No extracted fields found"
        }
    
    missing_fields = []
    warnings = []
    
    # Check required fields
    if not extracted_fields.get("doctor_name"):
        missing_fields.append("doctor_name")
    
    if not extracted_fields.get("patient_name"):
        missing_fields.append("patient_name")
    
    # Check for diagnosis OR medicines
    has_diagnosis = bool(extracted_fields.get("diagnosis"))
    has_medicines = bool(extracted_fields.get("medicines")) and len(extracted_fields.get("medicines", [])) > 0
    
    if not has_diagnosis and not has_medicines:
        missing_fields.append("diagnosis_or_medicines")
    
    # Optional fields that should ideally be present
    if not extracted_fields.get("date"):
        warnings.append("date")
    
    if not extracted_fields.get("doctor_reg_no"):
        warnings.append("doctor_reg_no")
    
    # Determine severity
    if missing_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": missing_fields,
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }
    elif warnings:
        return {
            "valid": True,
            "severity": "WARN",
            "missing_fields": warnings,
            "message": f"Missing optional fields: {', '.join(warnings)}"
        }
    else:
        return {
            "valid": True,
            "severity": "PASS",
            "missing_fields": [],
            "message": "All required fields present"
        }


def validate_hospital_bill_fields(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate HOSPITAL_BILL document fields.
    
    Required: bill_no, total_amount
    
    Args:
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result
    """
    if not extracted_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": ["all_fields"],
            "message": "No extracted fields found"
        }
    
    missing_fields = []
    warnings = []
    
    # Check required fields
    if not extracted_fields.get("bill_no"):
        missing_fields.append("bill_no")
    
    if not extracted_fields.get("total_amount"):
        missing_fields.append("total_amount")
    
    # Optional but important fields
    if not extracted_fields.get("hospital_name"):
        warnings.append("hospital_name")
    
    if not extracted_fields.get("patient_name"):
        warnings.append("patient_name")
    
    if not extracted_fields.get("bill_date"):
        warnings.append("bill_date")
    
    if not extracted_fields.get("line_items") or len(extracted_fields.get("line_items", [])) == 0:
        warnings.append("line_items")
    
    # Determine severity
    if missing_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": missing_fields,
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }
    elif warnings:
        return {
            "valid": True,
            "severity": "WARN",
            "missing_fields": warnings,
            "message": f"Missing optional fields: {', '.join(warnings)}"
        }
    else:
        return {
            "valid": True,
            "severity": "PASS",
            "missing_fields": [],
            "message": "All required fields present"
        }


def validate_lab_report_fields(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate LAB_REPORT document fields.
    
    Required: At least one test entry
    
    Args:
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result
    """
    if not extracted_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": ["all_fields"],
            "message": "No extracted fields found"
        }
    
    missing_fields = []
    warnings = []
    
    # Check required fields
    tests = extracted_fields.get("tests", [])
    if not tests or len(tests) == 0:
        missing_fields.append("tests")
    
    # Optional but important fields
    if not extracted_fields.get("lab_name"):
        warnings.append("lab_name")
    
    if not extracted_fields.get("patient_name"):
        warnings.append("patient_name")
    
    if not extracted_fields.get("report_date") and not extracted_fields.get("sample_date"):
        warnings.append("report_date_or_sample_date")
    
    # Determine severity
    if missing_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": missing_fields,
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }
    elif warnings:
        return {
            "valid": True,
            "severity": "WARN",
            "missing_fields": warnings,
            "message": f"Missing optional fields: {', '.join(warnings)}"
        }
    else:
        return {
            "valid": True,
            "severity": "PASS",
            "missing_fields": [],
            "message": "All required fields present"
        }


def validate_pharmacy_bill_fields(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate PHARMACY_BILL document fields.
    
    Required: net_amount, at least one medicine
    
    Args:
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result
    """
    if not extracted_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": ["all_fields"],
            "message": "No extracted fields found"
        }
    
    missing_fields = []
    warnings = []
    
    # Check required fields
    if not extracted_fields.get("net_amount"):
        missing_fields.append("net_amount")
    
    medicines = extracted_fields.get("medicines", [])
    if not medicines or len(medicines) == 0:
        missing_fields.append("medicines")
    
    # Optional but important fields
    if not extracted_fields.get("pharmacy_name"):
        warnings.append("pharmacy_name")
    
    if not extracted_fields.get("bill_no"):
        warnings.append("bill_no")
    
    if not extracted_fields.get("date"):
        warnings.append("date")
    
    if not extracted_fields.get("patient_name"):
        warnings.append("patient_name")
    
    # Determine severity
    if missing_fields:
        return {
            "valid": False,
            "severity": "FAIL",
            "missing_fields": missing_fields,
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }
    elif warnings:
        return {
            "valid": True,
            "severity": "WARN",
            "missing_fields": warnings,
            "message": f"Missing optional fields: {', '.join(warnings)}"
        }
    else:
        return {
            "valid": True,
            "severity": "PASS",
            "missing_fields": [],
            "message": "All required fields present"
        }


def validate_generic_document_fields(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate generic document fields (for unknown document types).
    
    Args:
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result
    """
    if not extracted_fields:
        return {
            "valid": False,
            "severity": "WARN",
            "missing_fields": ["all_fields"],
            "message": "No extracted fields found for generic document"
        }
    
    # Generic documents always pass with warning
    return {
        "valid": True,
        "severity": "WARN",
        "missing_fields": [],
        "message": "Generic document - no specific validation rules"
    }


# ============================================================================
# Main Validation Function
# ============================================================================

def validate_document_fields(doc_tag: str, extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate extracted fields based on document tag.
    
    Args:
        doc_tag: Document tag (e.g., PRESCRIPTION, HOSPITAL_BILL)
        extracted_fields: Dictionary of extracted fields
    
    Returns:
        Dictionary with validation result
    """
    doc_tag_upper = doc_tag.upper()
    
    if doc_tag_upper == "PRESCRIPTION":
        return validate_prescription_fields(extracted_fields)
    elif doc_tag_upper == "HOSPITAL_BILL":
        return validate_hospital_bill_fields(extracted_fields)
    elif doc_tag_upper == "LAB_REPORT":
        return validate_lab_report_fields(extracted_fields)
    elif doc_tag_upper == "PHARMACY_BILL":
        return validate_pharmacy_bill_fields(extracted_fields)
    else:
        # Unknown document type - use generic validation
        return validate_generic_document_fields(extracted_fields)


def adjust_confidence_for_validation(
    current_confidence: Optional[Decimal],
    validation_result: Dict[str, Any]
) -> Decimal:
    """
    Adjust document confidence based on validation result.
    
    Args:
        current_confidence: Current confidence score (0.000 - 1.000)
        validation_result: Validation result dictionary
    
    Returns:
        Adjusted confidence score
    """
    if current_confidence is None:
        current_confidence = Decimal("0.5")
    
    severity = validation_result.get("severity", "PASS")
    
    if severity == "FAIL":
        # Reduce confidence by 30% for failed validation
        return current_confidence * Decimal("0.7")
    elif severity == "WARN":
        # Reduce confidence by 10% for warnings
        return current_confidence * Decimal("0.9")
    else:
        # No change for passed validation
        return current_confidence


# ============================================================================
# Main Agent Function
# ============================================================================

def validate_tags_for_claim(claim_id: str) -> Dict[str, Any]:
    """
    Validate document tags and extracted fields for all documents in a claim.
    
    This function:
    1. Loads the claim and its documents from the database
    2. For each document:
       - Validates extracted fields match expected schema for doc_tag
       - Creates ClaimTrace for failures/warnings
       - Adjusts doc_confidence if validation fails
    3. Creates summary ClaimTrace if all documents pass
    4. Returns validation summary
    
    Args:
        claim_id: UUID of the claim to validate
    
    Returns:
        Dictionary with validation summary:
        {
            "claim_id": str,
            "total_documents": int,
            "passed": int,
            "warnings": int,
            "failed": int,
            "overall_status": "PASS" | "WARN" | "FAIL",
            "documents": list of document validation results
        }
    """
    # Initialize result
    result = {
        "claim_id": claim_id,
        "total_documents": 0,
        "passed": 0,
        "warnings": 0,
        "failed": 0,
        "overall_status": "PASS",
        "documents": []
    }
    
    try:
        # Load claim from database
        claim = db.session.query(Claim).filter_by(id=claim_id).first()
        
        if not claim:
            result["overall_status"] = "FAIL"
            result["error"] = f"Claim not found: {claim_id}"
            return result
        
        # Load claim documents
        documents = db.session.query(ClaimDocument).filter_by(claim_id=claim_id).all()
        
        if not documents:
            result["overall_status"] = "FAIL"
            result["error"] = f"No documents found for claim: {claim_id}"
            return result
        
        result["total_documents"] = len(documents)
        
        # Validate each document
        for doc in documents:
            doc_result = {
                "document_id": doc.id,
                "doc_tag": doc.doc_tag,
                "original_confidence": float(doc.doc_confidence) if doc.doc_confidence else None,
                "validation_status": None,
                "missing_fields": [],
                "message": None
            }
            
            try:
                # Validate extracted fields
                validation_result = validate_document_fields(
                    doc_tag=doc.doc_tag,
                    extracted_fields=doc.extracted_fields
                )
                
                doc_result["validation_status"] = validation_result["severity"]
                doc_result["missing_fields"] = validation_result["missing_fields"]
                doc_result["message"] = validation_result["message"]
                
                # Update counters
                if validation_result["severity"] == "PASS":
                    result["passed"] += 1
                elif validation_result["severity"] == "WARN":
                    result["warnings"] += 1
                elif validation_result["severity"] == "FAIL":
                    result["failed"] += 1
                
                # Create ClaimTrace for failures and warnings
                if validation_result["severity"] in ["FAIL", "WARN"]:
                    trace = ClaimTrace(
                        claim_id=claim_id,
                        step="TAG_VALIDATION",
                        status=validation_result["severity"],
                        details={
                            "document_id": doc.id,
                            "doc_tag": doc.doc_tag,
                            "missing_fields": validation_result["missing_fields"],
                            "message": validation_result["message"],
                            "original_confidence": float(doc.doc_confidence) if doc.doc_confidence else None
                        }
                    )
                    db.session.add(trace)
                    
                    # Adjust confidence for failed/warned documents
                    new_confidence = adjust_confidence_for_validation(
                        current_confidence=doc.doc_confidence,
                        validation_result=validation_result
                    )
                    doc.doc_confidence = new_confidence
                    doc_result["adjusted_confidence"] = float(new_confidence)
                else:
                    doc_result["adjusted_confidence"] = doc_result["original_confidence"]
                
            except Exception as e:
                # Handle validation errors for individual documents
                doc_result["validation_status"] = "FAIL"
                doc_result["message"] = f"Validation error: {str(e)}"
                result["failed"] += 1
                
                # Create error trace
                trace = ClaimTrace(
                    claim_id=claim_id,
                    step="TAG_VALIDATION",
                    status="FAIL",
                    details={
                        "document_id": doc.id,
                        "doc_tag": doc.doc_tag,
                        "error": str(e)
                    }
                )
                db.session.add(trace)
            
            result["documents"].append(doc_result)
        
        # Determine overall status
        if result["failed"] > 0:
            result["overall_status"] = "FAIL"
        elif result["warnings"] > 0:
            result["overall_status"] = "WARN"
        else:
            result["overall_status"] = "PASS"
            
            # Create summary trace for all-pass scenario
            trace = ClaimTrace(
                claim_id=claim_id,
                step="TAG_VALIDATION",
                status="PASS",
                details={
                    "total_documents": result["total_documents"],
                    "all_documents_valid": True,
                    "message": "All documents passed tag validation"
                }
            )
            db.session.add(trace)
        
        # Commit all changes
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        result["overall_status"] = "FAIL"
        result["error"] = f"Fatal error during validation: {str(e)}"
    
    return result


# ============================================================================
# Utility Functions
# ============================================================================

def get_validation_status_for_claim(claim_id: str) -> Dict[str, Any]:
    """
    Get tag validation status for a claim from ClaimTrace records.
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Dictionary with validation status information
    """
    traces = db.session.query(ClaimTrace).filter_by(
        claim_id=claim_id,
        step="TAG_VALIDATION"
    ).order_by(ClaimTrace.created_at.desc()).all()
    
    if not traces:
        return {
            "claim_id": claim_id,
            "validation_run": False,
            "message": "Tag validation has not been run for this claim"
        }
    
    # Get latest validation results
    validation_traces = []
    for trace in traces:
        validation_traces.append({
            "status": trace.status,
            "details": trace.details,
            "created_at": trace.created_at.isoformat()
        })
    
    # Determine overall status from traces
    statuses = [t.status for t in traces]
    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARN" in statuses:
        overall_status = "WARN"
    else:
        overall_status = "PASS"
    
    return {
        "claim_id": claim_id,
        "validation_run": True,
        "overall_status": overall_status,
        "total_traces": len(traces),
        "traces": validation_traces
    }


def revalidate_document(document_id: str) -> Dict[str, Any]:
    """
    Revalidate a single document.
    
    Args:
        document_id: UUID of the document
    
    Returns:
        Dictionary with validation result
    """
    doc = db.session.query(ClaimDocument).filter_by(id=document_id).first()
    
    if not doc:
        return {
            "error": f"Document not found: {document_id}",
            "valid": False
        }
    
    validation_result = validate_document_fields(
        doc_tag=doc.doc_tag,
        extracted_fields=doc.extracted_fields
    )
    
    # Adjust confidence
    new_confidence = adjust_confidence_for_validation(
        current_confidence=doc.doc_confidence,
        validation_result=validation_result
    )
    
    doc.doc_confidence = new_confidence
    
    # Create trace
    trace = ClaimTrace(
        claim_id=doc.claim_id,
        step="TAG_VALIDATION_RERUN",
        status=validation_result["severity"],
        details={
            "document_id": doc.id,
            "doc_tag": doc.doc_tag,
            "missing_fields": validation_result["missing_fields"],
            "message": validation_result["message"],
            "original_confidence": float(doc.doc_confidence) if doc.doc_confidence else None,
            "adjusted_confidence": float(new_confidence)
        }
    )
    db.session.add(trace)
    db.session.commit()
    
    return {
        "document_id": document_id,
        "doc_tag": doc.doc_tag,
        "validation_status": validation_result["severity"],
        "missing_fields": validation_result["missing_fields"],
        "message": validation_result["message"],
        "adjusted_confidence": float(new_confidence)
    }
