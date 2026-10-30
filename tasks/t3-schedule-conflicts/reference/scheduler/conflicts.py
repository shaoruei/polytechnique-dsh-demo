"""Detection of timetable clashes."""

from typing import List, Sequence, Tuple

from .models import Session


def _shares_resource(a: Session, b: Session) -> bool:
    return a.room == b.room or bool(a.groups & b.groups)


def find_conflicts(sessions: Sequence[Session]) -> List[Tuple[Session, Session]]:
    """Return every pair of sessions that clash (same room or group, overlapping time)."""
    conflicts = []
    for i, a in enumerate(sessions):
        for b in sessions[i + 1:]:
            if a.overlaps(b) and _shares_resource(a, b):
                conflicts.append((a, b))
    return conflicts
