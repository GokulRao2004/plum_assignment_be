from pathlib import Path
from .ocr_core import render_pdf_pages
from .extractors import extract_page_data
from .schemas import build_final_doc
from .validators import apply_validation


def process_document(file_path, expected_tag, doc_type_override='AUTO', ocr_mode='AUTO'):
    pages = render_pdf_pages(file_path) if str(file_path).lower().endswith('.pdf') else [str(file_path)]
    page_outputs = []
    for i, page_path in enumerate(pages, start=1):
        ex, _ = extract_page_data(page_path, page_no=i, doc_type_override=doc_type_override, ocr_mode=ocr_mode)
        page_outputs.append(ex)
    doc = build_final_doc(page_outputs, expected_tag=expected_tag, input_path=str(file_path))
    doc = apply_validation(doc, expected_tag)
    return doc
