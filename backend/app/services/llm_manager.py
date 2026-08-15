"""
Sequential LLM manager — load/unload GGUF models one at a time.

Design constraints:
- Only ONE model in VRAM at a time (6GB VRAM / RTX 3050)
- Sequential: load generation model → generate → unload → load critique model → critique → unload
- Fallback mock mode when llama-cpp-python is unavailable (dev/testing)

Usage:
    manager = LLMManager()
    result = manager.generate(prompt)       # loads generation model
    critique = manager.critique(prompt)     # unloads gen, loads critique model
"""

import logging
from typing import Optional

from app.config import (
    GENERATION_MODEL_PATH,
    CRITIQUE_MODEL_PATH,
    LLM_TEMPERATURE,
    LLM_SEED,
    LLM_MAX_TOKENS,
    LLM_N_GPU_LAYERS,
    LLM_N_CTX,
)

logger = logging.getLogger(__name__)

# ── Try importing llama-cpp-python; fallback to mock if unavailable ──────
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
    logger.info("llama-cpp-python available — using real models")
except ImportError:
    LLAMA_AVAILABLE = False
    logger.warning(
        "llama-cpp-python not installed — using MOCK mode. "
        "Install it for real LLM inference."
    )


class LLMManager:
    """
    Manages sequential loading/unloading of two GGUF models.

    Attributes:
        _current_model: The currently loaded Llama instance (or None).
        _current_model_type: Which model is loaded ("generation" | "critique" | None).
    """

    def __init__(self):
        self._current_model: Optional[object] = None
        self._current_model_type: Optional[str] = None

    # ── Model Lifecycle ──────────────────────────────────────────────────

    def _unload_current(self) -> None:
        """Unload the current model from memory."""
        if self._current_model is not None:
            model_type = self._current_model_type
            del self._current_model
            self._current_model = None
            self._current_model_type = None
            logger.info("Unloaded %s model", model_type)

    def _load_model(self, model_type: str) -> None:
        """
        Load a model into memory, unloading any existing model first.

        Args:
            model_type: "generation" or "critique"
        """
        if self._current_model_type == model_type:
            return  # already loaded

        self._unload_current()

        if not LLAMA_AVAILABLE:
            self._current_model_type = model_type
            logger.info("MOCK: Pretending to load %s model", model_type)
            return

        model_path = (
            GENERATION_MODEL_PATH if model_type == "generation"
            else CRITIQUE_MODEL_PATH
        )

        logger.info("Loading %s model from %s ...", model_type, model_path)
        self._current_model = Llama(
            model_path=model_path,
            n_gpu_layers=LLM_N_GPU_LAYERS,
            n_ctx=LLM_N_CTX,
            seed=LLM_SEED,
            verbose=False,
        )
        self._current_model_type = model_type
        logger.info("Loaded %s model successfully", model_type)

    # ── Inference ────────────────────────────────────────────────────────

    def _run_inference(self, prompt: str) -> str:
        """Run inference on the currently loaded model."""
        if not LLAMA_AVAILABLE or self._current_model is None:
            return self._mock_inference(prompt)

        response = self._current_model(
            prompt,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            seed=LLM_SEED,
            stop=["</s>", "[INST]", "###"],
        )

        text = response["choices"][0]["text"].strip()
        return text

    def _mock_inference(self, prompt: str) -> str:
        """
        Generate a deterministic mock response for dev/testing.

        Parses the prompt to extract patient context and returns
        a structured mock report or critique.
        """
        if self._current_model_type == "generation":
            return (
                "## Clinical Report (MOCK)\n\n"
                "### Diagnosis\n"
                "Based on the available evidence from multiple sources, "
                "the patient presents with findings consistent with the "
                "recorded clinical data.\n\n"
                "### Treatment Plan\n"
                "Continue current treatment protocol as documented. "
                "Monitor vitals and adjust as clinically indicated.\n\n"
                "### Evidence Summary\n"
                "- EHR records reviewed\n"
                "- Clinician notes incorporated\n"
                "- Wearable data considered\n\n"
                "### Confidence\n"
                "Evidence confidence: 0.85\n"
            )
        else:  # critique
            return (
                "## Critique Assessment (MOCK)\n\n"
                "### Accuracy: PASS\n"
                "The report accurately reflects the available evidence.\n\n"
                "### Completeness: PASS\n"
                "All relevant data sources have been considered.\n\n"
                "### Consistency: PASS\n"
                "No contradictions found between report and source data.\n\n"
                "### Overall: APPROVED\n"
                "The report meets clinical documentation standards.\n"
            )

    # ── Public API ───────────────────────────────────────────────────────

    def generate(self, prompt: str) -> str:
        """
        Generate a clinical report using the generation model.

        Loads the generation model (unloading critique if loaded),
        runs inference, and returns the generated text.
        """
        self._load_model("generation")
        return self._run_inference(prompt)

    def critique(self, prompt: str) -> str:
        """
        Critique a generated report using the critique model.

        Loads the critique model (unloading generation if loaded),
        runs inference, and returns the critique text.
        """
        self._load_model("critique")
        return self._run_inference(prompt)

    def cleanup(self) -> None:
        """Explicitly release all model resources."""
        self._unload_current()

    @property
    def is_mock(self) -> bool:
        """Whether the manager is running in mock mode."""
        return not LLAMA_AVAILABLE

    @property
    def current_model(self) -> Optional[str]:
        """Which model is currently loaded (None if none)."""
        return self._current_model_type
