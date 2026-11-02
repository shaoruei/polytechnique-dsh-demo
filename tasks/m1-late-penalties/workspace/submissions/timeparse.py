"""Timestamp parsing for the platform export."""

from datetime import datetime


def parse_timestamp(text: str) -> datetime:
    """Parse an ISO 8601 timestamp such as 2026-10-12T23:59:00+02:00."""
    return datetime.fromisoformat(text.strip())
