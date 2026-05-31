REQUIRED_FIELDS = {
    'PRESCRIPTION': ['doctor_name', 'patient_name', 'date', 'medicines'],
    'HOSPITAL_BILL': ['hospital', 'bill_no', 'date', 'patient_name', 'line_items', 'total_amount'],
    'LAB_REPORT': ['lab_name', 'patient_name', 'sample_id', 'sample_date', 'report_date', 'tests'],
    'PHARMACY_BILL': ['pharmacy_name', 'bill_no', 'date', 'patient_name', 'medicines', 'net_amount']
}


def unwrap_value(v):
    if isinstance(v, dict) and 'value' in v:
        return v['value']
    return v


def is_present(v):
    v = unwrap_value(v)
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) > 0
    return True


def build_tag_match_result(expected_tag, inferred_tag):
    ok = str(expected_tag).upper().strip() == str(inferred_tag).upper().strip()
    return {
        'expected_tag': expected_tag,
        'inferred_doc_type': inferred_tag,
        'tag_matches': ok,
        'message': 'Document matches expected tag.' if ok else f'Document type mismatch: expected {expected_tag}, inferred {inferred_tag}.'
    }


def compute_required_field_check(doc, expected_tag):
    req = REQUIRED_FIELDS.get(expected_tag, [])
    present, missing = [], []
    for f in req:
        if is_present(doc.get(f)):
            present.append(f)
        else:
            missing.append(f)
    score = round(len(present) / max(1, len(req)), 4)
    return {
        'expected_tag': expected_tag,
        'required_fields': req,
        'present_fields': present,
        'missing_fields': missing,
        'all_required_fields_present': len(missing) == 0,
        'required_field_coverage': score
    }


def apply_validation(doc, expected_tag):
    doc['tag_validation'] = build_tag_match_result(expected_tag, doc.get('doc_type'))
    doc['required_field_validation'] = compute_required_field_check(doc, expected_tag)
    manual_review_reasons = []
    if not doc['tag_validation']['tag_matches']:
        manual_review_reasons.append(doc['tag_validation']['message'])
    if not doc['required_field_validation']['all_required_fields_present']:
        manual_review_reasons.extend([f'missing:{x}' for x in doc['required_field_validation']['missing_fields']])
    doc['manual_review'] = len(manual_review_reasons) > 0
    doc['manual_review_reasons'] = manual_review_reasons
    doc['ready_for_downstream_processing'] = not doc['manual_review']
    return doc
