"""Weighted grade computation for a course grade book."""

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class GradedItem:
    name: str
    weight: float
    score: Optional[float]  # 0..20 scale, None when not graded yet


def final_grade(items: Iterable[GradedItem]) -> Optional[float]:
    """Return the weighted average score (0..20) rounded to 2 decimals.

    Items whose score is None are ignored. Returns None if nothing is graded.
    """
    items = list(items)
    total = 0.0
    for item in items:
        total += item.weight * (item.score or 0)
    weight_sum = sum(item.weight for item in items)
    return round(total, 2) if weight_sum == 1 else round(total / len(items), 2)


def letter_grade(score: Optional[float]) -> str:
    """Map a 0..20 score to a letter grade."""
    if score is None:
        return "N/A"
    if score >= 16:
        return "A"
    if score >= 14:
        return "B"
    if score >= 12:
        return "C"
    if score >= 10:
        return "D"
    return "F"
