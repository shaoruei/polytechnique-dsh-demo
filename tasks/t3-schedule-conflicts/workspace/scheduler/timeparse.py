"""Parsing of "HH:MM" clock times."""


def to_minutes(clock: str) -> int:
    """Convert "HH:MM" (24h clock) into minutes since midnight."""
    hours, minutes = clock.strip().split(":")
    h, m = int(hours), int(minutes)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"invalid clock time: {clock!r}")
    return h * 60 + m
