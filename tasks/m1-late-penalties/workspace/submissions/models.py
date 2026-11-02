"""Plain data objects."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Submission:
    student_id: str
    name: str
    assignment: str
    submitted_at: datetime
    score: float


@dataclass(frozen=True)
class Assignment:
    name: str
    deadline: datetime
    max_score: float
