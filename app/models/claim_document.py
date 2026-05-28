from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC

from app.database import db


def generate_uuid():
    return str(uuid.uuid4())


class ClaimDocument(db.Model):
    __tablename__ = "claim_documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    claim_id = Column(
        UUID(as_uuid=False), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )

    file_path = Column(String(512), nullable=False)
    original_filename = Column(String(256), nullable=True)
    mime_type = Column(String(128), nullable=True)

    doc_tag = Column(String(64), nullable=False)

    ocr_text = Column(Text, nullable=True)
    extracted_fields = Column(JSONB, nullable=True)
    doc_confidence = Column(NUMERIC(4, 3), nullable=True)

    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    claim = db.relationship("Claim", back_populates="documents")