# 🏥 Stateful LLM Clinical Report Generator

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.25+-red.svg)
![LangGraph](https://img.shields.io/badge/LangGraph-Enabled-purple.svg)

A reconciliation-driven, stateful AI clinical report generator built with **FastAPI**, **LangGraph**, **Streamlit**, and **Local GGUF Models**.

This system processes incoming clinical events (EHR, wearables, clinician notes), maintains a versioned patient state in SQLite, resolves data conflicts deterministically, and generates clinical reports using an advanced self-critique loop with local Large Language Models.

---

## ✨ Key Features
- **Idempotent Event Ingestion**: `POST /events` safely handles duplicates and out-of-order events using SHA-256 payload hashing.
- **Deterministic Conflict Resolution**: Employs a strict 3-tier ranking hierarchy (`Source` > `Timestamp` > `Confidence`).
- **Stateful RAG Pipeline**: Powered by LangGraph, utilizing `llama-2-7b` for initial generation and `mistral-7b` for rigorous self-critique.
- **Resource Optimized**: LLMs are loaded/unloaded sequentially into VRAM, allowing the system to run on hardware with strict memory limits (e.g., RTX 3050 6GB).
- **Comprehensive Provenance**: Complete append-only audit trail tracking every state change and conflict resolution decision.

---

## 🚀 Getting Started

Follow these steps to deploy and run the system locally.

### 1. Clone
Clone the repository to your local machine:
```bash
git clone https://github.com/PesHwA07/Assessment-Ascend.git
cd Assessment
```

### 2. Setup
The system is built to use self-hosted GGUF models. To run the real LLMs, download and place your GGUF files directly into the `backend/models/` directory:
- `backend/models/llama-2-7b-chat.Q4_K_M.gguf`
- `backend/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf`

> **Note (Mock Mode)**: If you do not install `llama-cpp-python` or download the models, the system will automatically and gracefully fall back to **Mock Mode**. This allows you to test the entire architecture, UI, and API without needing a high-end GPU.

### 3. Run
The absolute easiest way to run the full stack (FastAPI Backend + Streamlit Frontend) is via Docker Compose:

```bash
docker-compose up --build
```

Once the containers are spinning, access the system at:
- **Frontend Clinical Dashboard**: [http://localhost:8501](http://localhost:8501)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **API Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

*(If you prefer to run it manually without Docker, simply create virtual environments in the `backend/` and `frontend/` folders, install `requirements.txt`, and run `uvicorn app.main:app` and `streamlit run app.py` respectively).*

### 4. Test
The repository includes a comprehensive `pytest` suite covering:
- Duplicate events
- Late/out-of-order events
- Conflicting data from multiple sources
- Missing or malformed events
- Replaying events to reproduce state

To run the automated test suite locally:
```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

---

## 📁 System Artifacts

### Where do Fixtures live?
The fixture data—which covers the core interaction edge cases (duplicates, conflicts, out-of-order)—is located at:
👉 **`backend/data/sample_events.json`**

You can instantly ingest these fixtures into the system by clicking the **"Inject Sample Events"** button on the Streamlit dashboard.

### Where do Audit Outputs live?
Audit outputs are permanently stored in the `audit_logs` table of the SQLite database (`backend/data/clinical.db`). 

You can retrieve and view them in two ways:
1. **API**: Make a request to `GET /audit/{patient_id}`
2. **Dashboard**: Navigate to the **"Data Provenance & Conflicts"** tab in the Streamlit UI for a beautifully formatted timeline of all audit logs.

---

## 🧠 Key Design Decisions

1. **Streamlit over React**: The PRD mentions "React dashboard" (line 68) but also mandates "Use only Python" (line 57). Since these constraints conflict, we chose **Streamlit** — a Python-native dashboard framework — to keep the entire codebase in a single language and simplify deployment. The dashboard delivers the same functionality: patient state visualization, audit log browsing, and report generation.

2. **Deterministic Conflict Resolution (No ML)**: Per the PRD, we use hard-coded 3-tier rules (`Source > Timestamp > Confidence`) rather than an LLM, ensuring reproducibility and auditability.

3. **Sequential LLM Loading**: Due to VRAM constraints (6GB), `LLMManager` loads/unloads one model at a time — generation first, then critique — preventing OOM errors on consumer-grade GPUs.

4. **Mock Mode Fallback**: If `llama-cpp-python` is not installed or GGUF model files are absent, the system gracefully falls back to deterministic mock responses, allowing the full architecture to be tested without a GPU.
