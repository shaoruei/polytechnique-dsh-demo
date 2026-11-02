"""Late-submission policy."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LatePolicy:
    grace_minutes: int = 15
    penalty_per_day: float = 0.10
    max_penalty: float = 0.50
    zero_after_days: int = 7

    def penalty(self, submitted_at: datetime, deadline: datetime) -> float:
        """Fraction of the score removed for a late submission (see SPEC.md)."""
        return 0.0
