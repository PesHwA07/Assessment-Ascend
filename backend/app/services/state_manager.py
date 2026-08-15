"""
Versioned patient state management.

Each incoming event creates a new version of the patient's state.
The state is built incrementally:
- New vitals REPLACE old vitals (latest reading wins)
- New diagnosis/treatment are MERGED with existing, subject to conflict
  resolution in Phase 3 (for now, latest event wins within same source)
- Event history is appended

The latest version (highest version number) is the current state.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db_models import Event, PatientState


def get_latest_state(db: Session, patient_id: str) -> Optional[PatientState]:
    """Fetch the most recent state version for a patient, or None if new."""
    return (
        db.query(PatientState)
        .filter(PatientState.patient_id == patient_id)
        .order_by(PatientState.version.desc())
        .first()
    )


def get_next_version(db: Session, patient_id: str) -> int:
    """Return the next version number for a patient (1-based)."""
    max_version = (
        db.query(func.max(PatientState.version))
        .filter(PatientState.patient_id == patient_id)
        .scalar()
    )
    return (max_version or 0) + 1


def _merge_field(existing: Optional[dict], incoming: dict, field_key: str) -> Optional[dict]:
    """
    Merge a clinical data field (diagnosis or treatment) from a new event
    into the existing state.

    Strategy (pre-conflict-resolution):
    - If incoming event contains the field_key, use the incoming value
    - Otherwise, keep the existing value unchanged
    """
    incoming_value = incoming.get(field_key)
    if incoming_value is not None:
        # Wrap scalar values in a dict for consistency
        if isinstance(incoming_value, str):
            return {"value": incoming_value, "source": "pending_resolution"}
        return incoming_value if isinstance(incoming_value, dict) else {"value": incoming_value}
    return existing


def update_patient_state(db: Session, patient_id: str, event: Event) -> PatientState:
    """
    Create a new versioned state snapshot after ingesting an event.

    Args:
        db:         Active database session (caller manages commit).
        patient_id: Patient identifier.
        event:      The persisted Event ORM object.

    Returns:
        The newly created PatientState (not yet committed).
    """
    latest = get_latest_state(db, patient_id)
    next_version = get_next_version(db, patient_id)

    # ── Build from previous state or start fresh ─────────────────────────
    if latest:
        prev_diagnosis = latest.diagnosis
        prev_treatment = latest.treatment
        prev_vitals = latest.vitals
        prev_history = list(latest.event_history or [])
    else:
        prev_diagnosis = None
        prev_treatment = None
        prev_vitals = None
        prev_history = []

    event_data = event.data or {}

    # ── Merge fields from the incoming event ─────────────────────────────
    new_diagnosis = _merge_field(prev_diagnosis, event_data, "diagnosis")
    new_treatment = _merge_field(prev_treatment, event_data, "treatment")

    # Vitals: latest reading replaces entirely
    new_vitals = event_data.get("vitals", prev_vitals)

    # Event history: append this event's ID
    new_history = prev_history + [event.id]

    # ── Create new state version ─────────────────────────────────────────
    new_state = PatientState(
        patient_id=patient_id,
        version=next_version,
        timestamp=datetime.now(timezone.utc),
        diagnosis=new_diagnosis,
        treatment=new_treatment,
        vitals=new_vitals,
        event_history=new_history,
    )
    db.add(new_state)
    db.flush()  # make version available to caller before commit

    return new_state
