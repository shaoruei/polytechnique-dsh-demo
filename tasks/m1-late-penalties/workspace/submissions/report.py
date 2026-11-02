"""Plain-text grade report."""

from typing import Dict, Tuple


def format_report(grades: Dict[Tuple[str, str], float]) -> str:
    """One line per student: id followed by assignment=score pairs, sorted."""
    by_student: Dict[str, Dict[str, float]] = {}
    for (student, assignment), score in grades.items():
        by_student.setdefault(student, {})[assignment] = score
    lines = []
    for student in sorted(by_student):
        parts = " ".join(f"{a}={s:.2f}" for a, s in sorted(by_student[student].items()))
        lines.append(f"{student} {parts}")
    return "\n".join(lines)
