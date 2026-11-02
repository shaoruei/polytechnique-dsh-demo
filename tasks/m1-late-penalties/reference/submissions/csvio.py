"""Reading the learning platform's CSV exports."""

import csv
import io
from typing import Dict, Iterator, List, Tuple

from .models import Assignment, Submission
from .timeparse import parse_timestamp


def _rows(text: str, width: int) -> Iterator[Tuple[int, List[str]]]:
    reader = csv.reader(io.StringIO(text))
    for index, row in enumerate(reader, start=1):
        if index == 1 or not any(field.strip() for field in row):
            continue
        if len(row) != width:
            raise ValueError(f"line {reader.line_num}: expected {width} fields, got {len(row)}")
        yield reader.line_num, [field.strip() for field in row]


def _number(text: str, line: int) -> float:
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"line {line}: invalid number {text!r}") from None


def _timestamp(text: str, line: int):
    try:
        return parse_timestamp(text)
    except ValueError as exc:
        raise ValueError(f"line {line}: {exc}") from None


def read_submissions(text: str) -> List[Submission]:
    """Parse the submissions export (header: student_id,name,assignment,submitted_at,score)."""
    out = []
    for line, (student_id, name, assignment, submitted_at, score) in _rows(text, 5):
        out.append(Submission(student_id, name, assignment, _timestamp(submitted_at, line), _number(score, line)))
    return out


def read_assignments(text: str) -> Dict[str, Assignment]:
    """Parse the assignments file (header: assignment,deadline,max_score)."""
    out = {}
    for line, (name, deadline, max_score) in _rows(text, 3):
        out[name] = Assignment(name, _timestamp(deadline, line), _number(max_score, line))
    return out
