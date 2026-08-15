# Stateful, Reconciliation-Driven LLM Report Generator with Temporal Evidence and Conflict Resolution

# Stateful, Reconciliation-Driven LLM Report Generator with Temporal Evidence and Conflict Resolution

Title:
Stateful, Reconciliation-Driven LLM Report Generator with Temporal Evidence and Conflict Resolution

Background:
You are building a critical component for a healthcare AI platform that generates treatment reports from patient data. The system must handle conflicting, delayed, or duplicate inputs from multiple sources (e.g., EHRs, wearable sensors, clinician notes), while ensuring that every generated report is auditable, consistent, and grounded in the most reliable evidence available.

Problem Statement:
Design and implement a stateful, reconciliation-driven LLM report generator that processes incoming clinical events from multiple sources, resolves conflicts between conflicting or delayed data, and produces a final treatment report for each patient. The system must maintain a consistent, versioned state of patient records, handle out-of-order and duplicate events, and ensure that every decision is explainable and replayable.

Scope:
The system must ingest structured and unstructured clinical data from multiple sources, process it through a stateful RAG pipeline with self-critique, and generate treatment reports. It must handle conflicting evidence, late events, and duplicate inputs, while maintaining an audit trail of all decisions and state transitions. The final output must be deterministic and explainable.

MVP Scope:
1. **Event Ingestion & Deduplication**: Accept JSON-formatted clinical events from multiple sources via HTTP POST /events. Each event includes a patient ID, timestamp, source, and data fields (e.g., vitals, diagnosis, treatment). Handle duplicates and out-of-order events.  
2. **Stateful Patient Record Management**: Maintain a versioned, persistent state of each patient’s record using a local SQLite DB. Track all state transitions and support replay of events to reconstruct historical states.  
3. **Reconciliation-Driven RAG Pipeline**: Implement a LangGraph-based stateful RAG pipeline that processes events through a self-critique loop (retrieve → generate → critique → reformulate). Use two models: one for retrieval and one for critique to reduce hallucinations. Apply guardrails to detect PII and prompt injection.  
4. **Conflict Resolution & Final Report Generation**: When conflicting or overlapping data is detected (e.g., conflicting diagnoses or treatment plans), implement a deterministic conflict resolution strategy based on source reliability, timestamp, and evidence confidence. Generate a final treatment report only after all relevant events have been processed.  
5. **Audit Trail & Replayability**: Produce a human-readable audit log for each patient that includes all events processed, decisions made, and the rationale for each. Support replay of events to reproduce the same final state and report.

Advanced/Bonus Scope:
- Extend the system to support real-time event streaming via WebSocket or long-polling.  
- Add a user-facing dashboard to visualize patient state changes and audit logs.  
- Integrate with a mock EHR API to simulate real-time data ingestion.  
- Implement a configurable policy engine to dynamically adjust conflict resolution rules (e.g., prioritize EHR over clinician notes).

Functional Requirements:
- POST /events: Accept JSON events with fields: `patient_id`, `timestamp`, `source`, `data` (dict). Return 200 on success, 400 on malformed input, 409 on duplicate event.  
- Events must be idempotent: same event sent twice must not alter final state.  
- Patient state must be versioned and persisted in SQLite. Each state must include a timestamp, event history, and current diagnosis/treatment.  
- The RAG pipeline must use LangChain and LangGraph to implement a self-critique loop with two models: `llama-2-7b` for generation and `mistral-7b` for critique.  
- The pipeline must detect and reject PII and prompt injection.  
- When conflicts exist (e.g., two different diagnoses), the system must resolve them deterministically using:  
  - Source reliability (EHR > clinician note > wearable)  
  - Timestamp (later > earlier)  
  - Evidence confidence (from model)  
- Final treatment report must be generated only after all relevant events are processed.  
- Audit log must be generated for each patient, including:  
  - List of events processed  
  - Decisions made  
  - Rationale for conflict resolution  
  - Final report content  
- Support replay of events to reproduce the same final state and report.

Non-Functional Requirements:
- Deterministic: Same input and configuration → same final state and report.  
- Idempotent: Duplicate events must not alter the final state.  
- Auditability: All decisions and state transitions must be explainable.  
- Replayable: Events must be replayable to reproduce decisions.  
- Performance: All events must be processed within 5 seconds.  
- Memory: Must run on a local machine with <4GB RAM.

Constraints:
- Use only Python, SQL, FastAPI, Docker, Git/GitHub, PyTorch, LangChain, LangGraph.  
- No external LLM APIs or cloud services (e.g., OpenAI, Anthropic). All models must be self-hosted.  
- No Kafka, Kubernetes, or microservices.  
- No ML/LLM fine-tuning required — use provided pre-trained models.  
- Do not use ML for conflict resolution — use deterministic rules based on source, timestamp, and confidence.  
- No external databases beyond local SQLite.

Deliverables:
1. Submission — Public GitHub repository URL (required).  
2. Repository contents —  
   - Backend: FastAPI app with `/events` endpoint and `/audit/{patient_id}` route  
   - Frontend: Simple React dashboard to view patient state and audit logs  
   - Sample fixture data (CSV/JSON) covering ≥5 interacting edge cases  
   - Audit logs and generated reports for each patient  
3. Test Suite — Automated tests covering:  
   - Duplicate events  
   - Late/out-of-order events  
   - Conflicting data from multiple sources  
   - Missing or malformed events  
   - Replay of events to reproduce same state  
4. Documentation — README with clone → setup → run → test instructions, including where fixtures and audit outputs live.
