from pathlib import Path
from collections import Counter
import re
import cv2
import fitz
import easyocr
import numpy as np
from PIL import Image
import imagehash

try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception:
    PADDLE_AVAILABLE = False

_easy_reader = None
_paddle_reader = None

SKIP_PREFIXES = ['age','gender','date','diagnosis','patient','chief complaint','follow-up','follow up','signed','name','ph','phone','hospital','investigations','advice','address','reg no','registration','doctor','page','bill to']
MED_HINTS = ['tab','tablet','cap','capsule','syp','syrup','inj','injection','cream','ointment','gel','drops','drop','lotion','spray']
STAMP_TERMS = ['original','duplicate','paid','cash','cancelled','received']
SPECIALIZATION_TERMS = ['mbbs','md','ms','dm','mch','dnb','internal medicine','dermatology','pathology','pediatrics','paediatrics','orthopedics','orthopaedics','gynaecology','ent','cardiology','neurology','psychiatry','general medicine']
DIAGNOSIS_SHORTHAND = {
    'htn': 'Hypertension', 'hbp': 'Hypertension', 't2dm': 'Type 2 Diabetes', 't1dm': 'Type 1 Diabetes',
    'dm': 'Diabetes Mellitus', 'gerd': 'GERD', 'uti': 'UTI', 'uri': 'URTI', 'copd': 'COPD Exacerbation',
    'oa': 'Osteoarthritis', 'ra': 'Rheumatoid Arthritis', 'cap': 'Community Acquired Pneumonia',
    'lbp': 'Back Pain', 'migraine': 'Migraine', 'ibs': 'IBS', 'pud': 'Peptic Ulcer Disease', 'hypothy': 'Hypothyroidism'
}
REG_PATTERNS = {
    'KA': r'KA/\d{4,6}/\d{4}', 'MH': r'MH/\d{4,6}/\d{4}', 'DL': r'DL/\d{4,6}/\d{4}',
    'TN': r'TN/\d{4,6}/\d{4}', 'GJ': r'GJ/\d{4,6}/\d{4}', 'AP': r'AP/\d{4,6}/\d{4}',
    'UP': r'UP/\d{4,6}/\d{4}', 'WB': r'WB/\d{4,6}/\d{4}', 'KL': r'KL/\d{4,6}/\d{4}',
    'AYUR': r'AYUR/[A-Z]{2}/\d{3,6}/\d{4}'
}
SECTION_PATTERNS = {
    'diagnosis': [r'^diagnosis[:\s]*$', r'^dx[:\s]*$', r'^impression[:\s]*$'],
    'rx': [r'^rx[:\s]*$', r'^treatment[:\s]*$', r'^medicines?[:\s]*$'],
    'tests': [r'^investigations?[:\s]*$', r'^tests? advised[:\s]*$', r'^labs?[:\s]*$'],
    'followup': [r'^follow[- ]?up[:\s]*$', r'^advice[:\s]*$']
}


def get_readers():
    global _easy_reader, _paddle_reader
    if _easy_reader is None:
        _easy_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    if _paddle_reader is None and PADDLE_AVAILABLE:
        try:
            _paddle_reader = PaddleOCR(use_angle_cls=True, lang='en')
        except Exception:
            _paddle_reader = None
    return _easy_reader, _paddle_reader


def nk(x):
    return re.sub(r'[^a-z0-9]+', ' ', str(x or '').lower()).strip()


def normalize_ocr_noise(text):
    text = str(text or '')
    text = text.replace('–', '-').replace('—', '-')
    text = re.sub(r'(?<=\d)[oO](?=\d|\s*(mg|mcg|ml|g|gm|iu|rs))', '0', text)
    text = re.sub(r'(?<=\d)[lI](?=\d)', '1', text)
    text = re.sub(r'\b1X\b', 'x', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def expand_diagnosis_shorthand(text):
    tokens = nk(text).split()
    expanded = [DIAGNOSIS_SHORTHAND.get(t, t) for t in tokens]
    return ' '.join(expanded).strip()


def validate_reg_no(text):
    t = normalize_ocr_noise(text)
    for state, pat in REG_PATTERNS.items():
        m = re.search(pat, t)
        if m:
            return {'value': m.group(0), 'state': state, 'valid_format': True}
    generic = re.search(r'[A-Z]{2}/\d{4,6}/\d{4}', t)
    if generic:
        return {'value': generic.group(0), 'state': generic.group(0).split('/')[0], 'valid_format': False}
    return None


def render_pdf_pages(pdf_path, out_dir=None, dpi=220):
    pages = []
    out_dir = Path(out_dir or Path(pdf_path).parent / 'rendered_pages')
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        out = out_dir / f'page_{i+1:03d}.png'
        pix.save(str(out))
        pages.append(str(out))
    return pages


def detect_script_flag(text):
    if re.search(r'[ऀ-ॿ]', text): return 'DEVANAGARI'
    if re.search(r'[஀-௿]', text): return 'TAMIL'
    if re.search(r'[ఀ-౿]', text): return 'TELUGU'
    if re.search(r'[ಀ-೿]', text): return 'KANNADA'
    return None


def estimate_quality_flags(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    edges = cv2.Canny(gray, 100, 200)
    edge_density = float(np.mean(edges > 0))
    flags = []
    if brightness < 70: flags.append('LOW_BRIGHTNESS')
    if contrast < 35: flags.append('LOW_CONTRAST')
    if edge_density < 0.01: flags.append('BLUR_OR_LOW_TEXT_DENSITY')
    return {'brightness': round(brightness, 2), 'contrast': round(contrast, 2), 'edge_density': round(edge_density, 4), 'flags': flags}


def deskew_image(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    inv = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inv > 0))
    if len(coords) < 50:
        return img_bgr, 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) > 20:
        return img_bgr, 0.0
    h, w = img_bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(img_bgr, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, float(angle)


def preprocess_for_ocr(img_bgr):
    rot, angle = deskew_image(img_bgr)
    gray = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    denoise = cv2.fastNlMeansDenoising(clahe, None, 8, 7, 21)
    denoise_bgr = cv2.cvtColor(denoise, cv2.COLOR_GRAY2BGR)
    denoise_rgb = cv2.cvtColor(denoise_bgr, cv2.COLOR_BGR2RGB)
    return denoise, denoise_bgr, denoise_rgb, angle


def normalize_paddle_output(res):
    raw_results = []
    if res is None:
        return raw_results
    for page in res:
        if page is None:
            continue
        if isinstance(page, dict):
            data = page.get('res', page)
            polys = data.get('dt_polys') or data.get('rec_polys') or data.get('rec_boxes')
            texts = data.get('rec_texts')
            scores = data.get('rec_scores')
            if polys is not None and texts is not None and scores is not None:
                for box, text, score in zip(polys, texts, scores):
                    raw_results.append((box.tolist() if hasattr(box, 'tolist') else box, str(text), float(score)))
                continue
        if isinstance(page, list):
            for item in page:
                if item is None:
                    continue
                if isinstance(item, (list, tuple)):
                    if len(item) == 2:
                        box, txt = item
                        if isinstance(txt, (list, tuple)) and len(txt) >= 2:
                            raw_results.append((box, str(txt[0]), float(txt[1])))
                        else:
                            raw_results.append((box, str(txt), 0.0))
                    elif len(item) >= 3:
                        box = item[0]
                        text = item[1]
                        score = item[2]
                        if isinstance(text, (list, tuple)) and len(text) >= 1:
                            text = text[0]
                        if isinstance(score, (list, tuple)) and len(score) >= 1:
                            score = score[0]
                        try:
                            score = float(score)
                        except Exception:
                            score = 0.0
                        raw_results.append((box, str(text), score))
    return raw_results


def choose_ocr_mode(quality, ocr_mode='AUTO'):
    _, paddle_reader = get_readers()
    if ocr_mode in ['EASYOCR', 'PADDLE']:
        return ocr_mode
    hard = ('LOW_CONTRAST' in quality['flags']) or ('BLUR_OR_LOW_TEXT_DENSITY' in quality['flags'])
    if hard and paddle_reader is not None:
        return 'PADDLE'
    return 'EASYOCR'


def run_ocr(page_path, ocr_mode='AUTO'):
    easy_reader, paddle_reader = get_readers()
    img_bgr = cv2.imread(page_path)
    assert img_bgr is not None, f'Could not read {page_path}'
    quality = estimate_quality_flags(img_bgr)
    ocr_gray, ocr_bgr, ocr_rgb, angle = preprocess_for_ocr(img_bgr)
    mode = choose_ocr_mode(quality, ocr_mode=ocr_mode)
    if mode == 'PADDLE' and paddle_reader is not None:
        try:
            res = paddle_reader.ocr(ocr_rgb, cls=True)
            raw_results = normalize_paddle_output(res)
            if not raw_results:
                mode = 'EASYOCR'
                raw_results = easy_reader.readtext(ocr_gray)
        except Exception:
            mode = 'EASYOCR'
            raw_results = easy_reader.readtext(ocr_gray)
    else:
        mode = 'EASYOCR'
        raw_results = easy_reader.readtext(ocr_gray)
    return img_bgr, angle, quality, mode, raw_results


def ocr_to_lines(results, y_tol=16):
    words = []
    for box, text, conf in results:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append({'text': normalize_ocr_noise(text), 'confidence': float(conf), 'x1': float(min(xs)), 'y1': float(min(ys)), 'x2': float(max(xs)), 'y2': float(max(ys))})
    words = sorted(words, key=lambda r: (r['y1'], r['x1']))
    grouped, current, anchor = [], [], None
    for w in words:
        if anchor is None or abs(w['y1'] - anchor) <= y_tol:
            current.append(w)
        else:
            grouped.append(sorted(current, key=lambda r: r['x1']))
            current = [w]
        anchor = w['y1'] if anchor is None else (anchor + w['y1']) / 2
    if current:
        grouped.append(sorted(current, key=lambda r: r['x1']))
    lines = []
    for row in grouped:
        txt = ' '.join(r['text'] for r in row).strip()
        lines.append({'text': txt, 'confidence': float(np.mean([r['confidence'] for r in row])), 'x1': min(r['x1'] for r in row), 'y1': min(r['y1'] for r in row), 'x2': max(r['x2'] for r in row), 'y2': max(r['y2'] for r in row), 'parts': row})
    return lines


def infer_doc_type(lines):
    txt = ' '.join(normalize_ocr_noise(x['text']).lower() for x in lines)
    scores = Counter()
    if 'rx' in txt or 'chief complaint' in txt or 'diagnosis' in txt: scores['PRESCRIPTION'] += 3
    if 'bill no' in txt or 'invoice' in txt or 'payment mode' in txt or 'subtotal' in txt: scores['HOSPITAL_BILL'] += 3
    if 'drug lic' in txt or 'net amount' in txt or 'pharmacy' in txt or 'mrp' in txt or 'batch' in txt: scores['PHARMACY_BILL'] += 3
    if 'sample id' in txt or 'reference range' in txt or 'lab report' in txt or 'haemoglobin' in txt or 'normal range' in txt: scores['LAB_REPORT'] += 3
    return scores.most_common(1)[0][0] if scores else 'PRESCRIPTION'


def detect_section(line_text):
    t = nk(line_text)
    for section, patterns in SECTION_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t, re.I):
                return section
    return None


def split_inline_section(line_text):
    raw = normalize_ocr_noise(line_text)
    for label in ['Diagnosis', 'Dx', 'Impression', 'Rx', 'Treatment', 'Medicines', 'Investigations', 'Investigation', 'Tests Advised', 'Labs', 'Follow-up', 'Follow up', 'Advice']:
        m = re.match(rf'^{label}[:\s]+(.+)$', raw, flags=re.I)
        if m:
            return label.lower(), m.group(1).strip()
    return None, None


def build_sections(lines):
    sections = {'header': [], 'diagnosis': [], 'rx': [], 'tests': [], 'followup': [], 'other': []}
    current = 'header'
    for ln in lines:
        txt = normalize_ocr_noise(ln['text'])
        sec = detect_section(txt)
        if sec:
            current = sec
            continue
        inline_key, inline_val = split_inline_section(txt)
        if inline_key:
            target = 'diagnosis' if inline_key in ['diagnosis', 'dx', 'impression'] else 'rx' if inline_key in ['rx', 'treatment', 'medicines'] else 'tests' if inline_key.startswith('investigation') or inline_key.startswith('tests') or inline_key == 'labs' else 'followup'
            new_ln = dict(ln)
            new_ln['text'] = inline_val
            sections[target].append(new_ln)
            current = target
            continue
        sections[current if current in sections else 'other'].append(ln)
    return sections


def page_fingerprint(page_path):
    return str(imagehash.phash(Image.open(page_path).convert('RGB')))


def detect_duplicate_stamps(lines):
    hits = []
    for ln in lines:
        t = nk(ln['text'])
        for s in STAMP_TERMS:
            if s in t:
                hits.append(s.upper())
    counts = Counter(hits)
    return [k for k, v in counts.items() if v >= 2]


def detect_document_alteration(lines):
    text = ' '.join(normalize_ocr_noise(x['text']).lower() for x in lines)
    cues = []
    if re.search(r'corrected|revised|overwritten|rewritten', text):
        cues.append('TEXTUAL_CORRECTION_CUE')
    if len(re.findall(r'\b(total|amount|net amount|subtotal)\b', text)) >= 2:
        cues.append('MULTIPLE_AMOUNT_MENTIONS')
    return cues


def detect_partial_document(lines, image_shape):
    h, w = image_shape[:2]
    if not lines:
        return ['EMPTY_PAGE']
    xs = [x['x1'] for x in lines] + [x['x2'] for x in lines]
    ys = [x['y1'] for x in lines] + [x['y2'] for x in lines]
    flags = []
    if min(xs) < 8 or max(xs) > (w - 8): flags.append('EDGE_TEXT_HORIZONTAL')
    if min(ys) < 8 or max(ys) > (h - 8): flags.append('EDGE_TEXT_VERTICAL')
    return flags
