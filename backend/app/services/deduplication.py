"""
Event deduplication service.

Checks whether an event with the same hash already exists in the database.
Uses the unique index on events.event_hash for O(1) lookup.
"""

from sqlalchemy.orm import Session

from app.db_models import Event


def is_duplicate(db: Session, event_hash: str) -> bool:
    """
    Check if an event with this hash already exists.

    Args:
        db:         Active database session.
        event_hash: SHA-256 hex digest of the event.

    Returns:
        True if a row with this hash exists (duplicate), False otherwise.
    """
    return db.query(Event.id).filter(Event.event_hash == event_hash).first() is not None
