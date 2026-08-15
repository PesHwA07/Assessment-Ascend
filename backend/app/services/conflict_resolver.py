"""
Deterministic per-field conflict resolution.

When multiple events for the same patient provide different values for
the same clinical field (diagnosis, treatment, vitals), this module
determines which value wins using a strict 3-tier ranking:

    Tier 1: Source reliability   (EHR > clinician_note > wearable)
    Tier 2: Timestamp            (later > earlier)
    Tier 3: Evidence confidence  (higher > lower, default 0.0)

Each field is resolved independently — the winning diagnosis may come
from a different event than the winning treatment.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.config import SOURCE_RELIABILITY


# ── Data Structures ──────────────────────────────────────────────────────

@dataclass
class FieldCandidate:
    """A single candidate value for a clinical field."""
    value: Any
    source: str
    timestamp: datetime
    confidence: float = 0.0
    event_id: Optional[int] = None

    def __post_init__(self):
        # Normalize to offset-naive for safe cross-comparison
        # (SQLite drops tzinfo, while direct API models retain it)
        if self.timestamp and self.timestamp.tzinfo is not None:
            self.timestamp = self.timestamp.replace(tzinfo=None)

    @property
    def source_rank(self) -> int:
        """Source reliability score (higher = more trusted)."""
        return SOURCE_RELIABILITY.get(self.source, 0)


@dataclass
class ResolutionResult:
    """Outcome of resolving conflicts for a single patient."""
    diagnosis: Optional[Any] = None
    treatment: Optional[Any] = None
    vitals: Optional[Any] = None
    resolutions: list = field(default_factory=list)   # audit trail of decisions


# ── Core Resolution ──────────────────────────────────────────────────────

def _rank_candidates(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    """
    Sort candidates by the 3-tier priority (best first).

    Sorting key (descending for all three):
        1. source_rank   (higher = better)
        2. timestamp     (later = better)
        3. confidence    (higher = better)
    """
    return sorted(
        candidates,
        key=lambda c: (c.source_rank, c.timestamp, c.confidence),
        reverse=True,
    )


def _resolve_field(
    field_name: str,
    candidates: list[FieldCandidate],
) -> tuple[Optional[Any], Optional[dict]]:
    """
    Resolve a single clinical field from multiple candidate values.

    Args:
        field_name:  Name of the field (for audit logging).
        candidates:  All candidate values for this field.

    Returns:
        (winning_value, resolution_detail)
        resolution_detail is None if no conflict existed.
    """
    if not candidates:
        return None, None

    if len(candidates) == 1:
        # No conflict — single source
        return candidates[0].value, None

    # ── Multiple candidates → resolve ────────────────────────────────
    ranked = _rank_candidates(candidates)
    winner = ranked[0]
    losers = ranked[1:]

    # Check if there's an actual conflict (different values)
    unique_values = set()
    for c in candidates:
        # Convert dicts to frozenset for comparison
        if isinstance(c.value, dict):
            unique_values.add(frozenset(sorted(c.value.items())))
        else:
            unique_values.add(str(c.value))

    if len(unique_values) == 1:
        # All candidates agree — no conflict
        return winner.value, None

    # ── Genuine conflict — build rationale ───────────────────────────
    # Determine which tier broke the tie
    tier_used = _determine_winning_tier(winner, losers[0])

    resolution_detail = {
        "field": field_name,
        "conflict": True,
        "winner": {
            "value": winner.value,
            "source": winner.source,
            "timestamp": winner.timestamp.isoformat(),
            "confidence": winner.confidence,
            "event_id": winner.event_id,
        },
        "resolved_by": tier_used,
        "rejected": [
            {
                "value": loser.value,
                "source": loser.source,
                "timestamp": loser.timestamp.isoformat(),
                "confidence": loser.confidence,
                "event_id": loser.event_id,
            }
            for loser in losers
            # Only include losers with different values
            if str(loser.value) != str(winner.value)
        ],
    }

    return winner.value, resolution_detail


def _determine_winning_tier(winner: FieldCandidate, runner_up: FieldCandidate) -> str:
    """Identify which tier of the 3-tier strategy decided the winner."""
    if winner.source_rank != runner_up.source_rank:
        return f"source_reliability ({winner.source}={winner.source_rank} > {runner_up.source}={runner_up.source_rank})"
    if winner.timestamp != runner_up.timestamp:
        return f"timestamp ({winner.timestamp.isoformat()} > {runner_up.timestamp.isoformat()})"
    if winner.confidence != runner_up.confidence:
        return f"confidence ({winner.confidence} > {runner_up.confidence})"
    return "first_received (all tiers equal)"


# ── Public API ───────────────────────────────────────────────────────────

CLINICAL_FIELDS = ["diagnosis", "treatment", "vitals"]


def resolve_conflicts(
    events: list[dict],
) -> ResolutionResult:
    """
    Resolve all conflicts across a patient's events.

    Args:
        events: List of event dicts, each with keys:
            - id (int)
            - source (str)
            - timestamp (datetime)
            - data (dict with optional diagnosis, treatment, vitals keys)
            - confidence (float, default 0.0)

    Returns:
        ResolutionResult with the winning values and full audit trail.
    """
    result = ResolutionResult()

    for field_name in CLINICAL_FIELDS:
        # ── Collect candidates for this field ────────────────────────
        candidates = []
        for event in events:
            data = event.get("data", {})
            if field_name in data and data[field_name] is not None:
                candidates.append(FieldCandidate(
                    value=data[field_name],
                    source=event["source"],
                    timestamp=event["timestamp"],
                    confidence=event.get("confidence", 0.0),
                    event_id=event.get("id"),
                ))

        # ── Resolve this field ───────────────────────────────────────
        winning_value, resolution_detail = _resolve_field(field_name, candidates)
        setattr(result, field_name, winning_value)

        if resolution_detail:
            result.resolutions.append(resolution_detail)

    return result
