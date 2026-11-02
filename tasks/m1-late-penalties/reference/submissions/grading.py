"""Turning submissions into final grades."""

from typing import Dict, Iterable, Optional, Tuple

from .models import Assignment, Submission
from .policy import LatePolicy


def final_grades(submissions: Iterable[Submission], assignments: Dict[str, Assignment],
                 policy: LatePolicy, roster: Optional[Iterable[str]] = None) -> Dict[Tuple[str, str], float]:
    """Best penalty-adjusted score per (student_id, assignment), rounded to 2 decimals."""
    best: Dict[Tuple[str, str], float] = {}
    for sub in submissions:
        if sub.assignment not in assignments:
            raise ValueError(f"unknown assignment: {sub.assignment}")
        a = assignments[sub.assignment]
        if sub.score < 0 or sub.score > a.max_score:
            raise ValueError(f"score {sub.score} out of range for {a.name}")
        adjusted = sub.score * (1 - policy.penalty(sub.submitted_at, a.deadline))
        key = (sub.student_id, sub.assignment)
        best[key] = max(best.get(key, adjusted), adjusted)
    if roster is not None:
        for student in roster:
            for name in assignments:
                best.setdefault((student, name), 0.0)
    return {key: round(value, 2) for key, value in best.items()}
