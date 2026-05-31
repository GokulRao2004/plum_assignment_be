"""Celery tasks for claim processing."""
from decimal import Decimal
from app.celery_app import celery
from app.database import db
from app.models.claim import Claim
from app.models.claim_trace import ClaimTrace
from app.agents.ocr_parser import run_ocr_and_parse_for_claim
from app.agents.tag_validator import validate_tags_for_claim
from app.agents.claim_facts import build_claim_facts
from app.policy_engine import evaluate_claim
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


@celery.task(bind=True, name='app.tasks.claim_processing.process_claim_documents')
def process_claim_documents(self, claim_id):
    """
    Background task to process claim documents through the full pipeline.
    
    This task performs:
    1. Document quality and type validation
    2. Patient name consistency check
    3. OCR and document parsing
    4. Document tag validation
    5. Claim facts aggregation
    6. Policy engine evaluation
    
    Args:
        self: Celery task instance (when bind=True)
        claim_id: UUID of the claim to process
    
    Returns:
        dict: Processing result with status, decision, and amounts
    """
    from app import create_app
    
    # Create Flask app context for database access
    app = create_app()
    
    with app.app_context():
        try:
            logger.info(f"Starting background processing for claim {claim_id}")
            
            # Fetch the claim
            claim = Claim.query.filter_by(id=claim_id).first()
            if not claim:
                logger.error(f"Claim {claim_id} not found")
                return {
                    'status': 'ERROR',
                    'message': f'Claim {claim_id} not found'
                }
            
            # Update task progress (only if self is available)
            if self:
                self.update_state(state='PROCESSING', meta={'step': 'OCR', 'progress': 25})
            
            # Initialize confidence score
            confidence = 1.0
            component_failures = []
            
            # Step 1: Run OCR and parse documents
            try:
                logger.info(f"Running OCR for claim {claim_id}")
                ocr_result = run_ocr_and_parse_for_claim(claim_id)
                
                # Reduce confidence if OCR had errors
                if ocr_result.get("errors") and len(ocr_result["errors"]) > 0:
                    confidence -= 0.2
                    logger.warning(f"OCR errors for claim {claim_id}: {ocr_result['errors']}")
                    
            except Exception as ocr_error:
                logger.error(f"OCR processing failed for claim {claim_id}: {str(ocr_error)}")
                # Log OCR error but continue processing
                trace = ClaimTrace(
                    claim_id=claim_id,
                    step="OCR_PROCESSING",
                    status="FAIL",
                    details={"error": str(ocr_error)}
                )
                db.session.add(trace)
                db.session.commit()
                confidence -= 0.3
                component_failures.append("OCR_PROCESSING")
            
            # Step 1.5: Early validation checks (document quality, type, patient name consistency)
            try:
                logger.info(f"Running early validation checks for claim {claim_id}")
                early_validation_result = _run_early_validation_checks(claim_id)
                
                if not early_validation_result["passed"]:
                    # Early validation failed - stop processing but DO NOT reject claim
                    # The claim needs document correction/re-upload
                    claim.status = "PENDING_RESUBMISSION"
                    claim.decision = None  # No decision made yet
                    claim.primary_reason = early_validation_result["message"]
                    claim.confidence = Decimal(str(max(0.0, min(1.0, confidence))))
                    
                    # Create trace
                    trace = ClaimTrace(
                        claim_id=claim_id,
                        step="EARLY_VALIDATION",
                        status="FAIL",
                        details=early_validation_result
                    )
                    db.session.add(trace)
                    db.session.commit()
                    
                    logger.warning(f"Claim {claim_id} failed early validation: {early_validation_result['message']}")
                    
                    return {
                        'status': 'PENDING_RESUBMISSION',
                        'decision': None,
                        'approved_amount': 0.0,
                        'confidence': float(claim.confidence),
                        'message': claim.primary_reason,
                        'validation_issues': early_validation_result.get('issues', [])
                    }
                    
            except Exception as validation_error:
                logger.error(f"Early validation failed for claim {claim_id}: {str(validation_error)}")
                # Log validation error but continue processing
                trace = ClaimTrace(
                    claim_id=claim_id,
                    step="EARLY_VALIDATION",
                    status="FAIL",
                    details={"error": str(validation_error)}
                )
                db.session.add(trace)
                db.session.commit()
                confidence -= 0.2
                component_failures.append("EARLY_VALIDATION")
            
            # Update task progress (only if self is available)
            if self:
                self.update_state(state='PROCESSING', meta={'step': 'VALIDATION', 'progress': 50})
            
            # Step 2: Validate document tags
            try:
                logger.info(f"Validating tags for claim {claim_id}")
                validation_result = validate_tags_for_claim(claim_id)
                
                # Reduce confidence if validation had warnings or failures
                if validation_result.get("warnings", 0) > 0 or validation_result.get("failed", 0) > 0:
                    confidence -= 0.2
                    logger.warning(f"Tag validation issues for claim {claim_id}: {validation_result}")
                    
            except Exception as validation_error:
                logger.error(f"Tag validation failed for claim {claim_id}: {str(validation_error)}")
                # Log validation error but continue processing
                trace = ClaimTrace(
                    claim_id=claim_id,
                    step="TAG_VALIDATION",
                    status="FAIL",
                    details={"error": str(validation_error)}
                )
                db.session.add(trace)
                db.session.commit()
                confidence -= 0.2
                component_failures.append("TAG_VALIDATION")
            
            # Update task progress (only if self is available)
            if self:
                self.update_state(state='PROCESSING', meta={'step': 'FACTS', 'progress': 75})
            
            # Step 3: Build claim facts
            try:
                logger.info(f"Building claim facts for claim {claim_id}")
                claim_facts = build_claim_facts(claim_id)
            except Exception as facts_error:
                logger.error(f"Claim facts aggregation failed for claim {claim_id}: {str(facts_error)}")
                # Claim facts aggregation failed - cannot proceed
                claim.status = "COMPLETED"
                claim.decision = "REJECTED"
                claim.primary_reason = f"Failed to aggregate claim facts: {str(facts_error)}"
                claim.confidence = Decimal(str(max(0.0, min(1.0, confidence))))
                
                db.session.commit()
                
                return {
                    'status': 'COMPLETED',
                    'decision': 'REJECTED',
                    'approved_amount': 0.0,
                    'confidence': float(claim.confidence),
                    'message': claim.primary_reason
                }
            
            # Update task progress (only if self is available)
            if self:
                self.update_state(state='PROCESSING', meta={'step': 'POLICY_EVALUATION', 'progress': 90})
            
            # Step 4: Evaluate claim using policy engine
            try:
                logger.info(f"Evaluating policy for claim {claim_id}")
                eval_result = evaluate_claim(claim_facts)
                
                decision = eval_result.get("decision", "REJECTED")
                approved_amount = float(eval_result.get("approved_amount", 0.0))
                rule_results = eval_result.get("rule_results", [])
                
                # Check if fraud thresholds suggest manual review
                if decision == "MANUAL_REVIEW":
                    confidence -= 0.2
                
                # Clamp confidence between 0 and 1
                confidence = max(0.0, min(1.0, confidence))
                
                # Determine primary reason from rule results
                primary_reason = ""
                
                # Find first failing rule
                for rule in rule_results:
                    if rule.get("status") == "FAIL":
                        primary_reason = rule.get("reason", "")
                        break
                
                # If no failing rule, use last rule's reason
                if not primary_reason and rule_results:
                    primary_reason = rule_results[-1].get("reason", "Claim processed successfully")
                
                if not primary_reason:
                    if decision == "APPROVED":
                        primary_reason = "Claim approved - all policy checks passed"
                    elif decision == "PARTIAL":
                        primary_reason = "Claim partially approved - amount adjusted per policy limits"
                    elif decision == "MANUAL_REVIEW":
                        primary_reason = "Claim requires manual review due to fraud thresholds"
                    else:
                        primary_reason = "Claim rejected"
                
                # Add component failure note if any components failed
                if component_failures:
                    primary_reason += f" (Note: Some components failed during processing: {', '.join(component_failures)}. Manual review recommended.)"
                
                # Create ClaimTrace for policy engine evaluation
                trace = ClaimTrace(
                    claim_id=claim_id,
                    step="POLICY_ENGINE",
                    status="INFO",
                    details={
                        "decision": decision,
                        "approved_amount": approved_amount,
                        "confidence": confidence,
                        "rule_results": rule_results,
                        "component_failures": component_failures
                    }
                )
                db.session.add(trace)
                
                # Update claim with final results
                claim.status = "COMPLETED"
                claim.decision = decision
                claim.approved_amount = Decimal(str(approved_amount))
                claim.confidence = Decimal(str(confidence))
                claim.primary_reason = primary_reason
                claim.claim_facts = claim_facts
                
                db.session.commit()
                
                logger.info(f"Claim {claim_id} processing completed: {decision}")
                
                return {
                    'status': 'COMPLETED',
                    'decision': decision,
                    'approved_amount': approved_amount,
                    'confidence': confidence,
                    'claim_id': claim_id,
                    'component_failures': component_failures
                }
                
            except Exception as eval_error:
                logger.error(f"Policy evaluation failed for claim {claim_id}: {str(eval_error)}")
                # Policy evaluation failed
                claim.status = "COMPLETED"
                claim.decision = "REJECTED"
                claim.primary_reason = f"Policy evaluation failed: {str(eval_error)}"
                claim.confidence = Decimal(str(max(0.0, min(1.0, confidence))))
                
                db.session.commit()
                
                return {
                    'status': 'COMPLETED',
                    'decision': 'REJECTED',
                    'approved_amount': 0.0,
                    'confidence': float(claim.confidence),
                    'message': claim.primary_reason
                }
        
        except Exception as e:
            logger.error(f"Unexpected error processing claim {claim_id}: {str(e)}")
            # Update claim status to indicate error
            try:
                claim = Claim.query.filter_by(id=claim_id).first()
                if claim:
                    claim.status = "COMPLETED"
                    claim.decision = "REJECTED"
                    claim.primary_reason = f"Processing error: {str(e)}"
                    db.session.commit()
            except:
                pass
            
            raise


def _run_early_validation_checks(claim_id: str) -> Dict[str, Any]:
    """
    Run early validation checks before full processing.
    
    Checks:
    1. Document type matches expected tag (TC001)
    2. Document quality is readable (TC002)
    3. Patient names are consistent across documents (TC003)
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Dictionary with validation result:
        {
            "passed": bool,
            "message": str,
            "issues": list of issue descriptions
        }
    """
    from app.models.claim_document import ClaimDocument

    def _extract_text(value: Any) -> str:
        """Extract a best-effort text value from str/dict/list OCR payloads."""
        if isinstance(value, str):
            return value.strip()

        if isinstance(value, dict):
            for key in ("value", "text", "name", "full_name", "patient_name", "doc_type"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return ""

        if isinstance(value, list):
            for item in value:
                text = _extract_text(item)
                if text:
                    return text
            return ""

        return ""

    def _extract_string_list(value: Any) -> list[str]:
        """Normalize potential OCR list payloads into a list of strings."""
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []

        if isinstance(value, list):
            result = []
            for item in value:
                text = _extract_text(item)
                if text:
                    result.append(text)
            return result

        if isinstance(value, dict):
            text = _extract_text(value)
            return [text] if text else []

        return []
    
    issues = []
    
    # Load claim documents
    documents = db.session.query(ClaimDocument).filter_by(claim_id=claim_id).all()
    
    if not documents:
        return {
            "passed": False,
            "message": "No documents found for claim",
            "issues": ["NO_DOCUMENTS"]
        }
    
    # Check 1: Document type matches expected tag (TC001)
    for doc in documents:
        if doc.extracted_fields:
            inferred_type = _extract_text(doc.extracted_fields.get('doc_type', '')).upper()
            expected_type = _extract_text(doc.doc_tag).upper()
            
            # Check if types match
            if inferred_type and inferred_type != expected_type and inferred_type != 'UNKNOWN':
                issues.append({
                    "type": "WRONG_DOCUMENT_TYPE",
                    "document_id": doc.id,
                    "expected": expected_type,
                    "uploaded": inferred_type,
                    "filename": doc.original_filename,
                    "message": f"Wrong document uploaded: You uploaded a {inferred_type} but we need a {expected_type}. Please re-upload the correct document type. Your claim has not been rejected - we just need the right document to proceed."
                })
    
    # Check 2: Document quality is readable (TC002)
    for doc in documents:
        if doc.extracted_fields:
            quality_flags = _extract_string_list(doc.extracted_fields.get('quality_flags', []))
            
            # Check for unreadable quality flags
            unreadable_flags = [flag for flag in quality_flags if 'unreadable' in flag.lower() or 'blurry' in flag.lower() or 'low quality' in flag.lower()]
            
            if unreadable_flags:
                issues.append({
                    "type": "UNREADABLE_DOCUMENT",
                    "document_id": doc.id,
                    "doc_tag": doc.doc_tag,
                    "filename": doc.original_filename,
                    "quality_flags": unreadable_flags,
                    "message": f"The {doc.doc_tag} document ({doc.original_filename}) cannot be read clearly. Please re-upload a clearer photo or scan of this specific document. Your claim has not been rejected - we just need a readable version of this document to proceed."
                })
    
    # Check 3: Patient name consistency (TC003)
    patient_names = {}
    for doc in documents:
        if doc.extracted_fields:
            patient_name = _extract_text(doc.extracted_fields.get('patient_name', ''))
            if patient_name:
                if doc.doc_tag not in patient_names:
                    patient_names[doc.doc_tag] = patient_name
    
    # Check if all patient names are consistent
    if len(set(patient_names.values())) > 1:
        # Different patient names found
        name_details = [f"{tag}: {name}" for tag, name in patient_names.items()]
        issues.append({
            "type": "PATIENT_NAME_MISMATCH",
            "patient_names": patient_names,
            "message": f"Documents belong to different patients. We found these names: {', '.join(name_details)}. Please ensure all documents are for the same patient and re-upload the correct documents. Your claim has not been rejected - we just need documents for the same patient to proceed."
        })
    
    # Determine if validation passed
    if issues:
        # Build comprehensive message
        if any(issue["type"] == "WRONG_DOCUMENT_TYPE" for issue in issues):
            wrong_doc_issues = [issue for issue in issues if issue["type"] == "WRONG_DOCUMENT_TYPE"]
            message = wrong_doc_issues[0]["message"]
        elif any(issue["type"] == "UNREADABLE_DOCUMENT" for issue in issues):
            unreadable_issues = [issue for issue in issues if issue["type"] == "UNREADABLE_DOCUMENT"]
            message = unreadable_issues[0]["message"]
        elif any(issue["type"] == "PATIENT_NAME_MISMATCH" for issue in issues):
            mismatch_issues = [issue for issue in issues if issue["type"] == "PATIENT_NAME_MISMATCH"]
            message = mismatch_issues[0]["message"]
        else:
            message = "Document validation failed. Please review and resubmit."
        
        return {
            "passed": False,
            "message": message,
            "issues": issues
        }
    
    return {
        "passed": True,
        "message": "All early validation checks passed",
        "issues": []
    }
