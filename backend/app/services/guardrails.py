"""
Input/output guardrails for the RAG pipeline.

Pre-generation guardrails:
- PII detection (basic pattern matching for SSN, phone, email)
- Prompt injection detection (common attack patterns)

Post-generation guardrails:
- Hallucination check (output must reference provided evidence)
- Confidence extraction from model output
- Structural validation (report must have required sections)
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data Structures ──────────────────────────────────────────────────────

@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    issues: list[str]
    sanitized_text: Optional[str] = None


# ── PII Detection ────────────────────────────────────────────────────────

PII_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
}


def check_pii(text: str) -> GuardrailResult:
    """
    Scan text for common PII patterns.

    Returns GuardrailResult with sanitized_text where PII is redacted.
    """
    issues = []
    sanitized = text

    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, text)
        if matches:
            issues.append(f"Found {len(matches)} potential {pii_type} pattern(s)")
            sanitized = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", sanitized)

    return GuardrailResult(
        passed=len(issues) == 0,
        issues=issues,
        sanitized_text=sanitized,
    )


# ── Prompt Injection Detection ───────────────────────────────────────────

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?(your|the)\s+instructions",
    r"you\s+are\s+now\s+a",
    r"pretend\s+you\s+are",
    r"act\s+as\s+(if|a)",
    r"system\s*:\s*you",
    r"<\s*script\s*>",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bimport\s+os\b",
]


def check_injection(text: str) -> GuardrailResult:
    """
    Detect potential prompt injection attacks in input text.

    Uses pattern matching for common injection techniques.
    """
    issues = []

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(f"Potential injection detected: pattern '{pattern}'")

    return GuardrailResult(
        passed=len(issues) == 0,
        issues=issues,
    )


# ── Input Validation (combined pre-generation check) ─────────────────────

def validate_input(event_data: dict) -> GuardrailResult:
    """
    Run all pre-generation guardrails on event data.

    Checks the string representation of the data dict for PII and injection.
    """
    text = str(event_data)
    all_issues = []

    # PII check
    pii_result = check_pii(text)
    all_issues.extend(pii_result.issues)

    # Injection check
    injection_result = check_injection(text)
    all_issues.extend(injection_result.issues)

    return GuardrailResult(
        passed=len(all_issues) == 0,
        issues=all_issues,
        sanitized_text=pii_result.sanitized_text,
    )


# ── Output Validation (post-generation checks) ──────────────────────────

CONFIDENCE_PATTERN = r"(?:confidence|evidence\s+confidence)\s*[:=]\s*(0?\.\d+|1\.0|1)"


def extract_confidence(report_text: str) -> float:
    """
    Extract evidence confidence score from model-generated report.

    Looks for patterns like "Evidence confidence: 0.85" or "confidence: 0.92".
    Returns 0.0 if no confidence found.
    """
    match = re.search(CONFIDENCE_PATTERN, report_text, re.IGNORECASE)
    if match:
        try:
            score = float(match.group(1))
            return min(max(score, 0.0), 1.0)  # clamp to [0, 1]
        except ValueError:
            pass
    return 0.0


def validate_output(
    report_text: str,
    patient_state: dict,
) -> GuardrailResult:
    """
    Validate model-generated report for quality and safety.

    Checks:
    1. Report is not empty
    2. Report contains required sections
    3. No PII leaked into output
    4. Report references available evidence
    """
    issues = []

    # 1. Non-empty check
    if not report_text or len(report_text.strip()) < 50:
        issues.append("Report is too short or empty")

    # 2. Structural check — should have diagnosis/treatment sections
    report_lower = report_text.lower()
    required_keywords = ["diagnosis", "treatment"]
    for keyword in required_keywords:
        if keyword not in report_lower:
            issues.append(f"Report missing expected section: {keyword}")

    # 3. PII check on output
    pii_result = check_pii(report_text)
    if not pii_result.passed:
        issues.extend([f"OUTPUT PII: {i}" for i in pii_result.issues])

    # 4. Evidence grounding — report should reference source types
    source_types = ["ehr", "clinician", "wearable"]
    referenced_sources = sum(1 for s in source_types if s in report_lower)
    if referenced_sources == 0 and patient_state:
        issues.append("Report does not reference any evidence sources")

    return GuardrailResult(
        passed=len(issues) == 0,
        issues=issues,
    )
