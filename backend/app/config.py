"""
Application configuration.

Centralizes all settings: DB path, model paths, model parameters,
source reliability rankings, and self-critique iteration cap.
"""

import os
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'clinical.db'}"

MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

GENERATION_MODEL_PATH = os.getenv(
    "GENERATION_MODEL_PATH",
    str(MODEL_DIR / "llama-2-7b-chat.Q4_K_M.gguf"),
)
CRITIQUE_MODEL_PATH = os.getenv(
    "CRITIQUE_MODEL_PATH",
    str(MODEL_DIR / "mistral-7b-instruct-v0.2.Q4_K_M.gguf"),
)

# ── LLM Parameters ──────────────────────────────────────────────────────
LLM_TEMPERATURE = 0.0
LLM_SEED = 42
LLM_MAX_TOKENS = 1024
LLM_N_GPU_LAYERS = -1          # offload all layers to GPU
LLM_N_CTX = 2048               # context window

# ── Self-Critique Pipeline ───────────────────────────────────────────────
MAX_CRITIQUE_ITERATIONS = 3

# ── Source Reliability (higher = more trusted) ───────────────────────────
SOURCE_RELIABILITY = {
    "EHR": 3,
    "clinician_note": 2,
    "wearable": 1,
}

# ── CORS (frontend) ─────────────────────────────────────────────────────
FRONTEND_ORIGINS = [
    "http://localhost:8501",     # Streamlit default
    "http://localhost:8000",     # API self-reference
]
