"""
Audit router — GET /audit/{patient_id} and GET /replay/{patient_id}

Provides:
- Full audit trail for a patient (all decisions, state transitions, rationale)
- Event replay to reproduce the same final state
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import Event, PatientState, AuditLog
from app.schemas import AuditTrailResponse, AuditLogEntry, PatientStateResponse


router = APIRouter(tags=["audit"])


# ── GET /audit/{patient_id} ─────────────────────────────────────────────

@router.get(
    "/audit/{patient_id}",
    response_model=AuditTrailResponse,
    responses={
        404: {"description": "No audit trail found for this patient"},
    },
)
def get_audit_trail(
    patient_id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    db: Session = Depends(get_db),
):
    """
    Retrieve the full audit trail for a patient.

    Includes:
    - All events ingested
    - Conflict resolution decisions with rationale
    - Report generation logs
    - State transitions
    """
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.patient_id == patient_id)
        .order_by(AuditLog.created_at.asc())
        .limit(limit)
        .all()
    )

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit trail found for patient {patient_id}",
        )

    return AuditTrailResponse(
        patient_id=patient_id,
        total_entries=len(entries),
        entries=[
            AuditLogEntry(
                id=e.id,
                patient_id=e.patient_id,
                event_id=e.event_id,
                action=e.action,
                details=e.details,
                created_at=e.created_at,
            )
            for e in entries
        ],
    )


# ── GET /state/{patient_id} ─────────────────────────────────────────────

@router.get(
    "/state/{patient_id}",
    response_model=PatientStateResponse,
    responses={
        404: {"description": "No state found for this patient"},
    },
)
def get_patient_state(
    patient_id: str,
    version: int = Query(default=None, ge=1, description="Specific version (latest if omitted)"),
    db: Session = Depends(get_db),
):
    """
    Retrieve the current (or specific version of) patient state.
    """
    query = db.query(PatientState).filter(PatientState.patient_id == patient_id)

    if version:
        state = query.filter(PatientState.version == version).first()
    else:
        state = query.order_by(PatientState.version.desc()).first()

    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No state found for patient {patient_id}"
            + (f" version {version}" if version else ""),
        )

    return PatientStateResponse(
        patient_id=state.patient_id,
        version=state.version,
        timestamp=state.timestamp,
        diagnosis=state.diagnosis,
        treatment=state.treatment,
        vitals=state.vitals,
        event_history=state.event_history or [],
        created_at=state.created_at,
    )


# ── GET /replay/{patient_id} ────────────────────────────────────────────

@router.get(
    "/replay/{patient_id}",
    response_model=dict,
    responses={
        404: {"description": "No events found for this patient"},
    },
)
def replay_events(
    patient_id: str,
    db: Session = Depends(get_db),
):
    """
    Replay all events for a patient and verify the final state matches.

    This endpoint:
    1. Fetches all raw events in timestamp order
    2. Replays conflict resolution from scratch
    3. Compares replayed state against the stored latest state
    4. Returns a verification report
    """
    from app.services.conflict_resolver import resolve_conflicts

    # ── Fetch all events ─────────────────────────────────────────────
    events = (
        db.query(Event)
        .filter(Event.patient_id == patient_id)
        .order_by(Event.timestamp.asc())
        .all()
    )

    if not events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No events found for patient {patient_id}",
        )

    # ── Replay: re-resolve conflicts from scratch ────────────────────
    event_dicts = [
        {
            "id": e.id,
            "source": e.source,
            "timestamp": e.timestamp,
            "data": e.data or {},
            "confidence": 0.0,
        }
        for e in events
    ]

    replayed = resolve_conflicts(event_dicts)

    # ── Fetch stored state for comparison ────────────────────────────
    stored_state = (
        db.query(PatientState)
        .filter(PatientState.patient_id == patient_id)
        .order_by(PatientState.version.desc())
        .first()
    )

    # ── Compare ──────────────────────────────────────────────────────
    match = True
    mismatches = []

    if stored_state:
        for field_name in ["diagnosis", "treatment", "vitals"]:
            stored_val = getattr(stored_state, field_name)
            replayed_val = getattr(replayed, field_name)
            if str(stored_val) != str(replayed_val):
                match = False
                mismatches.append({
                    "field": field_name,
                    "stored": stored_val,
                    "replayed": replayed_val,
                })

    return {
        "patient_id": patient_id,
        "total_events": len(events),
        "replay_result": {
            "diagnosis": replayed.diagnosis,
            "treatment": replayed.treatment,
            "vitals": replayed.vitals,
            "conflicts_found": len(replayed.resolutions),
            "resolutions": replayed.resolutions,
        },
        "stored_state_version": stored_state.version if stored_state else None,
        "match": match,
        "mismatches": mismatches,
        "deterministic": match and len(mismatches) == 0,
    }
