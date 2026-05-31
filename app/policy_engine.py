"""
claim_facts dict structure (input to evaluate_claim):

{
  "claim_id": str,
  "policy_id": str,            # Policy ID from claim submission
  "member_id": str,
  "claim_type": str,           # CONSULTATION / DIAGNOSTIC / PHARMACY / ...
  "treatment_date": str,       # "YYYY-MM-DD"
  "submission_date": str,      # "YYYY-MM-DD"
  "claimed_amount": float,
  "hospital_name": str,
  "is_network_hospital": bool,
  "diagnosis": str,
  "per_category_amounts": {    # e.g. {"consultation": 1000.0, "diagnostic": 500.0}
    "<category>": float
  },
  "is_pre_existing_condition": bool,
  "is_maternity": bool,
  "is_dental_procedure": bool,
  "is_vision_item": bool,
  "same_day_claims_count": int,
  "monthly_claims_count": int,
  "high_value_flag": bool,
  "pre_auth_present": bool,
  "procedures": list,          # Extracted procedures (dental, vision, etc.)
  "medicines": list,           # Extracted medicines with branded flag
  "tests": list,               # Extracted diagnostic tests
  "session_count_ytd": int     # Year-to-date sessions for alternative medicine
}
"""

from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date
from decimal import Decimal

from app.utils.policy_loader import load_policy_terms
from app.database import db
from app.models.claim import Claim
from sqlalchemy import func, extract, and_


def _validate_policy_id(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates that the claim's policy_id matches the loaded policy.
    This is the first check to ensure we're evaluating against the correct policy.
    """
    claim_policy_id = claim_facts.get("policy_id")
    policy_id = policy.get("policy_id")
    
    if not claim_policy_id:
        return {
            "name": "policy_id_validation",
            "status": "FAIL",
            "reason": "No policy_id provided in claim",
            "amount_delta": 0.0,
        }
    
    if claim_policy_id != policy_id:
        return {
            "name": "policy_id_validation",
            "status": "FAIL",
            "reason": f"Claim policy_id '{claim_policy_id}' does not match active policy '{policy_id}'",
            "amount_delta": 0.0,
        }
    
    return {
        "name": "policy_id_validation",
        "status": "PASS",
        "reason": f"Policy ID '{policy_id}' validated successfully",
        "amount_delta": 0.0,
    }


def _check_eligibility(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks:
    - member exists in policy["members"]
    - treatment_date within policy_start_date and policy_end_date
    - policy renewal_status is ACTIVE
    - dependent relationships are valid
    """
    member_id = claim_facts["member_id"]
    members = policy.get("members", [])

    member = next((m for m in members if m.get("member_id") == member_id), None)
    if member is None:
        return {
            "name": "eligibility_member",
            "status": "FAIL",
            "reason": f"Member {member_id} not found in policy roster",
            "amount_delta": 0.0,
        }

    # Check if dependent has valid primary member
    if member.get("relationship") != "SELF":
        primary_member_id = member.get("primary_member_id")
        if not primary_member_id:
            return {
                "name": "eligibility_dependent",
                "status": "FAIL",
                "reason": f"Dependent {member_id} has no primary member linked",
                "amount_delta": 0.0,
            }
        
        primary_member = next((m for m in members if m.get("member_id") == primary_member_id), None)
        if not primary_member:
            return {
                "name": "eligibility_dependent",
                "status": "FAIL",
                "reason": f"Primary member {primary_member_id} not found for dependent {member_id}",
                "amount_delta": 0.0,
            }

    # Check policy renewal status
    holder = policy.get("policy_holder", {})
    renewal_status = holder.get("renewal_status", "ACTIVE")
    if renewal_status != "ACTIVE":
        return {
            "name": "eligibility_policy_status",
            "status": "FAIL",
            "reason": f"Policy is not active (status: {renewal_status})",
            "amount_delta": 0.0,
        }

    # Check policy dates
    start = datetime.fromisoformat(holder["policy_start_date"]).date()
    end = datetime.fromisoformat(holder["policy_end_date"]).date()
    treatment_date = datetime.fromisoformat(claim_facts["treatment_date"]).date()

    if not (start <= treatment_date <= end):
        return {
            "name": "eligibility_policy_period",
            "status": "FAIL",
            "reason": f"Treatment date {treatment_date} is outside policy period {start} to {end}",
            "amount_delta": 0.0,
        }

    return {
        "name": "eligibility",
        "status": "PASS",
        "reason": "Member eligible and policy active",
        "amount_delta": 0.0,
    }


def _check_submission_rules(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks:
    - minimum_claim_amount
    - deadline_days_from_treatment
    """
    submission_rules = policy.get("submission_rules", {})
    min_amount = submission_rules.get("minimum_claim_amount", 0)
    deadline_days = submission_rules.get("deadline_days_from_treatment", 0)

    claimed = float(claim_facts["claimed_amount"])
    if claimed < min_amount:
        return {
            "name": "submission_min_amount",
            "status": "FAIL",
            "reason": f"Claimed amount {claimed} is below minimum {min_amount}",
            "amount_delta": 0.0,
        }

    treatment_date = datetime.fromisoformat(claim_facts["treatment_date"]).date()
    submission_date = datetime.fromisoformat(claim_facts["submission_date"]).date()
    delta_days = (submission_date - treatment_date).days

    if delta_days > deadline_days:
        return {
            "name": "submission_deadline",
            "status": "FAIL",
            "reason": f"Claim submitted after {delta_days} days; deadline is {deadline_days} days",
            "amount_delta": 0.0,
        }

    return {
        "name": "submission_rules",
        "status": "PASS",
        "reason": "",
        "amount_delta": 0.0,
    }


def _check_waiting_periods(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses:
    - waiting_periods.initial_waiting_period_days
    - waiting_periods.pre_existing_conditions_days
    - waiting_periods.specific_conditions
    """
    waiting = policy.get("waiting_periods", {})
    initial_days = waiting.get("initial_waiting_period_days", 0)
    pre_existing_days = waiting.get("pre_existing_conditions_days", 0)
    specific = waiting.get("specific_conditions", {})

    # Find member join_date from policy members
    member_id = claim_facts["member_id"]
    members = policy.get("members", [])
    member = next((m for m in members if m.get("member_id") == member_id), None)

    if member is None or "join_date" not in member:
        # If we can't find join_date, be conservative and WARN, not FAIL
        return {
            "name": "waiting_periods",
            "status": "WARN",
            "reason": "Member join date not found; unable to strictly enforce waiting periods",
            "amount_delta": 0.0,
        }

    join_date = datetime.fromisoformat(member["join_date"]).date()
    treatment_date = datetime.fromisoformat(claim_facts["treatment_date"]).date()
    days_since_join = (treatment_date - join_date).days

    # Initial waiting period
    if days_since_join < initial_days:
        return {
            "name": "waiting_initial",
            "status": "FAIL",
            "reason": f"Only {days_since_join} days since join; initial waiting period is {initial_days} days",
            "amount_delta": 0.0,
        }

    diagnosis = claim_facts.get("diagnosis", "").lower()

    # Specific conditions (e.g., maternity, cataract, etc.)
    for condition_key, required_days in specific.items():
        if condition_key in diagnosis:
            if days_since_join < required_days:
                return {
                    "name": f"waiting_{condition_key}",
                    "status": "FAIL",
                    "reason": f"{condition_key} has waiting period {required_days} days; only {days_since_join} days since join",
                    "amount_delta": 0.0,
                }

    # Pre-existing conditions
    if claim_facts.get("is_pre_existing_condition", False) and days_since_join < pre_existing_days:
        return {
            "name": "waiting_pre_existing",
            "status": "FAIL",
            "reason": f"Pre-existing condition waiting period {pre_existing_days} days; only {days_since_join} days since join",
            "amount_delta": 0.0,
        }

    return {
        "name": "waiting_periods",
        "status": "PASS",
        "reason": "",
        "amount_delta": 0.0,
    }


def _check_exclusions(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks global + category-specific exclusions.
    """
    exclusions = policy.get("exclusions", {})
    global_exclusions = [c.lower() for c in exclusions.get("conditions", [])]
    dental_exclusions = [c.lower() for c in exclusions.get("dental_exclusions", [])]
    vision_exclusions = [c.lower() for c in exclusions.get("vision_exclusions", [])]

    diagnosis = claim_facts.get("diagnosis", "").lower()
    claim_type = claim_facts.get("claim_type", "").upper()

    # Global exclusions
    for cond in global_exclusions:
        if cond and cond.split()[0] in diagnosis:
            return {
                "name": "exclusions_global",
                "status": "FAIL",
                "reason": f"Diagnosis '{claim_facts.get('diagnosis')}' matches exclusion '{cond}'",
                "amount_delta": 0.0,
            }

    # Dental exclusions
    if claim_type == "DENTAL":
        for cond in dental_exclusions:
            if cond and cond.split()[0] in diagnosis:
                return {
                    "name": "exclusions_dental",
                    "status": "FAIL",
                    "reason": f"Diagnosis '{claim_facts.get('diagnosis')}' matches dental exclusion '{cond}'",
                    "amount_delta": 0.0,
                }

    # Vision exclusions
    if claim_type == "VISION":
        for cond in vision_exclusions:
            if cond and cond.split()[0] in diagnosis:
                return {
                    "name": "exclusions_vision",
                    "status": "FAIL",
                    "reason": f"Diagnosis '{claim_facts.get('diagnosis')}' matches vision exclusion '{cond}'",
                    "amount_delta": 0.0,
                }

    return {
        "name": "exclusions",
        "status": "PASS",
        "reason": "No exclusions matched",
        "amount_delta": 0.0,
    }


def _check_pre_authorization(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if pre-authorization is required and present.
    
    Pre-auth required for:
    - High-value diagnostic tests (MRI, CT, PET scan > threshold)
    - Major surgical procedures
    - Planned hospitalization
    """
    pre_auth_config = policy.get("pre_authorization", {})
    required_for = pre_auth_config.get("required_for", [])
    
    claim_type = claim_facts.get("claim_type", "").upper()
    diagnosis = claim_facts.get("diagnosis", "").lower()
    tests = claim_facts.get("tests", [])
    claimed_amount = float(claim_facts.get("claimed_amount", 0))
    pre_auth_present = claim_facts.get("pre_auth_present", False)
    
    requires_pre_auth = False
    reason_for_pre_auth = ""
    
    # Check for high-value diagnostic tests
    if claim_type == "DIAGNOSTIC":
        opd_categories = policy.get("opd_categories", {})
        diagnostic_config = opd_categories.get("diagnostic", {})
        pre_auth_threshold = float(diagnostic_config.get("pre_auth_threshold", 10000))
        high_value_tests = [t.lower() for t in diagnostic_config.get("high_value_tests_requiring_pre_auth", [])]
        
        # Check if amount exceeds threshold
        if claimed_amount > pre_auth_threshold:
            requires_pre_auth = True
            reason_for_pre_auth = f"Diagnostic claim amount ₹{claimed_amount} exceeds pre-auth threshold ₹{pre_auth_threshold}"
        
        # Check if any test is high-value
        for test in tests:
            test_name = test.lower() if isinstance(test, str) else test.get("name", "").lower()
            for high_value_test in high_value_tests:
                if high_value_test in test_name:
                    requires_pre_auth = True
                    reason_for_pre_auth = f"High-value test '{test_name}' requires pre-authorization"
                    break
            if requires_pre_auth:
                break
    
    # Check diagnosis for procedures requiring pre-auth
    for requirement in required_for:
        req_lower = requirement.lower()
        if any(keyword in diagnosis for keyword in ["mri", "ct scan", "pet scan", "surgical", "hospitalization"]):
            if any(keyword in req_lower for keyword in ["mri", "ct", "pet", "surgical", "hospitalization"]):
                requires_pre_auth = True
                reason_for_pre_auth = f"Procedure requires pre-authorization: {requirement}"
                break
    
    # If pre-auth required but not present, fail
    if requires_pre_auth and not pre_auth_present:
        return {
            "name": "pre_authorization",
            "status": "FAIL",
            "reason": f"Pre-authorization required but not provided. {reason_for_pre_auth}",
            "amount_delta": 0.0,
        }
    
    # If pre-auth required and present, pass
    if requires_pre_auth and pre_auth_present:
        return {
            "name": "pre_authorization",
            "status": "PASS",
            "reason": f"Pre-authorization verified. {reason_for_pre_auth}",
            "amount_delta": 0.0,
        }
    
    # Pre-auth not required
    return {
        "name": "pre_authorization",
        "status": "PASS",
        "reason": "Pre-authorization not required for this claim",
        "amount_delta": 0.0,
    }


def _check_procedure_coverage(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Validates that specific procedures are covered (dental, vision).
    Returns line-item breakdown for partial approvals (TC006).
    
    Returns:
        Tuple of (rule_result, line_item_breakdown)
        line_item_breakdown is None for full approval/rejection, or dict for partial
    """
    claim_type = claim_facts.get("claim_type", "").upper()
    procedures = claim_facts.get("procedures", [])
    diagnosis = claim_facts.get("diagnosis", "").lower()
    
    opd_categories = policy.get("opd_categories", {})
    line_item_breakdown = None
    
    # Check dental procedures with line-item processing (TC006)
    if claim_type == "DENTAL":
        dental_config = opd_categories.get("dental", {})
        covered_procedures = [p.lower() for p in dental_config.get("covered_procedures", [])]
        excluded_procedures = [p.lower() for p in dental_config.get("excluded_procedures", [])]
        
        # Get line items from claim_facts if available
        line_items = claim_facts.get("line_items", [])
        
        if line_items:
            # Process each line item separately
            approved_items = []
            rejected_items = []
            total_approved = 0.0
            total_rejected = 0.0
            
            for item in line_items:
                item_desc = item.get("description", "").lower()
                item_amount = float(item.get("amount", 0))
                
                # Check if item is excluded
                is_excluded = False
                exclusion_reason = ""
                
                for excluded in excluded_procedures:
                    if excluded in item_desc:
                        is_excluded = True
                        exclusion_reason = f"Cosmetic/excluded procedure: {excluded}"
                        break
                
                if is_excluded:
                    rejected_items.append({
                        "description": item.get("description"),
                        "amount": item_amount,
                        "reason": exclusion_reason
                    })
                    total_rejected += item_amount
                else:
                    approved_items.append({
                        "description": item.get("description"),
                        "amount": item_amount,
                        "reason": "Covered procedure"
                    })
                    total_approved += item_amount
            
            # If some items rejected, return partial approval with breakdown
            if rejected_items:
                line_item_breakdown = {
                    "approved_items": approved_items,
                    "rejected_items": rejected_items,
                    "total_approved": total_approved,
                    "total_rejected": total_rejected
                }
                
                if not approved_items:
                    # All items rejected
                    return {
                        "name": "procedure_coverage_dental",
                        "status": "FAIL",
                        "reason": f"All dental procedures are excluded from coverage. Total rejected: ₹{total_rejected}",
                        "amount_delta": 0.0,
                        "line_item_breakdown": line_item_breakdown
                    }, line_item_breakdown
                else:
                    # Partial approval
                    return {
                        "name": "procedure_coverage_dental",
                        "status": "PARTIAL",
                        "reason": f"Partial approval: ₹{total_approved} approved, ₹{total_rejected} rejected (excluded procedures)",
                        "amount_delta": -total_rejected,
                        "line_item_breakdown": line_item_breakdown
                    }, line_item_breakdown
        
        # Fallback: Check procedures list if no line items
        for proc in procedures:
            proc_name = proc.lower() if isinstance(proc, str) else proc.get("name", "").lower()
            for excluded in excluded_procedures:
                if excluded in proc_name or proc_name in excluded:
                    return {
                        "name": "procedure_coverage_dental",
                        "status": "FAIL",
                        "reason": f"Dental procedure '{proc_name}' is excluded from coverage",
                        "amount_delta": 0.0,
                    }, None
        
        # Check diagnosis for excluded procedures
        for excluded in excluded_procedures:
            if excluded in diagnosis:
                return {
                    "name": "procedure_coverage_dental",
                    "status": "FAIL",
                    "reason": f"Dental procedure '{excluded}' found in diagnosis is excluded from coverage",
                    "amount_delta": 0.0,
                }, None
    
    # Check vision procedures
    if claim_type == "VISION":
        vision_config = opd_categories.get("vision", {})
        covered_items = [p.lower() for p in vision_config.get("covered_items", [])]
        excluded_items = [p.lower() for p in vision_config.get("excluded_items", [])]
        
        # Check if any item is explicitly excluded
        for proc in procedures:
            proc_name = proc.lower() if isinstance(proc, str) else proc.get("name", "").lower()
            for excluded in excluded_items:
                if excluded in proc_name or proc_name in excluded:
                    return {
                        "name": "procedure_coverage_vision",
                        "status": "FAIL",
                        "reason": f"Vision item '{proc_name}' is excluded from coverage",
                        "amount_delta": 0.0,
                    }, None
        
        # Check diagnosis for excluded items
        for excluded in excluded_items:
            if excluded in diagnosis:
                return {
                    "name": "procedure_coverage_vision",
                    "status": "FAIL",
                    "reason": f"Vision item '{excluded}' found in diagnosis is excluded from coverage",
                    "amount_delta": 0.0,
                }, None
    
    return {
        "name": "procedure_coverage",
        "status": "PASS",
        "reason": "All procedures are covered",
        "amount_delta": 0.0,
    }, None


def _check_category_requirements(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates category-specific requirements (prescription, reports, etc.).
    """
    claim_type = claim_facts.get("claim_type", "").lower()
    opd_categories = policy.get("opd_categories", {})
    category_config = opd_categories.get(claim_type, {})
    
    # Check if category is covered
    if not category_config.get("covered", True):
        return {
            "name": "category_requirements",
            "status": "FAIL",
            "reason": f"Claim type '{claim_type}' is not covered under this policy",
            "amount_delta": 0.0,
        }
    
    # Check prescription requirement
    requires_prescription = category_config.get("requires_prescription", False)
    if requires_prescription:
        # This should be validated earlier in document presence check
        # Here we just note it passed
        pass
    
    # Check registered practitioner for alternative medicine
    if claim_type == "alternative_medicine":
        requires_registered = category_config.get("requires_registered_practitioner", False)
        if requires_registered:
            # Would need to validate practitioner registration from extracted fields
            # For now, we assume it's validated in document extraction
            pass
    
    # Check session limits for alternative medicine
    if claim_type == "alternative_medicine":
        max_sessions = category_config.get("max_sessions_per_year", 999)
        session_count_ytd = claim_facts.get("session_count_ytd", 0)
        
        if session_count_ytd >= max_sessions:
            return {
                "name": "category_requirements_sessions",
                "status": "FAIL",
                "reason": f"Maximum sessions per year ({max_sessions}) exceeded. Current: {session_count_ytd}",
                "amount_delta": 0.0,
            }
    
    return {
        "name": "category_requirements",
        "status": "PASS",
        "reason": "All category requirements met",
        "amount_delta": 0.0,
    }


def _get_member_and_family(member_id: str, policy: Dict[str, Any]) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Get member and their family members for floater calculations.
    
    Returns:
        Tuple of (member_dict, family_members_list)
    """
    members = policy.get("members", [])
    member = next((m for m in members if m.get("member_id") == member_id), None)
    
    if not member:
        return None, []
    
    # If member is SELF, get their dependents
    if member.get("relationship") == "SELF":
        primary_id = member_id
        family_members = [m for m in members if m.get("member_id") == primary_id or m.get("primary_member_id") == primary_id]
    else:
        # If member is dependent, get primary and all dependents
        primary_id = member.get("primary_member_id")
        family_members = [m for m in members if m.get("member_id") == primary_id or m.get("primary_member_id") == primary_id]
    
    return member, family_members


def _check_annual_opd_limit(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """
    Checks annual OPD limit for the member.
    Returns adjusted amount if limit would be exceeded.
    """
    member_id = claim_facts["member_id"]
    treatment_date = datetime.fromisoformat(claim_facts["treatment_date"]).date()
    
    coverage = policy.get("coverage", {})
    annual_opd_limit = float(coverage.get("annual_opd_limit", 0))
    
    if annual_opd_limit == 0:
        return {
            "name": "annual_opd_limit",
            "status": "PASS",
            "reason": "No annual OPD limit configured",
            "amount_delta": 0.0,
        }, 0.0
    
    # Get policy year start
    holder = policy.get("policy_holder", {})
    policy_start = datetime.fromisoformat(holder["policy_start_date"]).date()
    
    # Calculate current policy year start
    if treatment_date.month >= policy_start.month and treatment_date.day >= policy_start.day:
        year_start = date(treatment_date.year, policy_start.month, policy_start.day)
    else:
        year_start = date(treatment_date.year - 1, policy_start.month, policy_start.day)
    
    # Query total approved amount for member in current policy year
    total_approved = db.session.query(
        func.coalesce(func.sum(Claim.approved_amount), 0)
    ).filter(
        and_(
            Claim.member_id == member_id,
            Claim.status == "COMPLETED",
            Claim.decision.in_(["APPROVED", "PARTIAL"]),
            Claim.treatment_date >= year_start,
            Claim.treatment_date < treatment_date
        )
    ).scalar() or 0
    
    total_approved = float(total_approved)
    current_claim = float(claim_facts.get("claimed_amount", 0))
    
    remaining_limit = annual_opd_limit - total_approved
    
    if remaining_limit <= 0:
        return {
            "name": "annual_opd_limit",
            "status": "FAIL",
            "reason": f"Annual OPD limit of ₹{annual_opd_limit} exhausted. Already claimed: ₹{total_approved}",
            "amount_delta": 0.0,
        }, 0.0
    
    if current_claim > remaining_limit:
        return {
            "name": "annual_opd_limit",
            "status": "WARN",
            "reason": f"Claim amount ₹{current_claim} exceeds remaining annual limit ₹{remaining_limit}. Capping to remaining limit.",
            "amount_delta": remaining_limit - current_claim,
        }, remaining_limit
    
    return {
        "name": "annual_opd_limit",
        "status": "PASS",
        "reason": f"Within annual OPD limit. Used: ₹{total_approved} of ₹{annual_opd_limit}",
        "amount_delta": 0.0,
    }, 0.0


def _check_family_floater_limit(claim_facts: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """
    Checks family floater combined limit.
    Returns adjusted amount if limit would be exceeded.
    """
    coverage = policy.get("coverage", {})
    family_floater = coverage.get("family_floater", {})
    
    if not family_floater.get("enabled", False):
        return {
            "name": "family_floater_limit",
            "status": "PASS",
            "reason": "Family floater not enabled",
            "amount_delta": 0.0,
        }, 0.0
    
    combined_limit = float(family_floater.get("combined_limit", 0))
    if combined_limit == 0:
        return {
            "name": "family_floater_limit",
            "status": "PASS",
            "reason": "No family floater limit configured",
            "amount_delta": 0.0,
        }, 0.0
    
    member_id = claim_facts["member_id"]
    treatment_date = datetime.fromisoformat(claim_facts["treatment_date"]).date()
    
    # Get member and family
    member, family_members = _get_member_and_family(member_id, policy)
    if not member:
        return {
            "name": "family_floater_limit",
            "status": "PASS",
            "reason": "Member not found, skipping family floater check",
            "amount_delta": 0.0,
        }, 0.0
    
    family_member_ids = [m["member_id"] for m in family_members]
    
    # Get policy year start
    holder = policy.get("policy_holder", {})
    policy_start = datetime.fromisoformat(holder["policy_start_date"]).date()
    
    # Calculate current policy year start
    if treatment_date.month >= policy_start.month and treatment_date.day >= policy_start.day:
        year_start = date(treatment_date.year, policy_start.month, policy_start.day)
    else:
        year_start = date(treatment_date.year - 1, policy_start.month, policy_start.day)
    
    # Query total approved amount for family in current policy year
    total_family_approved = db.session.query(
        func.coalesce(func.sum(Claim.approved_amount), 0)
    ).filter(
        and_(
            Claim.member_id.in_(family_member_ids),
            Claim.status == "COMPLETED",
            Claim.decision.in_(["APPROVED", "PARTIAL"]),
            Claim.treatment_date >= year_start,
            Claim.treatment_date < treatment_date
        )
    ).scalar() or 0
    
    total_family_approved = float(total_family_approved)
    current_claim = float(claim_facts.get("claimed_amount", 0))
    
    remaining_limit = combined_limit - total_family_approved
    
    if remaining_limit <= 0:
        return {
            "name": "family_floater_limit",
            "status": "FAIL",
            "reason": f"Family floater limit of ₹{combined_limit} exhausted. Family already claimed: ₹{total_family_approved}",
            "amount_delta": 0.0,
        }, 0.0
    
    if current_claim > remaining_limit:
        return {
            "name": "family_floater_limit",
            "status": "WARN",
            "reason": f"Claim amount ₹{current_claim} exceeds remaining family floater limit ₹{remaining_limit}. Capping to remaining limit.",
            "amount_delta": remaining_limit - current_claim,
        }, remaining_limit
    
    return {
        "name": "family_floater_limit",
        "status": "PASS",
        "reason": f"Within family floater limit. Family used: ₹{total_family_approved} of ₹{combined_limit}",
        "amount_delta": 0.0,
    }, 0.0


def _apply_opd_sub_limits_and_copay(
    claim_facts: Dict[str, Any],
    policy: Dict[str, Any],
    approved_amount: float,
) -> Tuple[Dict[str, Any], float]:
    """
    Applies (in order):
    1. per_claim_limit check (REJECT if exceeded)
    2. OPD category sub_limit
    3. network_discount_percent (applied to amount BEFORE copay)
    4. copay_percent (patient share calculated on discounted amount)
    5. branded_drug_copay_percent for pharmacy
    
    IMPORTANT: Network discount is applied BEFORE copay, not after.
    This is the correct order per TC010.
    """
    coverage = policy.get("coverage", {})
    per_claim_limit = float(coverage.get("per_claim_limit", approved_amount))

    opd_categories = policy.get("opd_categories", {})
    claim_type = claim_facts.get("claim_type", "").lower()
    category_conf = opd_categories.get(claim_type, {})

    sub_limit = float(category_conf.get("sub_limit", approved_amount))
    copay_percent = float(category_conf.get("copay_percent", 0))
    network_discount_percent = float(category_conf.get("network_discount_percent", 0))

    per_category_amounts = claim_facts.get("per_category_amounts", {})
    category_amount = float(per_category_amounts.get(claim_type, approved_amount))

    # Apply sub_limit and per_claim_limit first
    capped_amount = min(category_amount, sub_limit, per_claim_limit)
    
    reason_parts = []
    reason_parts.append(f"Applied sub_limit ₹{sub_limit}, per_claim_limit ₹{per_claim_limit}")

    # Apply network discount FIRST (before copay) - TC010
    discounted_amount = capped_amount
    if claim_facts.get("is_network_hospital", False) and network_discount_percent > 0:
        network_discount = (network_discount_percent / 100.0) * capped_amount
        discounted_amount = capped_amount - network_discount
        reason_parts.append(f"Network discount {network_discount_percent}% applied: ₹{capped_amount:.2f} → ₹{discounted_amount:.2f}")
    
    # Calculate copay (patient share) on the discounted amount
    patient_copay = 0.0
    
    # Special handling for pharmacy - check for branded drugs
    if claim_type == "pharmacy":
        medicines = claim_facts.get("medicines", [])
        branded_drug_copay_percent = float(category_conf.get("branded_drug_copay_percent", 0))
        generic_mandatory = category_conf.get("generic_mandatory", False)
        
        # Check if any medicines are branded
        has_branded = False
        for med in medicines:
            if isinstance(med, dict):
                is_branded = med.get("is_branded", False)
                has_generic_alternative = med.get("has_generic_alternative", True)
                
                if is_branded and has_generic_alternative and generic_mandatory:
                    has_branded = True
                    break
        
        if has_branded and branded_drug_copay_percent > 0:
            patient_copay = (branded_drug_copay_percent / 100.0) * discounted_amount
            reason_parts.append(f"Branded drug copay {branded_drug_copay_percent}% applied on ₹{discounted_amount:.2f}")
        elif copay_percent > 0:
            patient_copay = (copay_percent / 100.0) * discounted_amount
            reason_parts.append(f"Standard copay {copay_percent}% applied on ₹{discounted_amount:.2f}")
    else:
        # Standard copay for other categories
        if copay_percent > 0:
            patient_copay = (copay_percent / 100.0) * discounted_amount
            reason_parts.append(f"Copay {copay_percent}% applied on ₹{discounted_amount:.2f}")
    
    # Final approved amount = discounted amount - patient copay
    final_approved = discounted_amount - patient_copay
    
    if patient_copay > 0:
        reason_parts.append(f"Patient copay: ₹{patient_copay:.2f}, Final approved: ₹{final_approved:.2f}")

    rr = {
        "name": "coverage_opd_sub_limits_copay",
        "status": "PASS",
        "reason": "; ".join(reason_parts),
        "amount_delta": float(final_approved - approved_amount),
    }

    return rr, final_approved


def _check_fraud_thresholds(
    claim_facts: Dict[str, Any],
    policy: Dict[str, Any],
) -> Tuple[Dict[str, Any], Any]:
    """
    Uses fraud_thresholds:
    - same_day_claims_limit
    - monthly_claims_limit
    - high_value_claim_threshold
    - auto_manual_review_above
    - fraud_score_manual_review_threshold
    
    Calculates fraud score from multiple signals.
    """
    fraud_cfg = policy.get("fraud_thresholds", {})

    same_day_limit = fraud_cfg.get("same_day_claims_limit", 999)
    monthly_limit = fraud_cfg.get("monthly_claims_limit", 999)
    high_value_threshold = float(fraud_cfg.get("high_value_claim_threshold", 0))
    auto_manual_review_above = float(fraud_cfg.get("auto_manual_review_above", 0))
    fraud_score_threshold = float(fraud_cfg.get("fraud_score_manual_review_threshold", 0.80))

    same_day_count = int(claim_facts.get("same_day_claims_count", 0))
    monthly_count = int(claim_facts.get("monthly_claims_count", 0))
    claimed_amount = float(claim_facts.get("claimed_amount", 0.0))

    # Calculate fraud score (0.0 to 1.0)
    fraud_score = 0.0
    fraud_signals = []
    
    # Signal 1: Excessive same-day claims (weight: 0.3)
    if same_day_count > same_day_limit:
        fraud_score += 0.3
        fraud_signals.append(f"Same-day claims ({same_day_count}) exceeds limit ({same_day_limit})")
    
    # Signal 2: Excessive monthly claims (weight: 0.2)
    if monthly_count > monthly_limit:
        fraud_score += 0.2
        fraud_signals.append(f"Monthly claims ({monthly_count}) exceeds limit ({monthly_limit})")
    
    # Signal 3: High value claim (weight: 0.15)
    if claimed_amount > high_value_threshold:
        fraud_score += 0.15
        fraud_signals.append(f"High value claim ₹{claimed_amount} exceeds threshold ₹{high_value_threshold}")
    
    # Signal 4: Document fraud indicators from OCR (weight: 0.35)
    # Check for fraud signals from extracted documents
    fraud_summary = claim_facts.get("fraud_summary", {})
    if fraud_summary:
        if fraud_summary.get("duplicate_stamp_terms"):
            fraud_score += 0.15
            fraud_signals.append("Duplicate stamps detected in documents")
        
        if fraud_summary.get("alteration_flags"):
            fraud_score += 0.10
            fraud_signals.append("Document alterations detected")
        
        if fraud_summary.get("partial_flags"):
            fraud_score += 0.05
            fraud_signals.append("Partial/incomplete documents detected")
        
        if fraud_summary.get("duplicate_pages_detected"):
            fraud_score += 0.05
            fraud_signals.append("Duplicate pages detected")
    
    # Clamp fraud score to 0.0-1.0
    fraud_score = min(1.0, fraud_score)
    
    status = "PASS"
    decision_override = None
    reason_parts = []
    
    # Check if fraud score exceeds threshold
    if fraud_score >= fraud_score_threshold:
        status = "WARN"
        decision_override = "MANUAL_REVIEW"
        reason_parts.append(f"Fraud score {fraud_score:.2f} exceeds threshold {fraud_score_threshold}")
    
    # Check if amount requires manual review
    if claimed_amount > auto_manual_review_above:
        status = "WARN"
        decision_override = "MANUAL_REVIEW"
        reason_parts.append(f"Claim amount ₹{claimed_amount} exceeds auto-manual-review threshold ₹{auto_manual_review_above}")
    
    # Add all fraud signals to reason
    if fraud_signals:
        reason_parts.extend(fraud_signals)
    
    if not reason_parts:
        reason_parts.append(f"No fraud indicators detected (fraud score: {fraud_score:.2f})")

    rr = {
        "name": "fraud_thresholds",
        "status": status,
        "reason": "; ".join(reason_parts),
        "amount_delta": 0.0,
        "fraud_score": fraud_score,
    }

    return rr, decision_override


def evaluate_claim(claim_facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main policy evaluation function with full policy coverage.
    
    Evaluation order:
    0. Policy ID validation (ensure claim matches active policy)
    1. Eligibility (member, policy status, dates, dependents)
    2. Submission rules (min amount, deadline)
    3. Per-claim limit check (EARLY - TC008)
    4. Waiting periods (initial, pre-existing, specific conditions)
    5. Pre-authorization (required tests/procedures)
    6. Exclusions (global, category-specific)
    7. Procedure coverage (dental, vision)
    8. Category requirements (prescription, sessions, etc.)
    9. Annual OPD limit (per member)
    10. Family floater limit (combined family)
    11. Coverage limits and copay (sub-limits, copay, network discount)
    12. Fraud thresholds (score calculation, manual review triggers)
    """
    policy = load_policy_terms()
    rule_results: List[Dict[str, Any]] = []

    claimed_amount = float(claim_facts["claimed_amount"])
    approved_amount = claimed_amount
    decision = "APPROVED"

    # 0) Policy ID validation (FIRST CHECK)
    rr = _validate_policy_id(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 1) Eligibility (member exists, policy active, dependents valid)
    rr = _check_eligibility(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 2) Submission rules (min amount, deadline)
    rr = _check_submission_rules(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 3) Per-claim limit check (EARLY - TC008)
    coverage = policy.get("coverage", {})
    per_claim_limit = float(coverage.get("per_claim_limit", 0))
    if per_claim_limit > 0 and claimed_amount > per_claim_limit:
        rr = {
            "name": "per_claim_limit_exceeded",
            "status": "FAIL",
            "reason": f"Claimed amount ₹{claimed_amount} exceeds per-claim limit ₹{per_claim_limit}",
            "amount_delta": 0.0,
        }
        rule_results.append(rr)
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 4) Waiting periods
    rr = _check_waiting_periods(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 5) Pre-authorization
    rr = _check_pre_authorization(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 6) Exclusions
    rr = _check_exclusions(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 7) Procedure coverage (dental, vision) - with line-item breakdown for TC006
    rr, line_item_breakdown = _check_procedure_coverage(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        response = _build_response(decision, approved_amount, rule_results)
        if line_item_breakdown:
            response["line_item_breakdown"] = line_item_breakdown
        return response
    elif rr["status"] == "PARTIAL" and line_item_breakdown:
        # Partial approval - adjust approved amount
        approved_amount = line_item_breakdown["total_approved"]
        decision = "PARTIAL"

    # 8) Category requirements (sessions, prescription, etc.)
    rr = _check_category_requirements(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)

    # 9) Annual OPD limit
    rr, capped_by_annual = _check_annual_opd_limit(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)
    
    # If annual limit caps the amount, use that
    if capped_by_annual > 0:
        approved_amount = min(approved_amount, capped_by_annual)

    # 10) Family floater limit
    rr, capped_by_floater = _check_family_floater_limit(claim_facts, policy)
    rule_results.append(rr)
    if rr["status"] == "FAIL":
        decision = "REJECTED"
        approved_amount = 0.0
        return _build_response(decision, approved_amount, rule_results)
    
    # If family floater caps the amount, use that
    if capped_by_floater > 0:
        approved_amount = min(approved_amount, capped_by_floater)

    # 11) Coverage, sub-limits, copay (per_claim_limit, category sub_limit, copay, network discount)
    rr, approved_amount = _apply_opd_sub_limits_and_copay(
        claim_facts, policy, approved_amount
    )
    rule_results.append(rr)

    # 12) Fraud thresholds (same_day, monthly, high_value, fraud score)
    rr, maybe_decision = _check_fraud_thresholds(claim_facts, policy)
    rule_results.append(rr)
    if maybe_decision is not None:
        decision = maybe_decision

    # Mark as PARTIAL if approved_amount < claimed_amount
    if decision == "APPROVED" and approved_amount < claimed_amount:
        decision = "PARTIAL"

    response = _build_response(decision, approved_amount, rule_results)
    
    # Add line-item breakdown if available (TC006)
    if line_item_breakdown:
        response["line_item_breakdown"] = line_item_breakdown
    
    return response


def _build_response(decision: str, approved_amount: float,
                    rule_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "decision": decision,
        "approved_amount": float(approved_amount),
        "rule_results": rule_results,
    }