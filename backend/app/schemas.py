"""
Pydantic schemas for request validation and response serialization.

Organized by domain:
- Event schemas      (ingestion)
- PatientState schemas (state queries)
- AuditLog schemas   (audit trail)
- Report schemas     (report generation & retrieval)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    """Allowed clinical event sources — closed set per PRD."""
    EHR = "EHR"
    CLINICIAN_NOTE = "clinician_note"
    WEARABLE = "wearable"


# ── Event Schemas ────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    """POST /events request body."""
    patient_id: str = Field(..., min_length=1, max_length=64, description="Unique patient identifier")
    timestamp: datetime = Field(..., description="When the clinical event occurred (ISO 8601)")
    source: SourceType = Field(..., description="Event source: EHR | clinician_note | wearable")
    data: dict[str, Any] = Field(..., description="Clinical data payload (vitals, diagnosis, treatment, etc.)")

    @field_validator("data")
    @classmethod
    def data_must_not_be_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("data must not be an empty dict")
        return v


class EventResponse(BaseModel):
    """Successful POST /events response."""
    id: int
    event_hash: str
    patient_id: str
    timestamp: datetime
    source: str
    message: str = "Event ingested successfully"

    model_config = {"from_attributes": True}


# ── Patient State Schemas ────────────────────────────────────────────────

class PatientStateResponse(BaseModel):
    """Current or historical patient state snapshot."""
    patient_id: str
    version: int
    timestamp: datetime
    diagnosis: Optional[dict[str, Any]] = None
    treatment: Optional[dict[str, Any]] = None
    vitals: Optional[dict[str, Any]] = None
    event_history: list[int] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientListItem(BaseModel):
    """Summary item for listing all patients."""
    patient_id: str
    latest_version: int
    event_count: int
    last_updated: datetime


# ── Audit Log Schemas ────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    """Single audit trail entry."""
    id: int
    patient_id: str
    event_id: Optional[int] = None
    action: str
    details: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditTrailResponse(BaseModel):
    """Full audit trail for a patient (GET /audit/{patient_id})."""
    patient_id: str
    total_entries: int
    entries: list[AuditLogEntry]


# ── Report Schemas ───────────────────────────────────────────────────────

class ReportResponse(BaseModel):
    """Generated treatment report (GET /report/{patient_id})."""
    patient_id: str
    version: int
    content: str
    confidence: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None
    state_version: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportTriggerResponse(BaseModel):
    """POST /report/{patient_id} response."""
    patient_id: str
    report_version: int
    message: str = "Report generated successfully"
    confidence: Optional[float] = None


# ── Error Schemas ────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response body."""
    detail: str
    error_code: Optional[str] = None
