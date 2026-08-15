import json
import pytest

def test_ingest_event_success(client):
    payload = {
        "patient_id": "T001",
        "timestamp": "2024-01-01T10:00:00Z",
        "source": "EHR",
        "data": {"diagnosis": "Flu"}
    }
    response = client.post("/events", json=payload)
    assert response.status_code == 200
    assert response.json()["message"] == "Event ingested successfully"


def test_ingest_duplicate_event_409(client):
    payload = {
        "patient_id": "T001",
        "timestamp": "2024-01-01T10:00:00Z",
        "source": "EHR",
        "data": {"diagnosis": "Flu"}
    }
    # First insert
    res1 = client.post("/events", json=payload)
    assert res1.status_code == 200

    # Exact duplicate should trigger 409 (idempotency constraint)
    res2 = client.post("/events", json=payload)
    assert res2.status_code == 409


def test_ingest_malformed_event_400(client):
    # Missing 'source'
    payload = {
        "patient_id": "T001",
        "timestamp": "2024-01-01T10:00:00Z",
        "data": {"diagnosis": "Flu"}
    }
    response = client.post("/events", json=payload)
    assert response.status_code == 400
    assert "Malformed input" in response.text


def test_get_state_and_versioning(client):
    client.post("/events", json={
        "patient_id": "T002",
        "timestamp": "2024-01-01T10:00:00Z",
        "source": "EHR",
        "data": {"diagnosis": "Flu"}
    })
    
    res_state = client.get("/state/T002")
    assert res_state.status_code == 200
    state = res_state.json()
    assert state["version"] == 1
    assert state["diagnosis"] == "Flu"
    
    # Second event should bump version
    client.post("/events", json={
        "patient_id": "T002",
        "timestamp": "2024-01-02T10:00:00Z",
        "source": "EHR",
        "data": {"treatment": "Rest"}
    })
    
    res_state2 = client.get("/state/T002")
    assert res_state2.json()["version"] == 2
    assert res_state2.json()["diagnosis"] == "Flu"  # retained from v1
    assert res_state2.json()["treatment"] == "Rest" # added in v2


def test_report_generation_and_audit(client):
    client.post("/events", json={
        "patient_id": "T003",
        "timestamp": "2024-01-01T10:00:00Z",
        "source": "EHR",
        "data": {"diagnosis": "Flu"}
    })
    
    # Add conflicting event to trigger conflict resolution log
    client.post("/events", json={
        "patient_id": "T003",
        "timestamp": "2024-01-01T11:00:00Z",
        "source": "clinician_note",
        "data": {"diagnosis": "Severe Flu"}
    })
    
    # Generate report
    res_report = client.post("/report/T003")
    assert res_report.status_code == 200
    
    # Get report
    res_get_report = client.get("/report/T003")
    assert res_get_report.status_code == 200
    
    # Check audit trail
    res_audit = client.get("/audit/T003")
    assert res_audit.status_code == 200
    audit = res_audit.json()
    actions = [e["action"] for e in audit["entries"]]
    assert "event_ingested" in actions
    assert "conflict_resolved" in actions
    assert "report_generated" in actions


def test_replay_endpoint(client):
    # Ingest some events
    client.post("/events", json={
        "patient_id": "T004",
        "timestamp": "2024-01-01T10:00:00Z",
        "source": "EHR",
        "data": {"diagnosis": "Asthma"}
    })
    client.post("/events", json={
        "patient_id": "T004",
        "timestamp": "2024-01-01T11:00:00Z",
        "source": "clinician_note",
        "data": {"diagnosis": "Severe Asthma"}
    })
    
    res = client.get("/replay/T004")
    assert res.status_code == 200
    data = res.json()
    assert data["match"] is True
    assert data["deterministic"] is True
    # EHR should win over clinician_note
    assert data["replay_result"]["diagnosis"] == "Asthma"
