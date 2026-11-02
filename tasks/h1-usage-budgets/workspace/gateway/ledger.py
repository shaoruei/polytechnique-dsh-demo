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

    def spent(self, user_id: str, month: str) -> Decimal:
        return sum((e.cost for e in self.entries if e.user_id == user_id), Decimal("0"))

    def usage_report(self, user_id: str, month: str) -> dict:
        raise NotImplementedError

    def top_spenders(self, month: str, n: int) -> List[Tuple[str, Decimal]]:
        raise NotImplementedError
