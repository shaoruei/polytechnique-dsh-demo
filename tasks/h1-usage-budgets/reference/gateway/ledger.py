"""In-memory usage ledger."""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Tuple

from .upstream import Usage


@dataclass(frozen=True)
class Entry:
    user_id: str
    month: str  # "YYYY-MM"
    model: str
    usage: Usage
    cost: Decimal
    status: str  # "ok" or "failed_attempt"


class Ledger:
    def __init__(self):
        self.entries: List[Entry] = []

    def record(self, entry: Entry) -> None:
        self.entries.append(entry)

    def _of(self, user_id: str, month: str):
        return [e for e in self.entries if e.user_id == user_id and e.month == month]

    def spent(self, user_id: str, month: str) -> Decimal:
        return sum((e.cost for e in self._of(user_id, month)), Decimal("0"))

    def usage_report(self, user_id: str, month: str) -> dict:
        es = self._of(user_id, month)
        return {
            "requests": sum(1 for e in es if e.status == "ok"),
            "failed_attempts": sum(1 for e in es if e.status == "failed_attempt"),
            "prompt_tokens": sum(e.usage.prompt_tokens for e in es),
            "cached_tokens": sum(e.usage.cached_tokens for e in es),
            "completion_tokens": sum(e.usage.completion_tokens for e in es),
            "cost_usd": sum((e.cost for e in es), Decimal("0")),
        }

    def top_spenders(self, month: str, n: int) -> List[Tuple[str, Decimal]]:
        totals = {}
        for e in self.entries:
            if e.month == month:
                totals[e.user_id] = totals.get(e.user_id, Decimal("0")) + e.cost
        ranked = sorted(((u, c) for u, c in totals.items() if c > 0), key=lambda uc: (-uc[1], uc[0]))
        return ranked[:n]
