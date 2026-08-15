"""
LangGraph-based RAG pipeline with self-critique loop.

Flow:
    ┌──────────────┐
    │ build_prompt  │  Assemble patient state + evidence into prompt
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │   generate    │  Generation model creates clinical report
    └──────┬───────┘
           │
    ┌──────▼───────┐
    │  guardrail    │  Validate output (PII, structure, grounding)
    └──────┬───────┘
           │
    ┌──────▼───────┐     ┌─────────────┐
    │   critique    │────►│ reformulate │──► (back to generate, max 3x)
    └──────┬───────┘     └─────────────┘
           │ APPROVED
    ┌──────▼───────┐
    │   finalize    │  Extract confidence, package result
    └──────────────┘

Self-critique cycle:
- Critique model evaluates the generated report
- If critique says APPROVED → finalize
- If critique says REVISE → reformulate prompt with feedback → regenerate
- Maximum MAX_CRITIQUE_ITERATIONS cycles (default 3)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import MAX_CRITIQUE_ITERATIONS
from app.services.llm_manager import LLMManager
from app.services.guardrails import (
    validate_output,
    extract_confidence,
    check_pii,
)

logger = logging.getLogger(__name__)


# ── Pipeline State ───────────────────────────────────────────────────────

@dataclass
class PipelineState:
    """Tracks state through the LangGraph pipeline."""
    patient_id: str
    patient_state: dict
    events: list[dict]
    conflict_resolutions: list[dict]

    # Evolving state
    prompt: str = ""
    generated_report: str = ""
    critique_feedback: str = ""
    iteration: int = 0
    confidence: float = 0.0

    # Result tracking
    is_approved: bool = False
    guardrail_issues: list[str] = field(default_factory=list)
    iteration_history: list[dict] = field(default_factory=list)
    error: Optional[str] = None


# ── Prompt Templates ─────────────────────────────────────────────────────

GENERATION_PROMPT_TEMPLATE = """[INST] You are a clinical report generator. Based on the following patient evidence, generate a comprehensive treatment report.

PATIENT ID: {patient_id}

CURRENT CLINICAL STATE:
- Diagnosis: {diagnosis}
- Treatment: {treatment}
- Vitals: {vitals}

EVIDENCE TIMELINE:
{evidence_timeline}

CONFLICT RESOLUTIONS:
{conflict_resolutions}

INSTRUCTIONS:
1. Summarize the patient's current clinical picture under "### Diagnosis"
2. Recommend a treatment plan under "### Treatment Plan"
3. List all evidence considered under "### Evidence Summary", referencing the source type (EHR, clinician_note, wearable)
4. Assess and report your confidence in the evidence under "### Confidence" as "Evidence confidence: X.XX" (0.00-1.00)

Generate the report now: [/INST]
"""

CRITIQUE_PROMPT_TEMPLATE = """[INST] You are a clinical report reviewer. Evaluate the following generated report for accuracy, completeness, and clinical soundness.

PATIENT ID: {patient_id}

AVAILABLE EVIDENCE:
- Diagnosis: {diagnosis}
- Treatment: {treatment}
- Vitals: {vitals}

GENERATED REPORT:
{report}

EVALUATION CRITERIA:
1. Accuracy: Does the report match the available evidence?
2. Completeness: Are all evidence sources (EHR, clinician_note, wearable) referenced?
3. Consistency: Are there any contradictions?
4. Clinical soundness: Is the treatment plan appropriate for the diagnosis?

RESPOND WITH EXACTLY ONE OF:
- "APPROVED" if the report meets all criteria
- "REVISE: [specific feedback]" if the report needs changes

Your assessment: [/INST]
"""

REFORMULATION_PROMPT_TEMPLATE = """[INST] You are a clinical report generator. Your previous report received the following critique:

CRITIQUE FEEDBACK:
{critique_feedback}

PATIENT ID: {patient_id}

CURRENT CLINICAL STATE:
- Diagnosis: {diagnosis}
- Treatment: {treatment}
- Vitals: {vitals}

EVIDENCE TIMELINE:
{evidence_timeline}

CONFLICT RESOLUTIONS:
{conflict_resolutions}

Please generate an IMPROVED report addressing the critique feedback. Include:
1. "### Diagnosis" section
2. "### Treatment Plan" section
3. "### Evidence Summary" referencing source types (EHR, clinician_note, wearable)
4. "### Confidence" with "Evidence confidence: X.XX" (0.00-1.00)

Generate the improved report now: [/INST]
"""


# ── Pipeline Steps ───────────────────────────────────────────────────────

def _format_evidence_timeline(events: list[dict]) -> str:
    """Format events into a readable timeline string."""
    if not events:
        return "No events recorded."

    lines = []
    for e in events:
        ts = e.get("timestamp", "unknown")
        source = e.get("source", "unknown")
        data_keys = list(e.get("data", {}).keys())
        lines.append(f"  [{ts}] {source}: {', '.join(data_keys)}")
    return "\n".join(lines)


def _format_conflict_resolutions(resolutions: list[dict]) -> str:
    """Format conflict resolution details into readable text."""
    if not resolutions:
        return "No conflicts detected."

    lines = []
    for r in resolutions:
        field_name = r.get("field", "unknown")
        winner = r.get("winner", {})
        resolved_by = r.get("resolved_by", "unknown")
        lines.append(
            f"  {field_name}: '{winner.get('value', '?')}' "
            f"(from {winner.get('source', '?')}) — {resolved_by}"
        )
    return "\n".join(lines)


def build_prompt(state: PipelineState) -> PipelineState:
    """Step 1: Build the generation prompt from patient state."""
    evidence_timeline = _format_evidence_timeline(state.events)
    conflict_text = _format_conflict_resolutions(state.conflict_resolutions)

    if state.iteration == 0 or not state.critique_feedback:
        # First generation
        state.prompt = GENERATION_PROMPT_TEMPLATE.format(
            patient_id=state.patient_id,
            diagnosis=json.dumps(state.patient_state.get("diagnosis"), default=str),
            treatment=json.dumps(state.patient_state.get("treatment"), default=str),
            vitals=json.dumps(state.patient_state.get("vitals"), default=str),
            evidence_timeline=evidence_timeline,
            conflict_resolutions=conflict_text,
        )
    else:
        # Reformulation after critique
        state.prompt = REFORMULATION_PROMPT_TEMPLATE.format(
            critique_feedback=state.critique_feedback,
            patient_id=state.patient_id,
            diagnosis=json.dumps(state.patient_state.get("diagnosis"), default=str),
            treatment=json.dumps(state.patient_state.get("treatment"), default=str),
            vitals=json.dumps(state.patient_state.get("vitals"), default=str),
            evidence_timeline=evidence_timeline,
            conflict_resolutions=conflict_text,
        )

    return state


def generate(state: PipelineState, llm: LLMManager) -> PipelineState:
    """Step 2: Generate or regenerate the clinical report."""
    state.generated_report = llm.generate(state.prompt)
    state.iteration += 1

    logger.info(
        "Generation iteration %d for patient %s (%d chars)",
        state.iteration, state.patient_id, len(state.generated_report),
    )
    return state


def run_guardrails(state: PipelineState) -> PipelineState:
    """Step 3: Validate the generated output."""
    result = validate_output(state.generated_report, state.patient_state)
    state.guardrail_issues = result.issues

    if not result.passed:
        logger.warning(
            "Guardrail issues for patient %s: %s",
            state.patient_id, result.issues,
        )
    return state


def critique(state: PipelineState, llm: LLMManager) -> PipelineState:
    """Step 4: Critique the generated report."""
    critique_prompt = CRITIQUE_PROMPT_TEMPLATE.format(
        patient_id=state.patient_id,
        diagnosis=json.dumps(state.patient_state.get("diagnosis"), default=str),
        treatment=json.dumps(state.patient_state.get("treatment"), default=str),
        vitals=json.dumps(state.patient_state.get("vitals"), default=str),
        report=state.generated_report,
    )

    critique_response = llm.critique(critique_prompt)

    # Record this iteration
    state.iteration_history.append({
        "iteration": state.iteration,
        "report_length": len(state.generated_report),
        "critique": critique_response[:200],
        "guardrail_issues": list(state.guardrail_issues),
    })

    # Parse critique response
    critique_upper = critique_response.upper().strip()
    if "APPROVED" in critique_upper:
        state.is_approved = True
        state.critique_feedback = ""
        logger.info("Report APPROVED at iteration %d", state.iteration)
    else:
        state.is_approved = False
        # Extract feedback after "REVISE:"
        if "REVISE:" in critique_response.upper():
            idx = critique_response.upper().index("REVISE:")
            state.critique_feedback = critique_response[idx + 7:].strip()
        else:
            state.critique_feedback = critique_response
        logger.info(
            "Report needs revision at iteration %d: %s",
            state.iteration, state.critique_feedback[:100],
        )

    return state


def finalize(state: PipelineState) -> PipelineState:
    """Step 5: Extract confidence and package the final result."""
    state.confidence = extract_confidence(state.generated_report)

    # If no confidence found in text, assign based on iteration count
    if state.confidence == 0.0:
        # Higher confidence if approved on first try
        state.confidence = max(0.5, 1.0 - (state.iteration - 1) * 0.15)

    logger.info(
        "Finalized report for patient %s: confidence=%.2f, iterations=%d",
        state.patient_id, state.confidence, state.iteration,
    )
    return state


# ── Main Pipeline Runner ─────────────────────────────────────────────────

def run_pipeline(
    patient_id: str,
    patient_state: dict,
    events: list[dict],
    conflict_resolutions: list[dict],
) -> PipelineState:
    print(f"\n[RAG PIPELINE] Starting generation for patient: {patient_id}")
    print(f"[LLM MANAGER] Initializing LLM context...")
    llm = LLMManager()

    state = PipelineState(
        patient_id=patient_id,
        patient_state=patient_state,
        events=events,
        conflict_resolutions=conflict_resolutions,
    )

    try:
        # ── Self-critique loop ───────────────────────────────────────
        while state.iteration < MAX_CRITIQUE_ITERATIONS:
            print(f"\n--- ITERATION {state.iteration + 1} ---")
            
            # 1. Build / reformulate prompt
            state = build_prompt(state)

            # 2. Generate report
            print(f"[GENERATION] Formulating clinical report (llama-2-7b)...")
            state = generate(state, llm)
            print(f"[GENERATION] Output length: {len(state.generated_report)} characters")

            # 3. Run guardrails
            print(f"[GUARDRAILS] Checking for PII & structure...")
            state = run_guardrails(state)

            # 4. Critique
            print(f"[CRITIQUE] Reviewing report for clinical accuracy (mistral-7b)...")
            state = critique(state, llm)

            # 5. Check if approved
            if state.is_approved:
                print("[CRITIQUE RESULT] APPROVED! Proceeding to finalize.")
                break
            else:
                print(f"[CRITIQUE RESULT] REVISE: {state.critique_feedback[:80]}...")

        # If max iterations reached without approval, accept the last version
        if not state.is_approved:
            logger.warning(
                "Max critique iterations (%d) reached for patient %s. "
                "Accepting last generated report.",
                MAX_CRITIQUE_ITERATIONS, patient_id,
            )
            state.is_approved = True

        # 6. Finalize
        state = finalize(state)
        print(f"\n[RAG PIPELINE] Finished! Final Confidence: {state.confidence}")

    except Exception as e:
        logger.error("Pipeline error for patient %s: %s", patient_id, str(e))
        state.error = str(e)
    finally:
        llm.cleanup()

    return state
