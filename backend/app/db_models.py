"""
SQLAlchemy ORM models for the clinical report generator.

Tables:
- events:          raw clinical events (immutable after insert)
- patient_states:  versioned snapshots of a patient's current state
- audit_logs:      append-only log of all decisions and actions
- reports:         generated treatment reports
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, JSON, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Event(Base):
    """Raw clinical event as received via POST /events."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_hash = Column(String(64), unique=True, nullable=False, index=True)
    patient_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)                # event time
    source = Column(String(32), nullable=False)                 # EHR | clinician_note | wearable
    data = Column(JSON, nullable=False)                         # vitals, diagnosis, treatment, etc.
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PatientState(Base):
    """
    Versioned snapshot of a patient's reconciled state.

    Each new event creates a new version.  The latest version (highest
    version number for a patient_id) is the current state.
    """
    __tablename__ = "patient_states"
    __table_args__ = (
        UniqueConstraint("patient_id", "version", name="uq_patient_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)                # when this version was created
    diagnosis = Column(JSON, nullable=True)                     # current reconciled diagnosis
    treatment = Column(JSON, nullable=True)                     # current reconciled treatment
    vitals = Column(JSON, nullable=True)                        # latest vitals
    event_history = Column(JSON, nullable=False, default=list)  # ordered list of event IDs
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    """Append-only audit trail entry."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(64), nullable=False, index=True)
    event_id = Column(Integer, nullable=True)                   # FK to events.id (null for non-event actions)
    action = Column(String(64), nullable=False)                 # e.g. event_ingested, conflict_resolved, report_generated
    details = Column(JSON, nullable=True)                       # rationale, decisions, metadata
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Report(Base):
    """Generated treatment report for a patient."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)                      # the report text
    confidence = Column(Float, nullable=True)                   # model-assigned confidence 0.0–1.0
    metadata_ = Column("metadata", JSON, nullable=True)         # model used, iterations, timing
    state_version = Column(Integer, nullable=True)              # which patient_state version this is based on
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("patient_id", "version", name="uq_report_version"),
    )
