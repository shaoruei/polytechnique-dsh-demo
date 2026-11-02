"""Turning submissions into final grades."""

from typing import Dict, Iterable, Optional, Tuple

from .models import Assignment, Submission
from .policy import LatePolicy


def final_grades(submissions: Iterable[Submission], assignments: Dict[str, Assignment],
                 policy: LatePolicy, roster: Optional[Iterable[str]] = None) -> Dict[Tuple[str, str], float]:
    """Final score per (student_id, assignment); the latest submission counts."""
    latest: Dict[Tuple[str, str], Submission] = {}
    for sub in submissions:
        key = (sub.student_id, sub.assignment)
        if key not in latest or sub.submitted_at > latest[key].submitted_at:
            latest[key] = sub
    return {key: round(sub.score, 2) for key, sub in latest.items()}
