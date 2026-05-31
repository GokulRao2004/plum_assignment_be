"""
Validation Helper Functions

This module provides reusable validation functions for claim processing.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Any, Tuple, Optional


def validate_policy_id(policy_id: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate policy ID against policy terms.
    
    Args:
        policy_id: Policy ID to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    expected_policy_id = policy_terms.get("policy_id")
    
    if not policy_id:
        return False, "Policy ID is required"
    
    if policy_id != expected_policy_id:
        return False, f"Policy ID '{policy_id}' does not match active policy '{expected_policy_id}'"
    
    return True, None


def validate_member_id(member_id: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    Validate member ID exists in policy.
    
    Args:
        member_id: Member ID to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message, member_dict)
    """
    if not member_id:
        return False, "Member ID is required", None
    
    members = policy_terms.get("members", [])
    member = next((m for m in members if m.get("member_id") == member_id), None)
    
    if not member:
        return False, f"Member ID '{member_id}' not found in policy", None
    
    return True, None, member


def validate_relationship(relationship: str, member: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate relationship matches member's relationship in policy.
    
    Args:
        relationship: Relationship to validate
        member: Member dictionary from policy
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not relationship:
        return True, None  # Relationship is optional
    
    member_relationship = member.get("relationship", "SELF")
    
    if relationship.upper() != member_relationship.upper():
        return False, f"Provided relationship '{relationship}' does not match member's relationship '{member_relationship}'"
    
    return True, None


def validate_dependent_member(member: Dict[str, Any], policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate dependent member has valid primary member.
    
    Args:
        member: Member dictionary
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if member.get("relationship") == "SELF":
        return True, None  # Not a dependent
    
    primary_member_id = member.get("primary_member_id")
    
    if not primary_member_id:
        return False, f"Dependent member '{member.get('member_id')}' has no primary member linked"
    
    members = policy_terms.get("members", [])
    primary_member = next((m for m in members if m.get("member_id") == primary_member_id), None)
    
    if not primary_member:
        return False, f"Primary member '{primary_member_id}' not found in policy"
    
    return True, None


def validate_claim_type(claim_type: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    Validate claim type is recognized and covered.
    
    Args:
        claim_type: Claim type to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message, category_config)
    """
    if not claim_type:
        return False, "Claim type is required", None
    
    opd_categories = policy_terms.get("opd_categories", {})
    claim_type_lower = claim_type.lower()
    
    if claim_type_lower not in opd_categories:
        valid_types = ', '.join(opd_categories.keys())
        return False, f"Claim type '{claim_type}' is not recognized. Valid types: {valid_types}", None
    
    category_config = opd_categories.get(claim_type_lower, {})
    
    if not category_config.get("covered", False):
        return False, f"Claim type '{claim_type}' is not covered under this policy", None
    
    return True, None, category_config


def validate_treatment_date(treatment_date: date, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate treatment date is valid and within policy period.
    
    Args:
        treatment_date: Treatment date to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check not in future
    today = date.today()
    if treatment_date > today:
        return False, f"Treatment date '{treatment_date}' cannot be in the future. Today is {today}"
    
    # Check within policy period
    policy_holder = policy_terms.get("policy_holder", {})
    policy_start_str = policy_holder.get("policy_start_date")
    policy_end_str = policy_holder.get("policy_end_date")
    
    if policy_start_str and policy_end_str:
        policy_start = datetime.strptime(policy_start_str, "%Y-%m-%d").date()
        policy_end = datetime.strptime(policy_end_str, "%Y-%m-%d").date()
        
        if not (policy_start <= treatment_date <= policy_end):
            return False, f"Treatment date '{treatment_date}' is outside policy period ({policy_start} to {policy_end})"
    
    return True, None


def validate_submission_date(submission_date: date, treatment_date: date) -> Tuple[bool, Optional[str]]:
    """
    Validate submission date is after or equal to treatment date.
    
    Args:
        submission_date: Submission date to validate
        treatment_date: Treatment date
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if submission_date < treatment_date:
        return False, f"Submission date '{submission_date}' cannot be before treatment date '{treatment_date}'"
    
    return True, None


def validate_claimed_amount(claimed_amount: Decimal, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate claimed amount is positive and within policy limits.
    
    Args:
        claimed_amount: Claimed amount to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check positive
    if claimed_amount <= 0:
        return False, f"Claimed amount must be greater than 0. Received: {claimed_amount}"
    
    # Check against sum insured
    coverage = policy_terms.get("coverage", {})
    sum_insured = Decimal(str(coverage.get("sum_insured_per_employee", 500000)))
    
    if claimed_amount > sum_insured:
        return False, f"Claimed amount ₹{claimed_amount} exceeds sum insured per employee ₹{sum_insured}"
    
    return True, None


def validate_hospital_name(hospital_name: str, policy_terms: Dict[str, Any]) -> Tuple[bool, bool, Optional[str]]:
    """
    Validate hospital name and check if it's in network.
    
    Args:
        hospital_name: Hospital name to validate
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, is_network, warning_message)
    """
    if not hospital_name:
        return True, False, None  # Hospital name is optional
    
    network_hospitals = policy_terms.get("network_hospitals", [])
    is_network = False
    hospital_name_lower = hospital_name.lower().strip()
    
    for network_hospital in network_hospitals:
        if network_hospital.lower().strip() in hospital_name_lower or hospital_name_lower in network_hospital.lower().strip():
            is_network = True
            break
    
    warning = None
    if not is_network:
        warning = f"Hospital '{hospital_name}' is not in the network. Network discounts will not apply."
    
    return True, is_network, warning


def validate_document_tags(document_tags: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate document tags are recognized.
    
    Args:
        document_tags: List of document tags to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    valid_doc_tags = [
        "PRESCRIPTION", "HOSPITAL_BILL", "LAB_REPORT", "PHARMACY_BILL",
        "DIAGNOSTIC_REPORT", "DISCHARGE_SUMMARY", "DENTAL_REPORT", "DENTAL_BILL"
    ]
    
    for tag in document_tags:
        if tag.upper() not in valid_doc_tags:
            return False, f"Document tag '{tag}' is not valid. Valid tags: {', '.join(valid_doc_tags)}"
    
    return True, None


def validate_diagnosis_against_exclusions(diagnosis: str, claim_type: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate diagnosis is not in exclusions list.
    
    Args:
        diagnosis: Diagnosis string
        claim_type: Claim type
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not diagnosis:
        return True, None  # No diagnosis to check
    
    exclusions = policy_terms.get("exclusions", {})
    diagnosis_lower = diagnosis.lower()
    
    # Check global exclusions
    global_exclusions = [c.lower() for c in exclusions.get("conditions", [])]
    for exclusion in global_exclusions:
        if exclusion and exclusion.split()[0] in diagnosis_lower:
            return False, f"Diagnosis '{diagnosis}' matches excluded condition '{exclusion}'"
    
    # Check category-specific exclusions
    if claim_type.upper() == "DENTAL":
        dental_exclusions = [c.lower() for c in exclusions.get("dental_exclusions", [])]
        for exclusion in dental_exclusions:
            if exclusion and exclusion.split()[0] in diagnosis_lower:
                return False, f"Dental diagnosis '{diagnosis}' matches excluded procedure '{exclusion}'"
    
    if claim_type.upper() == "VISION":
        vision_exclusions = [c.lower() for c in exclusions.get("vision_exclusions", [])]
        for exclusion in vision_exclusions:
            if exclusion and exclusion.split()[0] in diagnosis_lower:
                return False, f"Vision diagnosis '{diagnosis}' matches excluded item '{exclusion}'"
    
    return True, None


def validate_procedures_against_coverage(procedures: List[str], claim_type: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate procedures are covered under the claim type.
    
    Args:
        procedures: List of procedure names
        claim_type: Claim type
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not procedures:
        return True, None  # No procedures to check
    
    opd_categories = policy_terms.get("opd_categories", {})
    
    # Check dental procedures
    if claim_type.upper() == "DENTAL":
        dental_config = opd_categories.get("dental", {})
        excluded_procedures = [p.lower() for p in dental_config.get("excluded_procedures", [])]
        
        for proc in procedures:
            proc_name = proc.lower() if isinstance(proc, str) else proc.get("name", "").lower()
            for excluded in excluded_procedures:
                if excluded in proc_name or proc_name in excluded:
                    return False, f"Dental procedure '{proc_name}' is excluded from coverage"
    
    # Check vision items
    if claim_type.upper() == "VISION":
        vision_config = opd_categories.get("vision", {})
        excluded_items = [p.lower() for p in vision_config.get("excluded_items", [])]
        
        for proc in procedures:
            proc_name = proc.lower() if isinstance(proc, str) else proc.get("name", "").lower()
            for excluded in excluded_items:
                if excluded in proc_name or proc_name in excluded:
                    return False, f"Vision item '{proc_name}' is excluded from coverage"
    
    return True, None


def validate_alternative_medicine_system(diagnosis: str, policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate alternative medicine system is covered.
    
    Args:
        diagnosis: Diagnosis string
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not diagnosis:
        return True, None
    
    opd_categories = policy_terms.get("opd_categories", {})
    alt_med_config = opd_categories.get("alternative_medicine", {})
    covered_systems = [s.lower() for s in alt_med_config.get("covered_systems", [])]
    
    diagnosis_lower = diagnosis.lower()
    
    # Check if any covered system is mentioned
    system_found = False
    for system in covered_systems:
        if system in diagnosis_lower:
            system_found = True
            break
    
    # If alternative medicine keywords found but no covered system
    alt_med_keywords = ["ayurved", "homeopath", "unani", "siddha", "naturopath"]
    has_alt_med_keyword = any(keyword in diagnosis_lower for keyword in alt_med_keywords)
    
    if has_alt_med_keyword and not system_found:
        return False, f"Alternative medicine system in diagnosis not covered. Covered systems: {', '.join(covered_systems)}"
    
    return True, None


def validate_per_category_amounts(per_category_amounts: Dict[str, float], claimed_amount: float, tolerance: float = 0.01) -> Tuple[bool, Optional[str]]:
    """
    Validate per-category amounts sum matches claimed amount.
    
    Args:
        per_category_amounts: Dictionary of category amounts
        claimed_amount: Total claimed amount
        tolerance: Acceptable difference (default 0.01 for rounding)
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not per_category_amounts:
        return True, None  # No breakdown to validate
    
    total = sum(per_category_amounts.values())
    difference = abs(total - claimed_amount)
    
    if difference > tolerance:
        return False, f"Sum of per-category amounts (₹{total:.2f}) does not match claimed amount (₹{claimed_amount:.2f}). Difference: ₹{difference:.2f}"
    
    return True, None


def validate_family_floater_relationships(member: Dict[str, Any], policy_terms: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate member's relationship is covered under family floater.
    
    Args:
        member: Member dictionary
        policy_terms: Policy terms dictionary
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    coverage = policy_terms.get("coverage", {})
    family_floater = coverage.get("family_floater", {})
    
    if not family_floater.get("enabled", False):
        return True, None  # Family floater not enabled
    
    covered_relationships = [r.upper() for r in family_floater.get("covered_relationships", [])]
    member_relationship = member.get("relationship", "SELF").upper()
    
    if member_relationship not in covered_relationships:
        return False, f"Relationship '{member_relationship}' is not covered under family floater. Covered: {', '.join(covered_relationships)}"
    
    return True, None
