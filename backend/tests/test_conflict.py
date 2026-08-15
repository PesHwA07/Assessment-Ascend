from datetime import datetime
import pytest
from app.services.conflict_resolver import resolve_conflicts

def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def test_resolve_conflicts_source_reliability():
    """EHR (3) overrides clinician_note (2) regardless of timestamps."""
    events = [
        {
            "id": 1,
            "source": "clinician_note",
            "timestamp": _ts("2024-01-02T10:00:00Z"), # Later
            "confidence": 0.0,
            "data": {"diagnosis": "Hypertension"}
        },
        {
            "id": 2,
            "source": "EHR",
            "timestamp": _ts("2024-01-01T10:00:00Z"), # Earlier
            "confidence": 0.0,
            "data": {"diagnosis": "Diabetes"}
        }
    ]
    
    result = resolve_conflicts(events)
    assert result.diagnosis == "Diabetes"
    
    # Verify resolution log
    res_log = result.resolutions[0]
    assert res_log["field"] == "diagnosis"
    assert res_log["winner"]["source"] == "EHR"
    assert "source_reliability" in res_log["resolved_by"]


def test_resolve_conflicts_timestamp():
    """Same source, later timestamp wins."""
    events = [
        {
            "id": 1,
            "source": "EHR",
            "timestamp": _ts("2024-01-01T10:00:00Z"),
            "confidence": 0.0,
            "data": {"treatment": "Rest"}
        },
        {
            "id": 2,
            "source": "EHR",
            "timestamp": _ts("2024-01-02T10:00:00Z"),
            "confidence": 0.0,
            "data": {"treatment": "Surgery"}
        }
    ]
    
    result = resolve_conflicts(events)
    assert result.treatment == "Surgery"
    
    res_log = result.resolutions[0]
    assert "timestamp" in res_log["resolved_by"]


def test_resolve_conflicts_vitals_overwrite():
    """Vitals from the winning event completely overwrite losing events."""
    events = [
        {
            "id": 1,
            "source": "EHR",
            "timestamp": _ts("2024-01-01T10:00:00Z"),
            "confidence": 0.0,
            "data": {"vitals": {"hr": 80, "bp": "120/80"}}
        },
        {
            "id": 2,
            "source": "clinician_note",
            "timestamp": _ts("2024-01-02T10:00:00Z"),
            "confidence": 0.0,
            "data": {"vitals": {"hr": 90, "temp": 98.6}}
        }
    ]
    
    result = resolve_conflicts(events)
    
    # EHR wins due to source reliability. The entire vitals object is taken from EHR.
    assert result.vitals["hr"] == 80
    assert result.vitals["bp"] == "120/80"
    assert "temp" not in result.vitals


def test_out_of_order_determinism():
    """Resolving events out of order should yield the exact same state."""
    event_ehr = {
        "id": 1,
        "source": "EHR",
        "timestamp": _ts("2024-01-01T10:00:00Z"),
        "confidence": 0.0,
        "data": {"diagnosis": "A"}
    }
    event_note = {
        "id": 2,
        "source": "clinician_note",
        "timestamp": _ts("2024-01-02T10:00:00Z"),
        "confidence": 0.0,
        "data": {"diagnosis": "B"}
    }
    
    res_ordered = resolve_conflicts([event_ehr, event_note])
    res_unordered = resolve_conflicts([event_note, event_ehr])
    
    assert res_ordered.diagnosis == res_unordered.diagnosis == "A"
