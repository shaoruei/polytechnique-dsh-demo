"""Late-submission policy."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

_DAY = timedelta(days=1)


@dataclass(frozen=True)
class LatePolicy:
    grace_minutes: int = 15
    penalty_per_day: float = 0.10
    max_penalty: float = 0.50
    zero_after_days: int = 7

    def penalty(self, submitted_at: datetime, deadline: datetime) -> float:
        """Fraction of the score removed for a late submission (see SPEC.md)."""
        late_by = submitted_at - deadline
        if late_by <= timedelta(minutes=self.grace_minutes):
            return 0.0
        if late_by > timedelta(days=self.zero_after_days):
            return 1.0
        days_late = math.ceil(late_by / _DAY)
        return min(days_late * self.penalty_per_day, self.max_penalty)
