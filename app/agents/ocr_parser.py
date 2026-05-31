"""
OCR & Document Parsing Agent

This module provides OCR and document parsing capabilities for claim documents.
It integrates the advanced OCR pipeline that supports:
- Multi-page PDF rendering (PyMuPDF)
- Advanced OCR engines (EasyOCR, PaddleOCR with auto-selection)
- Document type inference
- Smart field extraction (medicines, tests, amounts, dates, etc.)
- Fraud detection (duplicate stamps, alterations, partial documents)
- Quality assessment and validation
"""

import os
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal

logger = logging.getLogger(__name__)

from app.database import db
from app.models.claim import Claim
from app.models.claim_document import ClaimDocument
from app.ocr.pipeline import process_document



# ============================================================================
# Main Agent Function
# ============================================================================

def run_ocr_and_parse_for_claim(claim_id: str) -> Dict[str, Any]:
    """
    Run OCR and document parsing for all documents in a claim using the advanced pipeline.
    
    This function:
    1. Loads the claim and its documents from the database
    2. For each document without OCR text or extracted fields:
       - Runs the advanced OCR pipeline (process_document)
       - Extracts text and structured fields
       - Performs validation and fraud checks
       - Saves extracted data to the database
    3. Returns a summary of processing results
    
    The OCR pipeline includes:
    - PDF to page rendering (PyMuPDF)
    - Automatic OCR engine selection (EasyOCR/PaddleOCR based on quality)
    - Document type inference
    - Quality assessment
    - Field extraction and validation
    - Fraud detection
    
    Args:
        claim_id: UUID of the claim to process
    
    Returns:
        Dictionary with processing summary:
        {
            "claim_id": str,
            "documents_processed": int,
            "documents_skipped": int,
            "errors": list of error messages,
            "documents_summary": list of processed document details
        }
    """
    result = {
        "claim_id": claim_id,
        "documents_processed": 0,
        "documents_skipped": 0,
        "errors": [],
        "documents_summary": []
    }
    
    try:
        # Load claim from database
        claim = db.session.query(Claim).filter_by(id=claim_id).first()
        
        if not claim:
            result["errors"].append(f"Claim not found: {claim_id}")
            return result
        
        # Load claim documents
        documents = db.session.query(ClaimDocument).filter_by(claim_id=claim_id).all()
        
        if not documents:
            result["errors"].append(f"No documents found for claim: {claim_id}")
            return result
        
        # Process each document
        for doc in documents:
            # Skip if already processed
            if doc.ocr_text and doc.extracted_fields:
                result["documents_skipped"] += 1
                doc_summary = {
                    "document_id": doc.id,
                    "doc_tag": doc.doc_tag,
                    "status": "SKIPPED",
                    "reason": "Already processed"
                }
                result["documents_summary"].append(doc_summary)
                continue
            
            try:
                # Validate file exists
                if not os.path.exists(doc.file_path):
                    error_msg = f"Document file not found: {doc.file_path}"
                    result["errors"].append(error_msg)
                    doc_summary = {
                        "document_id": doc.id,
                        "doc_tag": doc.doc_tag,
                        "status": "FAILED",
                        "reason": error_msg
                    }
                    result["documents_summary"].append(doc_summary)
                    continue
                
                # Run the advanced OCR pipeline
                logger.info(f"Processing document {doc.id} ({doc.doc_tag}) with advanced pipeline")
                pipeline_result = process_document(
                    file_path=doc.file_path,
                    expected_tag=doc.doc_tag,
                    doc_type_override='AUTO',
                    ocr_mode='AUTO'
                )
                
                # Store raw OCR text from aggregate
                doc.ocr_text = pipeline_result.get('aggregate_text', '')
                
                # Store extracted fields (includes all document-specific fields and metadata)
                doc.extracted_fields = pipeline_result
                
                # Calculate confidence based on validation results
                confidence = _calculate_confidence(pipeline_result)
                doc.doc_confidence = confidence
                
                # Log summary
                doc_summary = {
                    "document_id": doc.id,
                    "doc_tag": doc.doc_tag,
                    "inferred_doc_type": pipeline_result.get('doc_type'),
                    "status": "SUCCESS",
                    "confidence": float(confidence),
                    "page_count": pipeline_result.get('page_count'),
                    "quality_flags": pipeline_result.get('quality_flags', []),
                    "fraud_summary": pipeline_result.get('fraud_summary', {}),
                    "manual_review": pipeline_result.get('manual_review', False),
                    "manual_review_reasons": pipeline_result.get('manual_review_reasons', [])
                }
                
                result["documents_processed"] += 1
                result["documents_summary"].append(doc_summary)
                logger.info(f"Successfully processed document {doc.id}")
                
            except Exception as e:
                error_msg = f"Error processing document {doc.id} ({doc.doc_tag}): {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
                
                doc_summary = {
                    "document_id": doc.id,
                    "doc_tag": doc.doc_tag,
                    "status": "FAILED",
                    "reason": str(e)
                }
                result["documents_summary"].append(doc_summary)
                continue
        
        # Commit all changes to database
        db.session.commit()
        logger.info(f"Claim {claim_id} OCR processing completed: {result['documents_processed']} processed, {result['documents_skipped']} skipped")
        
    except Exception as e:
        db.session.rollback()
        error_msg = f"Fatal error processing claim {claim_id}: {str(e)}"
        result["errors"].append(error_msg)
        logger.error(error_msg, exc_info=True)
    
    return result


def _calculate_confidence(pipeline_result: Dict[str, Any]) -> Decimal:
    """
    Calculate confidence score based on pipeline validation results.
    
    Starts at 1.0 and deducts:
    - 0.2 if tag validation fails
    - 0.2 if required fields are missing
    - 0.2 if quality flags indicate issues
    - 0.2 if fraud checks detected issues
    - 0.1 if manual review is needed
    
    Args:
        pipeline_result: Result dictionary from process_document
    
    Returns:
        Confidence score between 0.0 and 1.0
    """
    confidence = Decimal("1.0")
    
    # Check tag validation
    tag_validation = pipeline_result.get('tag_validation', {})
    if not tag_validation.get('tag_matches', True):
        confidence -= Decimal("0.2")
    
    # Check required fields
    required_validation = pipeline_result.get('required_field_validation', {})
    if not required_validation.get('all_required_fields_present', True):
        confidence -= Decimal("0.2")
    
    # Check quality flags
    quality_flags = pipeline_result.get('quality_flags', [])
    if quality_flags:
        confidence -= Decimal("0.2")
    
    # Check fraud summary
    fraud_summary = pipeline_result.get('fraud_summary', {})
    if any([
        fraud_summary.get('duplicate_stamp_terms'),
        fraud_summary.get('alteration_flags'),
        fraud_summary.get('partial_flags'),
        fraud_summary.get('duplicate_pages_detected')
    ]):
        confidence -= Decimal("0.2")
    
    # Check manual review
    if pipeline_result.get('manual_review', False):
        confidence -= Decimal("0.1")
    
    # Clamp between 0.0 and 1.0
    confidence = max(Decimal("0.0"), min(Decimal("1.0"), confidence))
    
    return round(confidence, 3)


# ============================================================================
# Utility Functions
# ============================================================================

def get_ocr_status_for_claim(claim_id: str) -> Dict[str, Any]:
    """
    Get OCR processing status for a claim.
    
    Args:
        claim_id: UUID of the claim
    
    Returns:
        Dictionary with status information for each document
    """
    documents = db.session.query(ClaimDocument).filter_by(claim_id=claim_id).all()
    
    total = len(documents)
    processed = sum(1 for doc in documents if doc.ocr_text and doc.extracted_fields)
    pending = total - processed
    
    return {
        "claim_id": claim_id,
        "total_documents": total,
        "processed": processed,
        "pending": pending,
        "documents": [
            {
                "id": doc.id,
                "doc_tag": doc.doc_tag,
                "has_ocr_text": bool(doc.ocr_text),
                "has_extracted_fields": bool(doc.extracted_fields),
                "confidence": float(doc.doc_confidence) if doc.doc_confidence else None,
                "inferred_doc_type": doc.extracted_fields.get('doc_type') if doc.extracted_fields else None,
                "manual_review_required": doc.extracted_fields.get('manual_review', False) if doc.extracted_fields else False
            }
            for doc in documents
        ]
    }


def get_document_extraction_details(doc_id: str) -> Dict[str, Any]:
    """
    Get detailed extraction results for a specific document.
    
    Args:
        doc_id: UUID of the document
    
    Returns:
        Dictionary with comprehensive extraction details
    """
    doc = db.session.query(ClaimDocument).filter_by(id=doc_id).first()
    
    if not doc:
        return {"error": f"Document not found: {doc_id}"}
    
    return {
        "document_id": doc.id,
        "claim_id": doc.claim_id,
        "doc_tag": doc.doc_tag,
        "filename": doc.original_filename,
        "confidence": float(doc.doc_confidence) if doc.doc_confidence else None,
        "extraction_result": doc.extracted_fields or {},
        "has_ocr_text": bool(doc.ocr_text),
        "manual_review_required": doc.extracted_fields.get('manual_review', False) if doc.extracted_fields else False,
        "manual_review_reasons": doc.extracted_fields.get('manual_review_reasons', []) if doc.extracted_fields else []
    }


def validate_document_extraction(doc_id: str) -> Dict[str, Any]:
    """
    Validate extracted fields for a document against expected schema.
    
    Args:
        doc_id: UUID of the document
    
    Returns:
        Validation results including tag match and field coverage
    """
    doc = db.session.query(ClaimDocument).filter_by(id=doc_id).first()
    
    if not doc:
        return {"error": f"Document not found: {doc_id}"}
    
    extracted = doc.extracted_fields or {}
    
    return {
        "document_id": doc.id,
        "doc_tag": doc.doc_tag,
        "tag_validation": extracted.get('tag_validation', {}),
        "required_field_validation": extracted.get('required_field_validation', {}),
        "quality_flags": extracted.get('quality_flags', []),
        "fraud_summary": extracted.get('fraud_summary', {}),
        "ready_for_downstream_processing": extracted.get('ready_for_downstream_processing', False)
    }

