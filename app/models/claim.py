from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    Date,
    DateTime,
    Numeric,
    Boolean,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import db


def generate_uuid():
    return str(uuid.uuid4())


class Claim(db.Model):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    external_id = Column(String(64), nullable=True)

    member_id = Column(String(32), nullable=False)
    patient_name = Column(String(128), nullable=True)
    relationship = Column(String(32), nullable=True)

    claim_type = Column(String(32), nullable=False)

    treatment_date = Column(Date, nullable=False)
    submission_date = Column(Date, nullable=False)

    claimed_amount = Column(Numeric(12, 2), nullable=False)
    hospital_name = Column(String(256), nullable=True)
    is_network_hospital = Column(Boolean, nullable=False, default=False)

    status = Column(String(32), nullable=False, default="PENDING")

    decision = Column(String(32), nullable=True)
    approved_amount = Column(Numeric(12, 2), nullable=True)
    confidence = Column(Numeric(4, 3), nullable=True)
    primary_reason = Column(Text, nullable=True)

    claim_facts = Column(JSONB, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    documents = db.relationship(
        "ClaimDocument",
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    traces = db.relationship(
        "ClaimTrace",
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )