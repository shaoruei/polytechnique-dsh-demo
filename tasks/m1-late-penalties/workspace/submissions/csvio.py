"""Reading the learning platform's CSV exports."""

from typing import Dict, List

from .models import Assignment, Submission
from .timeparse import parse_timestamp


def _rows(text: str) -> List[List[str]]:
    lines = text.splitlines()
    return [line.split(",") for line in lines[1:]]


def read_submissions(text: str) -> List[Submission]:
    """Parse the submissions export (header: student_id,name,assignment,submitted_at,score)."""
    out = []
    for row in _rows(text):
        student_id, name, assignment, submitted_at, score = row
        out.append(Submission(student_id, name, assignment, parse_timestamp(submitted_at), float(score)))
    return out


def read_assignments(text: str) -> Dict[str, Assignment]:
    """Parse the assignments file (header: assignment,deadline,max_score)."""
    out = {}
    for name, deadline, max_score in _rows(text):
        out[name] = Assignment(name, parse_timestamp(deadline), float(max_score))
    return out
