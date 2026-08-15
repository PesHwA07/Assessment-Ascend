"""
Deterministic event hashing for duplicate detection.

Hash = SHA-256( patient_id | timestamp_iso | source | sorted_json(data) )

Guarantees:
- Same event content → same hash (deterministic)
- Different field order in `data` → same hash (sort_keys=True)
- Different timestamps or sources → different hash
"""

import hashlib
import json
from datetime import datetime


def compute_event_hash(
    patient_id: str,
    timestamp: datetime,
    source: str,
    data: dict,
) -> str:
    """
    Compute a SHA-256 hash uniquely identifying a clinical event.

    Args:
        patient_id: Patient identifier.
        timestamp:  When the event occurred.
        source:     Event source (EHR, clinician_note, wearable).
        data:       Clinical data payload.

    Returns:
        64-character lowercase hex digest.
    """
    canonical = "|".join([
        patient_id,
        timestamp.isoformat(),
        source,
        json.dumps(data, sort_keys=True, default=str),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
