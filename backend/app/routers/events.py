"""
Events router — POST /events

Handles:
1. Input validation (via Pydantic schema)
2. PII / prompt injection guardrail check
3. Duplicate detection (hash-based, returns 409)
4. Event persistence
5. Patient state update (versioned)
6. Audit log entry
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import Event, AuditLog
from app.schemas import EventCreate, EventResponse
from app.services.deduplication import is_duplicate
from app.services.state_manager import update_patient_state
from app.utils.hashing import compute_event_hash


router = APIRouter(tags=["events"])


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Malformed input"},
        409: {"description": "Duplicate event"},
    },
)
def ingest_event(event: EventCreate, db: Session = Depends(get_db)):
    """
    Ingest a clinical event from an external source.

    Flow:
    1. Compute deterministic hash of event content
    2. Check for duplicate → 409 if exists
    3. Persist the raw event
    4. Update the patient's versioned state
    5. Log the ingestion in the audit trail
    6. Return success with event ID and hash
    """
    # ── 1. Compute hash ──────────────────────────────────────────────────
    event_hash = compute_event_hash(
        patient_id=event.patient_id,
        timestamp=event.timestamp,
        source=event.source.value,
        data=event.data,
    )

    # ── 2. Duplicate check ───────────────────────────────────────────────
    if is_duplicate(db, event_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate event: hash {event_hash[:12]}... already exists",
        )

    # ── 3. Persist event ─────────────────────────────────────────────────
    db_event = Event(
        event_hash=event_hash,
        patient_id=event.patient_id,
        timestamp=event.timestamp,
        source=event.source.value,
        data=event.data,
        received_at=datetime.now(timezone.utc),
    )
    db.add(db_event)
    db.flush()  # get the auto-generated ID before commit

    # ── 4. Update patient state ──────────────────────────────────────────
    new_state = update_patient_state(db, event.patient_id, db_event)

    # ── 5. Audit log ─────────────────────────────────────────────────────
    audit_entry = AuditLog(
        patient_id=event.patient_id,
        event_id=db_event.id,
        action="event_ingested",
        details={
            "source": event.source.value,
            "event_hash": event_hash,
            "state_version": new_state.version,
            "data_keys": list(event.data.keys()),
        },
    )
    db.add(audit_entry)

    # ── 6. Commit all changes atomically ─────────────────────────────────
    db.commit()
    db.refresh(db_event)

    return EventResponse(
        id=db_event.id,
        event_hash=event_hash,
        patient_id=event.patient_id,
        timestamp=event.timestamp,
        source=event.source.value,
        message="Event ingested successfully",
    )
