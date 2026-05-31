from datetime import datetime
from app.database import db


class OcrJob(db.Model):
    __tablename__ = 'ocr_jobs'

    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(512), nullable=False)
    file_path = db.Column(db.String(1024), nullable=False)
    expected_tag = db.Column(db.String(64), nullable=False)
    inferred_tag = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default='pending')
    manual_review = db.Column(db.Boolean, nullable=False, default=False)
    result_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
