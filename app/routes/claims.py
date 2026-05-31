import os
from datetime import datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from app.database import db
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.models.claim_trace import ClaimTrace
from app.utils.policy_loader import load_policy_terms
from app.tasks.claim_processing import process_claim_documents
from app.celery_app import celery

claims_bp = Blueprint("claims", __name__)

# Configuration
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx"}


def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _to_float(value):
    if value is None:
        return None
    return float(value)


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def _serialize_document(document):
    return {
        "id": document.id,
        "claim_id": document.claim_id,
        "file_path": document.file_path,
        "original_filename": document.original_filename,
        "mime_type": document.mime_type,
        "doc_tag": document.doc_tag,
        "ocr_text": document.ocr_text,
        "extracted_fields": document.extracted_fields,
        "doc_confidence": _to_float(document.doc_confidence),
        "uploaded_at": _serialize_datetime(document.uploaded_at),
    }


def _serialize_trace(trace):
    return {
        "id": trace.id,
        "claim_id": trace.claim_id,
        "step": trace.step,
        "status": trace.status,
        "details": trace.details,
        "created_at": _serialize_datetime(trace.created_at),
    }


def _serialize_claim_summary(claim):
    return {
        "id": claim.id,
        "external_id": claim.external_id,
        "policy_id": claim.policy_id if hasattr(claim, 'policy_id') else None,
        "member_id": claim.member_id,
        "patient_name": claim.patient_name,
        "relationship": claim.relationship,
        "claim_type": claim.claim_type,
        "treatment_date": claim.treatment_date.isoformat() if claim.treatment_date else None,
        "submission_date": claim.submission_date.isoformat() if claim.submission_date else None,
        "claimed_amount": _to_float(claim.claimed_amount),
        "hospital_name": claim.hospital_name,
        "is_network_hospital": claim.is_network_hospital,
        "pre_auth_present": claim.pre_auth_present if hasattr(claim, 'pre_auth_present') else False,
        "status": claim.status,
        "decision": claim.decision,
        "approved_amount": _to_float(claim.approved_amount),
        "confidence": _to_float(claim.confidence),
        "primary_reason": claim.primary_reason,
        "claim_facts": claim.claim_facts,
        "document_count": len(claim.documents) if claim.documents else 0,
        "trace_count": len(claim.traces) if claim.traces else 0,
        "created_at": _serialize_datetime(claim.created_at),
        "updated_at": _serialize_datetime(claim.updated_at),
    }


def _serialize_claim_detail(claim):
    payload = _serialize_claim_summary(claim)
    payload["documents"] = [
        _serialize_document(document)
        for document in sorted(claim.documents, key=lambda document: document.uploaded_at or datetime.min)
    ]
    payload["traces"] = [
        _serialize_trace(trace)
        for trace in sorted(claim.traces, key=lambda trace: trace.created_at or datetime.min)
    ]
    return payload


@claims_bp.route("/claims", methods=["GET"])
def list_claims():
    """Return all claims with summary fields for the dashboard."""
    claims = Claim.query.order_by(Claim.created_at.desc()).all()
    return jsonify({
        "claims": [_serialize_claim_summary(claim) for claim in claims],
        "count": len(claims),
    }), 200


@claims_bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    """Return a single claim with its documents and traces."""
    claim = Claim.query.filter_by(id=claim_id).first()
    if claim is None:
        return jsonify({
            "error": "Claim not found",
            "message": f"No claim exists with id '{claim_id}'"
        }), 404

    return jsonify({
        "claim": _serialize_claim_detail(claim)
    }), 200


@claims_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task_status(task_id):
    """
    Get the status of a background processing task.
    
    Returns:
        - PENDING: Task is waiting to be executed
        - PROCESSING: Task is currently running
        - SUCCESS: Task completed successfully
        - FAILURE: Task failed with an error
    """
    task = celery.AsyncResult(task_id)
    
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Task is waiting to be processed...'
        }
    elif task.state == 'PROCESSING':
        response = {
            'state': task.state,
            'status': task.info.get('step', 'Processing...'),
            'progress': task.info.get('progress', 0)
        }
    elif task.state == 'SUCCESS':
        response = {
            'state': task.state,
            'result': task.result
        }
    elif task.state == 'FAILURE':
        response = {
            'state': task.state,
            'status': str(task.info),
            'error': str(task.info)
        }
    else:
        response = {
            'state': task.state,
            'status': str(task.info)
        }
    
    return jsonify(response), 200


def save_claim_document(file, claim_id, doc_tag, original_filename):
    """
    Save an uploaded file to the uploads directory and create a ClaimDocument record.
    
    Args:
        file: The uploaded file object
        claim_id: The UUID of the claim
        doc_tag: The document tag (e.g., PRESCRIPTION, HOSPITAL_BILL)
        original_filename: The original filename from the upload
    
    Returns:
        ClaimDocument: The created ClaimDocument instance
    """
    # Create claim-specific directory
    claim_dir = os.path.join(UPLOAD_FOLDER, str(claim_id))
    os.makedirs(claim_dir, exist_ok=True)
    
    # Secure the filename and save
    filename = secure_filename(original_filename)
    file_path = os.path.join(claim_dir, filename)
    file.save(file_path)
    
    # Determine MIME type
    mime_type = file.content_type if hasattr(file, "content_type") else None
    
    # Create ClaimDocument record
    claim_document = ClaimDocument(
        claim_id=claim_id,
        file_path=file_path,
        original_filename=original_filename,
        mime_type=mime_type,
        doc_tag=doc_tag
    )
    
    return claim_document


def check_document_presence(claim_type, uploaded_tags):
    """
    Check if all required documents are present for the given claim type.
    
    Args:
        claim_type: The type of claim (e.g., CONSULTATION, DIAGNOSTIC)
        uploaded_tags: List of document tags that were uploaded
    
    Returns:
        dict: {
            "passed": bool,
            "required": list,
            "optional": list,
            "uploaded": list,
            "missing": list
        }
    """
    policy_terms = load_policy_terms()
    document_requirements = policy_terms.get("document_requirements", {})
    
    # Get requirements for this claim type
    requirements = document_requirements.get(claim_type, {})
    required_tags = requirements.get("required", [])
    optional_tags = requirements.get("optional", [])
    
    # Convert uploaded_tags to a set for comparison
    uploaded_set = set(uploaded_tags)
    required_set = set(required_tags)
    
    # Find missing required documents
    missing_tags = list(required_set - uploaded_set)
    
    # Check if all required documents are present
    passed = len(missing_tags) == 0
    
    return {
        "passed": passed,
        "required": required_tags,
        "optional": optional_tags,
        "uploaded": uploaded_tags,
        "missing": missing_tags
    }


@claims_bp.route("/claims", methods=["POST"])
def create_claim():
    """
    Intake & Document Presence Agent
    
    Accepts a new claim submission with documents and performs initial validation:
    1. Validates required fields and documents
    2. Creates claim record
    3. Saves uploaded documents
    4. Checks document presence requirements
    5. Returns appropriate status based on document completeness
    """
    try:
        # Extract form data
        policy_id = request.form.get("policy_id")
        member_id = request.form.get("member_id")
        patient_name = request.form.get("patient_name")
        relationship = request.form.get("relationship")
        claim_type = request.form.get("claim_type")
        treatment_date_str = request.form.get("treatment_date")
        submission_date_str = request.form.get("submission_date")
        claimed_amount_str = request.form.get("claimed_amount")
        hospital_name = request.form.get("hospital_name")
        pre_auth_present_str = request.form.get("pre_auth_present", "false")
        
        # Extract files and tags
        documents = request.files.getlist("documents")
        document_tags = request.form.getlist("document_tags")
        
        # Validation: Check if documents are present
        if not documents or len(documents) == 0:
            return jsonify({
                "error": "No documents provided",
                "message": "At least one document must be uploaded"
            }), 400
        
        # Validation: Check if document count matches tag count
        if len(documents) != len(document_tags):
            return jsonify({
                "error": "Document count mismatch",
                "message": f"Number of documents ({len(documents)}) must match number of tags ({len(document_tags)})"
            }), 400
        
        # Validation: Check document_tags are valid
        valid_doc_tags = ["PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT", "PHARMACY_BILL", 
                         "DIAGNOSTIC_REPORT", "DISCHARGE_SUMMARY", "DENTAL_REPORT", "DENTAL_BILL"]
        for tag in document_tags:
            if tag.upper() not in valid_doc_tags:
                return jsonify({
                    "error": "Invalid document tag",
                    "message": f"Document tag '{tag}' is not valid. Valid tags: {', '.join(valid_doc_tags)}"
                }), 400
        
        # Validation: Check required fields
        required_fields = {
            "policy_id": policy_id,
            "member_id": member_id,
            "claim_type": claim_type,
            "treatment_date": treatment_date_str,
            "submission_date": submission_date_str,
            "claimed_amount": claimed_amount_str
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            return jsonify({
                "error": "Missing required fields",
                "message": f"The following required fields are missing: {', '.join(missing_fields)}"
            }), 400
        
        # Validation: Check policy_id against policy_terms.json
        policy_terms = load_policy_terms()
        if policy_id != policy_terms.get("policy_id"):
            return jsonify({
                "error": "Invalid policy_id",
                "message": f"Policy ID '{policy_id}' does not match the active policy '{policy_terms.get('policy_id')}'"
            }), 400
        
        # Parse dates
        try:
            treatment_date = datetime.strptime(treatment_date_str, "%Y-%m-%d").date()
            submission_date = datetime.strptime(submission_date_str, "%Y-%m-%d").date()
        except ValueError as e:
            return jsonify({
                "error": "Invalid date format",
                "message": "Dates must be in YYYY-MM-DD format (e.g., 2024-12-25)"
            }), 400
        
        # Validation: Check treatment_date is not in the future
        from datetime import date as date_class
        today = date_class.today()
        if treatment_date > today:
            return jsonify({
                "error": "Invalid treatment_date",
                "message": f"Treatment date '{treatment_date}' cannot be in the future. Today is {today}"
            }), 400
        
        # Validation: Check submission_date >= treatment_date
        if submission_date < treatment_date:
            return jsonify({
                "error": "Invalid submission_date",
                "message": f"Submission date '{submission_date}' cannot be before treatment date '{treatment_date}'"
            }), 400
        
        # Parse claimed amount
        try:
            claimed_amount = Decimal(claimed_amount_str)
        except (ValueError, TypeError):
            return jsonify({
                "error": "Invalid claimed amount",
                "message": "Claimed amount must be a valid number"
            }), 400
        
        # Validation: Check claimed_amount is positive
        if claimed_amount <= 0:
            return jsonify({
                "error": "Invalid claimed amount",
                "message": f"Claimed amount must be greater than 0. Received: {claimed_amount}"
            }), 400
        
        # Validation: Check claimed_amount is reasonable (not exceeding sum_insured)
        coverage = policy_terms.get("coverage", {})
        sum_insured = Decimal(str(coverage.get("sum_insured_per_employee", 500000)))
        if claimed_amount > sum_insured:
            return jsonify({
                "error": "Claimed amount exceeds policy limit",
                "message": f"Claimed amount ₹{claimed_amount} exceeds sum insured per employee ₹{sum_insured}"
            }), 400
        
        # Parse pre_auth_present
        pre_auth_present = pre_auth_present_str.lower() == "true"
        
        # Validate member_id exists in policy
        members = policy_terms.get("members", [])
        member = next((m for m in members if m.get("member_id") == member_id), None)
        if member is None:
            return jsonify({
                "error": "Invalid member_id",
                "message": f"Member ID '{member_id}' not found in policy '{policy_id}'"
            }), 400
        
        # Validation: Check relationship matches member's relationship in policy
        if relationship:
            member_relationship = member.get("relationship", "SELF")
            if relationship.upper() != member_relationship.upper():
                return jsonify({
                    "error": "Relationship mismatch",
                    "message": f"Provided relationship '{relationship}' does not match member's relationship '{member_relationship}' in policy"
                }), 400
        
        # Validation: If member is dependent, validate primary member exists
        if member.get("relationship") != "SELF":
            primary_member_id = member.get("primary_member_id")
            if not primary_member_id:
                return jsonify({
                    "error": "Invalid dependent member",
                    "message": f"Dependent member '{member_id}' has no primary member linked in policy"
                }), 400
            
            primary_member = next((m for m in members if m.get("member_id") == primary_member_id), None)
            if not primary_member:
                return jsonify({
                    "error": "Invalid dependent member",
                    "message": f"Primary member '{primary_member_id}' for dependent '{member_id}' not found in policy"
                }), 400
        
        # Validation: Check treatment_date is within policy period
        policy_holder = policy_terms.get("policy_holder", {})
        policy_start_str = policy_holder.get("policy_start_date")
        policy_end_str = policy_holder.get("policy_end_date")
        
        if policy_start_str and policy_end_str:
            policy_start = datetime.strptime(policy_start_str, "%Y-%m-%d").date()
            policy_end = datetime.strptime(policy_end_str, "%Y-%m-%d").date()
            
            if not (policy_start <= treatment_date <= policy_end):
                return jsonify({
                    "error": "Treatment date outside policy period",
                    "message": f"Treatment date '{treatment_date}' is outside policy period ({policy_start} to {policy_end})"
                }), 400
        
        # Validate claim_type is covered in policy
        opd_categories = policy_terms.get("opd_categories", {})
        if claim_type.lower() not in opd_categories:
            return jsonify({
                "error": "Invalid claim_type",
                "message": f"Claim type '{claim_type}' is not recognized in policy '{policy_id}'. Valid types: {', '.join(opd_categories.keys())}"
            }), 400
        
        category_config = opd_categories.get(claim_type.lower(), {})
        if not category_config.get("covered", False):
            return jsonify({
                "error": "Claim type not covered",
                "message": f"Claim type '{claim_type}' is not covered under policy '{policy_id}'"
            }), 400
        
        # Validation: Check hospital_name against network hospitals (warning only)
        network_warning = None
        if hospital_name:
            network_hospitals = policy_terms.get("network_hospitals", [])
            is_network = False
            hospital_name_lower = hospital_name.lower().strip()
            
            for network_hospital in network_hospitals:
                if network_hospital.lower().strip() in hospital_name_lower or hospital_name_lower in network_hospital.lower().strip():
                    is_network = True
                    break
            
            if not is_network:
                network_warning = f"Hospital '{hospital_name}' is not in the network. Network discounts will not apply."
        
        # Create Claim record with status PENDING initially
        claim = Claim(
            policy_id=policy_id,
            member_id=member_id,
            patient_name=patient_name,
            relationship=relationship,
            claim_type=claim_type,
            treatment_date=treatment_date,
            submission_date=submission_date,
            claimed_amount=claimed_amount,
            hospital_name=hospital_name,
            pre_auth_present=pre_auth_present,
            status="PENDING"
        )
        
        db.session.add(claim)
        db.session.flush()  # Get the claim ID without committing
        
        claim_id = claim.id
        
        # Save documents and create ClaimDocument records
        for file, doc_tag in zip(documents, document_tags):
            if file and file.filename:
                # Validate file extension
                if not allowed_file(file.filename):
                    db.session.rollback()
                    return jsonify({
                        "error": "Invalid file type",
                        "message": f"File '{file.filename}' has an unsupported extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
                    }), 400
                
                # Save document
                claim_document = save_claim_document(
                    file=file,
                    claim_id=claim_id,
                    doc_tag=doc_tag,
                    original_filename=file.filename
                )
                db.session.add(claim_document)
        
        # Perform document presence check
        doc_check_result = check_document_presence(claim_type, document_tags)
        
        if not doc_check_result["passed"]:
            # Document presence check FAILED
            missing_tags = doc_check_result["missing"]
            
            # Create ClaimTrace for failed check
            trace = ClaimTrace(
                claim_id=claim_id,
                step="DOC_PRESENCE_CHECK",
                status="FAIL",
                details={
                    "claim_type": claim_type,
                    "required": doc_check_result["required"],
                    "optional": doc_check_result["optional"],
                    "uploaded": doc_check_result["uploaded"],
                    "missing": missing_tags
                }
            )
            db.session.add(trace)
            
            # Update claim status to COMPLETED with explanation
            claim.status = "COMPLETED"
            claim.decision = None
            claim.primary_reason = (
                f"Claim rejected due to incomplete documentation. "
                f"Missing required documents for {claim_type}: {', '.join(missing_tags)}. "
                f"Please resubmit with all required documents."
            )
            
            db.session.commit()
            
            return jsonify({
                "claim_id": claim_id,
                "status": "DOCS_INCOMPLETE",
                "missing": missing_tags,
                "message": f"Claim submission incomplete. Missing required documents: {', '.join(missing_tags)}"
            }), 400
        
        else:
            # Document presence check PASSED
            # Create ClaimTrace for successful check
            trace = ClaimTrace(
                claim_id=claim_id,
                step="DOC_PRESENCE_CHECK",
                status="PASS",
                details={
                    "claim_type": claim_type,
                    "required": doc_check_result["required"],
                    "optional": doc_check_result["optional"],
                    "uploaded": doc_check_result["uploaded"]
                }
            )
            db.session.add(trace)
            
            # Update claim status to PROCESSING for subsequent agents
            claim.status = "PROCESSING"
            
            db.session.commit()
            
            # ===== QUEUE BACKGROUND PROCESSING =====
            # Queue the claim processing task to run in the background
            try:
                task = process_claim_documents.delay(claim_id)
                
                response_data = {
                    "claim_id": claim_id,
                    "status": "PROCESSING",
                    "task_id": task.id,
                    "message": "Claim submitted successfully and is being processed in the background"
                }
                
                # Add network warning if present
                if network_warning:
                    response_data["warning"] = network_warning
                
                return jsonify(response_data), 202
                
            except Exception as task_error:
                # If task queueing fails, mark claim as failed
                claim.status = "COMPLETED"
                claim.decision = "REJECTED"
                claim.primary_reason = f"Failed to queue processing task: {str(task_error)}"
                
                db.session.commit()
                
                return jsonify({
                    "claim_id": claim_id,
                    "status": "COMPLETED",
                    "decision": "REJECTED",
                    "message": claim.primary_reason
                }), 500
    
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500
