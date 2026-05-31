import pandas as pd


def merge_list_field(page_outputs, name, key='canonical'):
    rows = []
    for p in page_outputs:
        rows.extend(p.get(name, []))
    if not rows:
        return []
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=[key]).to_dict(orient='records') if key in df.columns else rows


def build_final_doc(page_outputs, expected_tag, input_path=None):
    final = {
        'input_path': input_path,
        'expected_tag': expected_tag,
        'doc_type': page_outputs[0]['doc_type'] if page_outputs else 'UNKNOWN',
        'page_count': len(page_outputs),
        'pages': page_outputs,
        'aggregate_text': ''.join([p.get('text', '') for p in page_outputs]),
        'quality_flags': sorted(list(set(sum([p['quality']['flags'] for p in page_outputs], [])))) if page_outputs else [],
        'script_flags': sorted(list(set(sum([p.get('script_flags', []) for p in page_outputs], [])))) if page_outputs else []
    }

    for field in ['doctor_name','doctor_reg_no','specialization','address','patient_name','age','gender','date','sample_id','sample_date','report_date','bill_no','drug_license_no','gstin','nabl_status','diagnosis','pathologist_name','hospital','lab_name','pharmacy_name','subtotal','discount','net_amount','gst_amount','total_amount','remarks']:
        for p in page_outputs:
            if p.get(field) not in [None, '', [], {}]:
                final[field] = p[field]
                break

    if final['doc_type'] == 'PRESCRIPTION':
        final['medicines'] = merge_list_field(page_outputs, 'medicines', 'name')
        final['tests'] = merge_list_field(page_outputs, 'tests', 'canonical')
        final['line_items'] = []
        final['lab_rows'] = []
    elif final['doc_type'] == 'HOSPITAL_BILL':
        final['medicines'] = []
        final['tests'] = []
        final['line_items'] = merge_list_field(page_outputs, 'line_items', 'description')
        final['lab_rows'] = []
    elif final['doc_type'] == 'PHARMACY_BILL':
        final['medicines'] = merge_list_field(page_outputs, 'medicines', 'name') if any('name' in m for p in page_outputs for m in p.get('medicines', [])) else merge_list_field(page_outputs, 'line_items', 'medicine')
        final['tests'] = []
        final['line_items'] = merge_list_field(page_outputs, 'line_items', 'medicine')
        final['lab_rows'] = []
    elif final['doc_type'] == 'LAB_REPORT':
        final['medicines'] = []
        final['tests'] = merge_list_field(page_outputs, 'tests', 'name') if any('name' in t for p in page_outputs for t in p.get('tests', [])) else merge_list_field(page_outputs, 'lab_rows', 'test_name')
        final['line_items'] = []
        final['lab_rows'] = merge_list_field(page_outputs, 'lab_rows', 'test_name')
    else:
        final['medicines'] = merge_list_field(page_outputs, 'medicines', 'name')
        final['tests'] = merge_list_field(page_outputs, 'tests', 'canonical')
        final['line_items'] = []
        final['lab_rows'] = []

    final['fraud_summary'] = {
        'duplicate_stamp_terms': sorted(list(set(sum([p['fraud_checks'].get('duplicate_stamp_terms', []) for p in page_outputs], [])))) if page_outputs else [],
        'alteration_flags': sorted(list(set(sum([p['fraud_checks'].get('alteration_flags', []) for p in page_outputs], [])))) if page_outputs else [],
        'partial_flags': sorted(list(set(sum([p['fraud_checks'].get('partial_flags', []) for p in page_outputs], [])))) if page_outputs else [],
        'duplicate_pages_detected': len([p['fraud_checks']['image_fingerprint'] for p in page_outputs]) != len(set([p['fraud_checks']['image_fingerprint'] for p in page_outputs])) if page_outputs else False
    }
    if final['fraud_summary']['alteration_flags']:
        final['DOCUMENT_ALTERATION'] = True
    if final['script_flags']:
        final['regional_fields_unextracted'] = True
    return final
