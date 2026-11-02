"""Users, roles and budgets."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional


class UnknownUser(KeyError):
    pass


ROLE_BUDGETS: Dict[str, Optional[Decimal]] = {
    "student": Decimal("5.00"),
    "ta": Decimal("20.00"),
    "staff": None,  # unlimited
}


@dataclass(frozen=True)
class User:
    user_id: str
    role: str


class UserDirectory:
    def __init__(self, users=()):
        self._users: Dict[str, User] = {u.user_id: u for u in users}
        self._overrides: Dict[str, Optional[Decimal]] = {}

    def add(self, user: User) -> None:
        self._users[user.user_id] = user

    def get(self, user_id: str) -> User:
        return self._users[user_id]

    def set_budget(self, user_id: str, budget: Optional[Decimal]) -> None:
        """Per-user monthly budget override (None = unlimited)."""
        self._overrides[user_id] = budget

    def budget(self, user_id: str) -> Optional[Decimal]:
        return ROLE_BUDGETS[self.get(user_id).role]
