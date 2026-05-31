import re
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from .loaders import get_vocabs
from .ocr_core import (
    nk, normalize_ocr_noise, expand_diagnosis_shorthand, validate_reg_no,
    run_ocr, ocr_to_lines, infer_doc_type, build_sections, detect_script_flag,
    detect_duplicate_stamps, detect_document_alteration, detect_partial_document,
    page_fingerprint, SKIP_PREFIXES, MED_HINTS, SPECIALIZATION_TERMS
)


def find_first(lines, patterns):
    for ln in lines:
        for pat in patterns:
            m = re.search(pat, normalize_ocr_noise(ln['text']), re.I)
            if m:
                return m, ln
    return None, None


def named_entity(lines, prefixes):
    for ln in lines:
        tx = normalize_ocr_noise(ln['text'])
        for p in prefixes:
            if nk(tx).startswith(nk(p)):
                val = tx.split(':', 1)[1].strip() if ':' in tx else tx[len(p):].strip()
                return {'value': val, 'confidence': round(float(ln['confidence']), 3)}
    return None


def extract_specialization(header_lines):
    matches = []
    for ln in header_lines[:8]:
        t = nk(ln['text'])
        found = [s for s in SPECIALIZATION_TERMS if s in t]
        if found:
            matches.extend(found)
    return sorted(list(set(matches)))


def extract_address(lines):
    address_lines = []
    for ln in lines[:6]:
        t = normalize_ocr_noise(ln['text'])
        if re.search(r'road|rd\b|street|st\b|nagar|layout|bengaluru|bangalore|chennai|mumbai|delhi|560\d{3}|\d{6}', t, re.I):
            address_lines.append(t)
    return ' | '.join(address_lines) if address_lines else None


def extract_gstin(lines):
    m, ln = find_first(lines, [r'\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]\b'])
    return {'value': m.group(0), 'confidence': round(float(ln['confidence']), 3)} if m else None


def extract_nabl(lines):
    for ln in lines[:8]:
        if re.search(r'nabl', ln['text'], re.I):
            return {'value': normalize_ocr_noise(ln['text']), 'confidence': round(float(ln['confidence']), 3)}
    return None


def looks_like_medicine_line(text):
    t = normalize_ocr_noise(text)
    k = nk(t)
    if len(k) < 5 or any(k.startswith(p) for p in SKIP_PREFIXES):
        return False
    if any(h in k.split() for h in MED_HINTS):
        return True
    if re.search(r'\b\d+(?:\.\d+)?\s*(mg|mcg|ml|g|gm|iu|units?)\b', t, re.I):
        return True
    if re.search(r'\b(OD|BD|TDS|QID|SOS|PRN|HS|AC|PC)\b|\b\d-\d-\d\b', t, re.I):
        return True
    if re.search(r'^\d+[.)]', t):
        return True
    return False


def best_rxnorm_match(text, threshold_main=90, threshold_loose=86):
    rx_df, _, _ = get_vocabs()
    raw = normalize_ocr_noise(text)
    key = nk(raw)
    if not key or len(key) < 5 or not looks_like_medicine_line(raw):
        return None
    core = re.sub(r'^\d+[.)]\s*', '', raw)
    core = re.sub(r'\b(tab|tablet|cap|capsule|syp|syrup|inj|injection|cream|ointment|gel|drops|lotion|spray)\b', ' ', core, flags=re.I)
    core = re.sub(r'\b(od|bd|tds|qid|sos|prn|hs|ac|pc)\b', ' ', core, flags=re.I)
    core = re.sub(r'\b\d-\d-\d\b', ' ', core)
    core = re.sub(r'\bx\s*\d+\s*(days?|weeks?|months?)\b', ' ', core, flags=re.I)
    core_key = nk(core) or key
    candidates = rx_df['STR_NORM'].tolist()
    scorer = fuzz.WRatio if len(core_key.split()) <= 3 else fuzz.token_set_ratio
    result = process.extractOne(core_key, candidates, scorer=scorer)
    if not result:
        return None
    threshold = threshold_loose if re.search(r'\b\d+(?:\.\d+)?\s*(mg|mcg|ml|g|gm|iu)\b', raw, re.I) else threshold_main
    if result[1] < threshold:
        return None
    row = rx_df.iloc[result[2]]
    overlap = set(core_key.split()).intersection(set(str(row['STR_NORM']).split()))
    if len(overlap) == 0:
        return None
    return {'canonical': row['STR'], 'rxcui': row['RXCUI'], 'tty': row['TTY'], 'sab': row['SAB'], 'score': float(result[1]), 'method': 'rxnorm_safe_fuzzy', 'core_query': core_key}


def best_vocab_match(text, vocab_df, threshold=78, label='vocab'):
    raw = expand_diagnosis_shorthand(normalize_ocr_noise(text)) if label == 'diagnosis' else normalize_ocr_noise(text)
    key = nk(raw)
    if not key or vocab_df.empty:
        return None
    candidates = vocab_df['alias_norm'].tolist()
    scorer = fuzz.WRatio if len(key.split()) <= 3 else fuzz.token_set_ratio
    result = process.extractOne(key, candidates, scorer=scorer)
    if not result or result[1] < threshold:
        return None
    row = vocab_df.iloc[result[2]]
    return {'canonical': row['canonical'], 'code': row['code'], 'alias': row['alias'], 'score': float(result[1]), 'method': f'{label}_safe_fuzzy'}


def parse_hospital_bill_rows(lines):
    """
    Robust parser for hospital bill line items.

    Handles layouts where DESCRIPTION / QTY / RATE / AMOUNT appear in a header row,
    and then the numeric values and descriptions are split across multiple lines
    (typical EasyOCR output).

    Returns a list of dicts: {description, qty, rate, amount}.
    """

    # 1) Identify table region boundaries: header row, then stop at footer
    header_idx = None
    footer_idx = len(lines)

    header_pattern = re.compile(r"description", re.I)
    footer_patterns = re.compile(
        r"subtotal|total amount|gst|payment mode|amount paid|balance",
        re.I,
    )

    for i, ln in enumerate(lines):
        t = normalize_ocr_noise(ln["text"])
        if header_idx is None and header_pattern.search(t):
            header_idx = i
            continue
        if header_idx is not None and footer_patterns.search(t):
            footer_idx = i
            break

    # If no recognizable header, bail out (let doc-level validation catch missing line_items)
    if header_idx is None:
        return []

    body = lines[header_idx + 1:footer_idx]

    # 2) Classify lines in body as numeric-only vs description
    numeric_lines = []   # (index_in_body, numeric_value)
    desc_lines = []      # (index_in_body, cleaned_text)

    # Strict numeric pattern: full line is something like 500 or 500.00
    num_pat = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")

    for idx, ln in enumerate(body):
        t = normalize_ocr_noise(ln["text"]).strip()
        if not t:
            continue
        if num_pat.match(t):
            try:
                numeric_lines.append((idx, float(t)))
            except Exception:
                # If float conversion fails, treat as description
                desc_lines.append((idx, t))
        else:
            desc_lines.append((idx, t))

    if not numeric_lines or not desc_lines:
        return []

    # 3) Pair numeric pairs with nearby description lines
    items = []
    used_numeric_idx = set()

    def find_nearest_desc(i1, i2):
        """
        Find a description line whose index is between i1 and i2,
        or, if none, the closest one in terms of index distance.
        """
        if not desc_lines:
            return None
        candidates = []
        for di, txt in desc_lines:
            # Prefer descriptions between the two numeric indices
            if i1 <= di <= i2 or i2 <= di <= i1:
                # Distance 0 means inside [i1, i2]
                candidates.append((0, di, txt))
            else:
                # Distance to closest numeric index
                d = min(abs(di - i1), abs(di - i2))
                candidates.append((d, di, txt))
        # Sort by (distance, index) to ensure deterministic choice
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][1], candidates[0][2]

    i = 0
    while i < len(numeric_lines) - 1:
        idx1, v1 = numeric_lines[i]
        idx2, v2 = numeric_lines[i + 1]

        # Skip if already used in another pair
        if idx1 in used_numeric_idx or idx2 in used_numeric_idx:
            i += 1
            continue

        desc_info = find_nearest_desc(idx1, idx2)
        if not desc_info:
            i += 1
            continue

        desc_idx, desc_txt = desc_info

        # Filter out obvious footer-like descriptions accidentally captured
        if re.search(r"subtotal|total amount|gst|payment mode", desc_txt, re.I):
            i += 1
            continue

        # Build the item (assume qty=1 if not explicitly present)
        items.append(
            {
                "description": desc_txt,
                "qty": 1,
                "rate": v1,
                "amount": v2,
            }
        )

        used_numeric_idx.add(idx1)
        used_numeric_idx.add(idx2)
        i += 2

    return items


def parse_pharmacy_rows(lines):
    """
    Robust parser for pharmacy bill line items.

    Handles layouts where there is a header like:
        BATCH
        MEDICINE
        EXP QTY MRP AMT

    and each item is represented as:
        <medicine name>
        <BATCH> <EXP> <QTY> <MRP> <AMOUNT>

    Returns list of dicts:
        {
            "medicine": str,
            "batch": str or None,
            "expiry": str or None,
            "qty": int or None,
            "mrp": float or None,
            "amount": float or None,
        }
    """

    # 1) Identify table region (header -> footer)
    header_idx = None
    footer_idx = len(lines)

    # Look for the composite header: EXP QTY MRP AMT
    header_pattern = re.compile(r"\bEXP\b.*\bMRP\b.*\bAMT\b", re.I)
    footer_patterns = re.compile(
        r"subtotal|net amount|payment mode|gst|total amount|amount paid|balance",
        re.I,
    )

    for i, ln in enumerate(lines):
        t = normalize_ocr_noise(ln["text"])
        if header_idx is None and header_pattern.search(t):
            header_idx = i
            continue
        if header_idx is not None and footer_patterns.search(t):
            footer_idx = i
            break

    # If we didn't find the EXP/QTY/MRP/AMT header, bail out
    if header_idx is None:
        return []

    body = lines[header_idx + 1:footer_idx]

    # 2) Walk the body as (name_line, detail_line) pairs
    items = []

    # Pattern for detail line: BATCH EXP QTY MRP AMT
    # Example: "B7821 06/26 13 5.50 71.50"
    detail_pat = re.compile(
        r"""
        ^\s*
        (?P<batch>[A-Z0-9]{3,10})        # batch code, e.g. B7821
        \s+
        (?P<exp>\d{2}/\d{2,4})          # expiry MM/YY or MM/YYYY
        \s+
        (?P<qty>\d{1,4})                # quantity
        \s+
        (?P<mrp>\d+(?:\.\d{1,2})?)      # MRP
        \s+
        (?P<amt>\d+(?:\.\d{1,2})?)      # amount
        \s*$
        """,
        re.VERBOSE,
    )

    i = 0
    while i < len(body):
        # Expect medicine name on line i, detail on line i+1
        name_line = body[i]
        name_text = normalize_ocr_noise(name_line["text"]).strip()

        if not name_text:
            i += 1
            continue

        # No detail line => we can't parse this item
        if i + 1 >= len(body):
            break

        detail_line = body[i + 1]
        detail_text = normalize_ocr_noise(detail_line["text"]).strip()

        m = detail_pat.match(detail_text)
        if not m:
            # If the detail line doesn't match, skip this pair
            i += 1
            continue

        batch = m.group("batch")
        exp = m.group("exp")

        qty_str = m.group("qty")
        mrp_str = m.group("mrp")
        amt_str = m.group("amt")

        qty = int(qty_str) if qty_str is not None else None
        try:
            mrp = float(mrp_str) if mrp_str is not None else None
        except Exception:
            mrp = None
        try:
            amt = float(amt_str) if amt_str is not None else None
        except Exception:
            amt = None

        items.append(
            {
                "medicine": name_text,
                "batch": batch,
                "expiry": exp,
                "qty": qty,
                "mrp": mrp,
                "amount": amt,
            }
        )

        # consume name + detail
        i += 2

    return items


def parse_lab_rows(lines):
    rows = []
    for ln in lines:
        t = normalize_ocr_noise(ln['text'])
        if re.search(r'test name|normal range|sample id|report date|remarks|pathology', t, re.I):
            continue
        m = re.match(r'(.+?)\s+([A-Za-z0-9,./+-]+)\s+([/%A-Za-zμdL]+)\s+([0-9.,\-– ]+)$', t)
        if m:
            rows.append({'test_name': m.group(1).strip(), 'result': m.group(2), 'unit': m.group(3), 'normal_range': m.group(4).strip()})
        elif re.search(r'negative|positive|reactive|non reactive', t, re.I):
            parts = re.split(r'\s{2,}|\t', t)
            if len(parts) >= 2:
                rows.append({'test_name': parts[0].strip(), 'result': parts[1].strip(), 'unit': '', 'normal_range': ''})
    return rows


def parse_dosage(text):
    t = normalize_ocr_noise(text)
    for pat in [r'\b\d-\d-\d\b', r'\b\d-\d\b', r'\bSOS\b', r'\bPRN\b', r'\bOD\b', r'\bBD\b', r'\bTDS\b', r'\bQID\b', r'\bHS\b', r'\bAC\b', r'\bPC\b']:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(0).upper()
    return None


def parse_duration_days(text):
    t = normalize_ocr_noise(text)
    for pat, mult in [(r'\bx\s*(\d+)\s*(day|days)\b', 1), (r'\bfor\s*(\d+)\s*(day|days)\b', 1), (r'\bx\s*(\d+)\s*(week|weeks)\b', 7), (r'\bfor\s*(\d+)\s*(week|weeks)\b', 7), (r'\bx\s*(\d+)\s*(month|months)\b', 30), (r'\bfor\s*(\d+)\s*(month|months)\b', 30)]:
        m = re.search(pat, t, re.I)
        if m:
            return int(m.group(1)) * mult
    return None


def parse_note(text):
    t = normalize_ocr_noise(text)
    found = []
    for pat in [r'\bafter food\b', r'\bbefore food\b', r'\bafter meals\b', r'\bbefore meals\b', r'\bat bedtime\b', r'\bif fever persists\b', r'\bif pain persists\b', r'\bas needed\b', r'\bwhen necessary\b']:
        m = re.search(pat, t, re.I)
        if m:
            found.append(m.group(0).strip().lower())
    return ' | '.join(dict.fromkeys(found)) if found else None


def clean_medicine_name(raw_line, canonical=None):
    base = normalize_ocr_noise(canonical or raw_line)
    base = re.sub(r'^\d+[.)]\s*', '', base)
    base = re.sub(r'\b(tab|tablet|cap|capsule|syp|syrup|inj|injection|cream|ointment|gel|drops|lotion|spray)\b', '', base, flags=re.I)
    base = re.sub(r'\b(SOS|PRN|OD|BD|TDS|QID|HS|AC|PC)\b', '', base, flags=re.I)
    base = re.sub(r'\b\d-\d-\d\b', '', base)
    base = re.sub(r'\b\d-\d\b', '', base)
    base = re.sub(r'\bx\s*\d+\s*(day|days|week|weeks|month|months)\b', '', base, flags=re.I)
    base = re.sub(r'\bfor\s*\d+\s*(day|days|week|weeks|month|months)\b', '', base, flags=re.I)
    base = re.sub(r'\bafter food\b|\bbefore food\b|\bafter meals\b|\bbefore meals\b|\bat bedtime\b|\bif fever persists\b|\bif pain persists\b|\bas needed\b|\bwhen necessary\b', '', base, flags=re.I)
    base = re.sub(r'\s+', ' ', base).strip(' -,:;')
    return base


def extract_page_data(page_path, page_no=1, doc_type_override='AUTO', ocr_mode='AUTO'):
    _, diag_df, lab_df = get_vocabs()
    img_bgr, angle, quality, ocr_mode_used, raw_results = run_ocr(page_path, ocr_mode=ocr_mode)
    lines = ocr_to_lines(raw_results)
    inferred_type = infer_doc_type(lines) if doc_type_override == 'AUTO' else doc_type_override
    sections = build_sections(lines)
    header_lines = sections['header'] + sections['other']

    extracted = {
        'page_no': page_no,
        'doc_type': inferred_type,
        'text': ''.join([normalize_ocr_noise(x['text']) for x in lines]),
        'ocr_engine': ocr_mode_used,
        'confidence': round(float(np.mean([x['confidence'] for x in lines])) if lines else 0.0, 4),
        'quality': {**quality, 'deskew_angle': round(angle, 2)},
        'script_flags': sorted(list(set([s for s in [detect_script_flag(x['text']) for x in lines] if s]))),
        'fraud_checks': {
            'duplicate_stamp_terms': detect_duplicate_stamps(lines),
            'alteration_flags': detect_document_alteration(lines),
            'partial_flags': detect_partial_document(lines, img_bgr.shape),
            'image_fingerprint': page_fingerprint(page_path)
        }
    }

    for ln in header_lines[:10]:
        tx = normalize_ocr_noise(ln['text'])
        if 'dr.' in tx.lower() or tx.lower().startswith('dr '):
            extracted['doctor_name'] = {'value': tx.split('|')[0].strip(), 'confidence': round(float(ln['confidence']), 3)}
            break

    for ln in lines:
        reg = validate_reg_no(ln['text'])
        if reg:
            extracted['doctor_reg_no'] = reg
            break

    specs = extract_specialization(header_lines)
    if specs:
        extracted['specialization'] = specs
    addr = extract_address(header_lines)
    if addr:
        extracted['address'] = addr
    gst = extract_gstin(lines)
    if gst:
        extracted['gstin'] = gst
    nabl = extract_nabl(lines)
    if nabl:
        extracted['nabl_status'] = nabl

    for field, prefixes in [('patient_name', ['Patient Name','Patient','Pt','Name']), ('date', ['Date']), ('sample_id', ['Sample ID','Sample No','Accession']), ('bill_no', ['Bill No','Invoice']), ('drug_license_no', ['Drug Lic','DL No'])]:
        val = named_entity(lines, prefixes)
        if val and field not in extracted:
            extracted[field] = val

    m, ln = find_first(lines, [r'Age[:\s]+(\d{1,3})', r'Age/Gender[:\s]+(\d{1,3})'])
    if m:
        extracted['age'] = {'value': int(m.group(1)), 'confidence': round(float(ln['confidence']), 3)}
    m, ln = find_first(lines, [r'\b(Male|Female|M|F)\b'])
    if m:
        g = m.group(1)
        extracted['gender'] = {'value': 'Male' if g.upper() == 'M' else 'Female' if g.upper() == 'F' else g, 'confidence': round(float(ln['confidence']), 3)}

    date_patterns = [r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})\b', r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s./-]+\d{1,2}[\s.,-]+\d{2,4})\b']
    date_labels = [(r'(sample\s*date|collection\s*date|collected\s*on)', 'sample_date'), (r'(report\s*date|reported\s*on|report\s*generated)', 'report_date'), (r'(date\s*of\s*birth|dob)', 'dob'), (r'(date)', 'date')]
    for ln in lines:
        tx = normalize_ocr_noise(ln['text'])
        tx_lower = tx.lower()
        for label_pat, field_name in date_labels:
            if re.search(label_pat, tx_lower):
                for dpat in date_patterns:
                    dm = re.search(dpat, tx, re.I)
                    if dm:
                        if field_name not in extracted:
                            extracted[field_name] = {'value': dm.group(1), 'confidence': round(float(ln['confidence']), 3)}
                        break
    if inferred_type == 'LAB_REPORT':
        for ln in lines:
            tx = normalize_ocr_noise(ln['text'])
            for dpat in date_patterns:
                dm = re.search(dpat, tx, re.I)
                if dm:
                    if 'sample_date' not in extracted:
                        extracted['sample_date'] = {'value': dm.group(1), 'confidence': round(float(ln['confidence']), 3)}
                    elif 'report_date' not in extracted:
                        extracted['report_date'] = {'value': dm.group(1), 'confidence': round(float(ln['confidence']), 3)}
                    if 'sample_date' in extracted and 'report_date' in extracted:
                        break
            if 'sample_date' in extracted and 'report_date' in extracted:
                break

    dx_hits = []
    for ln in sections['diagnosis']:
        dv = best_vocab_match(ln['text'], diag_df, threshold=72, label='diagnosis')
        if dv:
            dx_hits.append({'raw_line': normalize_ocr_noise(ln['text']), 'canonical': dv['canonical'], 'code': dv['code'], 'match_score': dv['score'], 'match_method': dv['method'], 'confidence': round(float(ln['confidence']), 3)})
    if dx_hits:
        extracted['diagnosis'] = sorted(dx_hits, key=lambda z: (z['match_score'], z['confidence']), reverse=True)[0]
    elif sections['diagnosis']:
        extracted['diagnosis_raw'] = ' | '.join([expand_diagnosis_shorthand(x['text']) for x in sections['diagnosis']])

    meds = []
    med_lines = sections['rx'] if sections['rx'] else lines
    for idx, ln in enumerate(med_lines, 1):
        raw = normalize_ocr_noise(ln['text'])
        rx = best_rxnorm_match(raw)
        if rx:
            meds.append({'name': clean_medicine_name(raw, rx['canonical']), 'dosage': parse_dosage(raw), 'duration_days': parse_duration_days(raw), 'note': parse_note(raw), 'raw_line': raw, 'confidence': round(float(ln['confidence']), 3), 'line_index': idx, 'match_source': 'rxnorm', 'canonical': rx['canonical'], 'rxcui': rx['rxcui'], 'match_score': rx['score']})
    extracted['medicines'] = pd.DataFrame(meds).drop_duplicates(subset=['name', 'raw_line']).to_dict(orient='records') if meds else []

    tests = []
    for ln in sections['tests']:
        for piece in re.split(r',|/|;|\band\b', normalize_ocr_noise(ln['text']), flags=re.I):
            piece = piece.strip()
            if not piece:
                continue
            tv = best_vocab_match(piece, lab_df, threshold=72, label='lab')
            if tv:
                tests.append({'raw_line': piece, 'canonical': tv['canonical'], 'code': tv['code'], 'match_score': tv['score'], 'match_method': tv['method'], 'confidence': round(float(ln['confidence']), 3)})
    extracted['tests'] = pd.DataFrame(tests).sort_values(['match_score', 'confidence'], ascending=False).drop_duplicates(subset=['canonical']).to_dict(orient='records') if tests else []

    if inferred_type == 'HOSPITAL_BILL':
        extracted['line_items'] = parse_hospital_bill_rows(lines)
        m, _ = find_first(lines, [r'Subtotal[:\s]+([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['subtotal'] = float(m.group(1).replace(',', '')) if m else None
        m, _ = find_first(lines, [r'GST[^0-9]*([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['gst_amount'] = float(m.group(1).replace(',', '')) if m else None
        m, _ = find_first(lines, [r'Total Amount[:\s]+([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['total_amount'] = float(m.group(1).replace(',', '')) if m else None
        extracted['hospital'] = extracted.get('address') or (normalize_ocr_noise(lines[0]['text']) if lines else None)

    if inferred_type == 'PHARMACY_BILL':
        extracted['line_items'] = parse_pharmacy_rows(lines)
        m, _ = find_first(lines, [r'Subtotal[:\s]+([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['subtotal'] = float(m.group(1).replace(',', '')) if m else None
        m, _ = find_first(lines, [r'Discount[^0-9-]*-?([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['discount'] = float(m.group(1).replace(',', '')) if m else None
        m, _ = find_first(lines, [r'Net Amount[:\s]+([0-9,]+(?:\.[0-9]{1,2})?)'])
        extracted['net_amount'] = float(m.group(1).replace(',', '')) if m else None
        extracted['pharmacy_name'] = extracted.get('address') or (normalize_ocr_noise(lines[0]['text']) if lines else None)
        if not extracted.get('medicines') and extracted.get('line_items'):
            extracted['medicines'] = extracted['line_items']

    if inferred_type == 'LAB_REPORT':
        extracted['lab_rows'] = parse_lab_rows(lines)
        remarks = [normalize_ocr_noise(x['text']) for x in lines if re.search(r'remarks|clinical correlation', x['text'], re.I)]
        if remarks:
            extracted['remarks'] = remarks
        for ln in lines[::-1]:
            if 'dr.' in ln['text'].lower():
                extracted['pathologist_name'] = {'value': normalize_ocr_noise(ln['text']), 'confidence': round(float(ln['confidence']), 3)}
                break
        extracted['lab_name'] = extracted.get('nabl_status') or (normalize_ocr_noise(lines[0]['text']) if lines else None)
        if not extracted.get('tests') and extracted.get('lab_rows'):
            extracted['tests'] = [{'name': r.get('test_name'), 'result': r.get('result'), 'unit': r.get('unit'), 'range': r.get('normal_range')} for r in extracted.get('lab_rows', [])]

    if extracted['script_flags']:
        extracted['regional_fields_unextracted'] = True

    return extracted, lines
