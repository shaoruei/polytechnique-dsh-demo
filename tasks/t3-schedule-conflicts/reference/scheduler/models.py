"""Timetable data model."""

from dataclasses import dataclass, field
from typing import FrozenSet

from .timeparse import to_minutes

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Session:
    course: str
    day: str
    start: str  # "HH:MM"
    end: str    # "HH:MM"
    room: str
    groups: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if self.day not in DAYS:
            raise ValueError(f"unknown day: {self.day!r}")
        if self.end_minutes <= self.start_minutes:
            raise ValueError("session must end after it starts")

    @property
    def start_minutes(self) -> int:
        return to_minutes(self.start)

    @property
    def end_minutes(self) -> int:
        return to_minutes(self.end)

    def overlaps(self, other: "Session") -> bool:
        """True when the two sessions' time intervals overlap."""
        return (
            self.day == other.day
            and self.start_minutes < other.end_minutes
            and other.start_minutes < self.end_minutes
        )
