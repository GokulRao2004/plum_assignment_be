from flask import Blueprint, request, jsonify

from app.policy_engine import evaluate_claim

simulate_bp = Blueprint("simulate", __name__)

@simulate_bp.route("/claims/simulate", methods=["POST"])
def simulate_claim():
    claim_facts = request.get_json()
    result = evaluate_claim(claim_facts)
    return jsonify(result), 200