"""Timestamp parsing for the platform export."""

from datetime import datetime


def parse_timestamp(text: str) -> datetime:
    """Parse an ISO 8601 timestamp with a UTC offset; naive timestamps raise ValueError."""
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timestamp without UTC offset: {text!r}")
    return value
