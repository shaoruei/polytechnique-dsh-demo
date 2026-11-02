"""Request handling."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict

from .ledger import Ledger
from .upstream import Upstream
from .users import UserDirectory


@dataclass
class Response:
    status: int
    body: dict
    headers: Dict[str, str] = field(default_factory=dict)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Gateway:
    def __init__(self, directory: UserDirectory, upstream: Upstream, ledger: Ledger,
                 clock: Callable[[], datetime] = _utc_now):
        self.directory = directory
        self.upstream = upstream
        self.ledger = ledger
        self.clock = clock

    def handle(self, request: dict) -> Response:
        completion = self.upstream(request)
        usage = completion.usage
        return Response(200, {
            "content": completion.content,
            "usage": {"prompt_tokens": usage.prompt_tokens, "cached_tokens": usage.cached_tokens,
                      "completion_tokens": usage.completion_tokens},
        })
