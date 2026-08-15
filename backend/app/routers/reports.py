"""
Reports router — POST /report/{patient_id} and GET /report/{patient_id}

POST triggers the RAG pipeline to generate a new report.
GET retrieves the latest (or all) generated reports.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.db_models import Event, PatientState, Report, AuditLog
from app.schemas import ReportResponse, ReportTriggerResponse
from app.services.rag_pipeline import run_pipeline
from app.services.state_manager import get_latest_state


router = APIRouter(tags=["reports"])


def _get_patient_events(db: Session, patient_id: str) -> list[dict]:
    """Fetch all events for a patient as dicts for the pipeline."""
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
            "timestamp": e.timestamp.isoformat() if e.timestamp else "",
            "data": e.data or {},
        }
        for e in events
    ]


def _get_conflict_resolutions(db: Session, patient_id: str) -> list[dict]:
    """Fetch all conflict resolution audit entries for a patient."""
    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.patient_id == patient_id,
            AuditLog.action == "conflict_resolved",
        )
        .all()
    )
    return [e.details for e in entries if e.details]


# ── POST /report/{patient_id} ───────────────────────────────────────────

@router.post(
    "/report/{patient_id}",
    response_model=ReportTriggerResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Patient not found"},
        500: {"description": "Pipeline error"},
    },
)
def trigger_report(patient_id: str, db: Session = Depends(get_db)):
    """
    Generate a clinical report for a patient.

    Flow:
    1. Verify patient exists (has at least one event)
    2. Fetch current resolved state
    3. Run the RAG pipeline (generate → critique → finalize)
    4. Persist the report
    5. Log in audit trail
    6. Return report metadata
    """
    # ── 1. Verify patient exists ─────────────────────────────────────
    latest_state = get_latest_state(db, patient_id)
    if not latest_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No events found for patient {patient_id}",
        )

    # ── 2. Build patient state dict for the pipeline ─────────────────
    patient_state = {
        "diagnosis": latest_state.diagnosis,
        "treatment": latest_state.treatment,
        "vitals": latest_state.vitals,
    }

    # ── 3. Gather evidence ───────────────────────────────────────────
    events = _get_patient_events(db, patient_id)
    conflict_resolutions = _get_conflict_resolutions(db, patient_id)

    # ── 4. Run RAG pipeline ──────────────────────────────────────────
    pipeline_result = run_pipeline(
        patient_id=patient_id,
        patient_state=patient_state,
        events=events,
        conflict_resolutions=conflict_resolutions,
    )

    if pipeline_result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {pipeline_result.error}",
        )

    # ── 5. Determine report version ──────────────────────────────────
    existing_count = (
        db.query(Report)
        .filter(Report.patient_id == patient_id)
        .count()
    )
    report_version = existing_count + 1

    # ── 6. Persist report ────────────────────────────────────────────
    report = Report(
        patient_id=patient_id,
        version=report_version,
        content=pipeline_result.generated_report,
        confidence=pipeline_result.confidence,
        state_version=latest_state.version,
        metadata_={
            "iterations": pipeline_result.iteration,
            "iteration_history": pipeline_result.iteration_history,
            "guardrail_issues": pipeline_result.guardrail_issues,
            "is_mock": True,  # will be False when real models are loaded
        },
    )
    db.add(report)

    # ── 7. Audit log ─────────────────────────────────────────────────
    audit_entry = AuditLog(
        patient_id=patient_id,
        action="report_generated",
        details={
            "report_version": report_version,
            "state_version": latest_state.version,
            "confidence": pipeline_result.confidence,
            "iterations": pipeline_result.iteration,
            "pipeline_approved": pipeline_result.is_approved,
        },
    )
    db.add(audit_entry)

    # ── 8. Commit ────────────────────────────────────────────────────
    db.commit()
    db.refresh(report)

    return ReportTriggerResponse(
        patient_id=patient_id,
        report_version=report_version,
        confidence=pipeline_result.confidence,
        message=f"Report v{report_version} generated successfully",
    )


# ── GET /report/{patient_id} ────────────────────────────────────────────

@router.get(
    "/report/{patient_id}",
    response_model=ReportResponse,
    responses={
        404: {"description": "No report found for this patient"},
    },
)
def get_latest_report(patient_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the latest generated report for a patient.
    """
    report = (
        db.query(Report)
        .filter(Report.patient_id == patient_id)
        .order_by(Report.version.desc())
        .first()
    )

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found for patient {patient_id}",
        )

    return ReportResponse(
        patient_id=report.patient_id,
        version=report.version,
        content=report.content,
        confidence=report.confidence,
        metadata=report.metadata_,
        state_version=report.state_version,
        created_at=report.created_at,
    )
