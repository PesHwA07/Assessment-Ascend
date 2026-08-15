"""
Versioned patient state management.

Each incoming event creates a new version of the patient's state.
The state is built by:
1. Collecting ALL events for the patient (in timestamp order)
2. Running per-field conflict resolution across all events
3. Storing the resolved state as a new version

The latest version (highest version number) is the current state.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db_models import Event, PatientState, AuditLog
from app.services.conflict_resolver import resolve_conflicts


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


def _get_all_patient_events(db: Session, patient_id: str) -> list[dict]:
    """
    Fetch all events for a patient, ordered by timestamp.

    Returns list of dicts ready for the conflict resolver.
    """
    events = (
        db.query(Event)
        .filter(Event.patient_id == patient_id)
        .order_by(Event.timestamp.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "source": e.source,
            "timestamp": e.timestamp,
            "data": e.data or {},
            "confidence": 0.0,  # default until LLM assigns confidence
        }
        for e in events
    ]


def update_patient_state(db: Session, patient_id: str, event: Event) -> PatientState:
    """
    Create a new versioned state snapshot after ingesting an event.

    Rebuilds the resolved state from ALL events for this patient using
    the conflict resolver, ensuring that late-arriving or out-of-order
    events are handled correctly.

    Args:
        db:         Active database session (caller manages commit).
        patient_id: Patient identifier.
        event:      The persisted Event ORM object.

    Returns:
        The newly created PatientState (not yet committed).
    """
    next_version = get_next_version(db, patient_id)

    # ── Gather all events and resolve conflicts ──────────────────────────
    all_events = _get_all_patient_events(db, patient_id)
    resolution = resolve_conflicts(all_events)

    # ── Build event ID history ───────────────────────────────────────────
    event_history = [e["id"] for e in all_events]

    # ── Log only NEW conflict scenarios ──────────────────────────────────
    import json
    # Get previously logged conflicts for this patient
    existing_logs = db.query(AuditLog.details).filter(
        AuditLog.patient_id == patient_id,
        AuditLog.action == "conflict_resolved"
    ).all()
    
    # Extract just the 'rejected' lists to see what conflicts we've already logged
    logged_rejected = []
    for (details,) in existing_logs:
        if details and "rejected" in details:
            # Sort rejected to ensure consistent comparison regardless of order
            sorted_rej = sorted(details["rejected"], key=lambda r: r["source"] + str(r["timestamp"]))
            logged_rejected.append(sorted_rej)

    for res in resolution.resolutions:
        # Sort current rejected list for comparison
        current_rej = sorted(res.get("rejected", []), key=lambda r: r["source"] + str(r["timestamp"]))
        
        # If we've already logged this exact conflict scenario, skip it
        if current_rej in logged_rejected:
            continue

        audit_entry = AuditLog(
            patient_id=patient_id,
            event_id=event.id,
            action="conflict_resolved",
            details=res,
        )
        db.add(audit_entry)

    # ── Create new state version ─────────────────────────────────────────
    new_state = PatientState(
        patient_id=patient_id,
        version=next_version,
        timestamp=datetime.now(timezone.utc),
        diagnosis=resolution.diagnosis,
        treatment=resolution.treatment,
        vitals=resolution.vitals,
        event_history=event_history,
    )
    db.add(new_state)
    db.flush()

    return new_state
