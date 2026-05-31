import json
import os

_POLICY_TERMS = None

def load_policy_terms():
    global _POLICY_TERMS
    if _POLICY_TERMS is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        print('base_dir: ', base_dir)
        path = os.path.join(base_dir, "policy_terms.json")
        with open(path, "r", encoding="utf-8") as f:
            _POLICY_TERMS = json.load(f)
    return _POLICY_TERMS