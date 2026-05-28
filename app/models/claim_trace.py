from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import db


def generate_uuid():
    return str(uuid.uuid4())


class ClaimTrace(db.Model):
    __tablename__ = "claim_traces"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    claim_id = Column(
        UUID(as_uuid=False), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )

    step = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="INFO")
    details = Column(JSONB, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    claim = db.relationship("Claim", back_populates="traces")