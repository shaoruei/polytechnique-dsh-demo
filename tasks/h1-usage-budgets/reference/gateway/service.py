"""Request handling."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Dict, Tuple

from .ledger import Entry, Ledger
from .pricing import UnknownModel, fmt, price_of, request_cost
from .upstream import Upstream, UpstreamError, Usage
from .users import UnknownUser, UserDirectory

MAX_ATTEMPTS = 3


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
        self._replies: Dict[Tuple[str, str], Response] = {}

    def handle(self, request: dict) -> Response:
        user_id, model = request.get("user"), request.get("model")
        try:
            self.directory.get(user_id)
        except UnknownUser:
            return Response(403, {"error": "unknown_user"})
        try:
            price_of(model)
        except UnknownModel:
            return Response(400, {"error": "unknown_model"})

        rid = request.get("request_id")
        if rid is not None and (user_id, rid) in self._replies:
            stored = self._replies[(user_id, rid)]
            return Response(stored.status, dict(stored.body), {**stored.headers, "X-Idempotent-Replay": "true"})

        month = self.clock().astimezone(timezone.utc).strftime("%Y-%m")
        budget = self.directory.budget(user_id)
        if budget is not None:
            worst = request_cost(model, Usage(int(request.get("input_tokens", 0)), 0, int(request.get("max_tokens", 0))))
            spent = self.ledger.spent(user_id, month)
            if spent + worst > budget:
                return Response(402, {"error": "budget_exceeded", "remaining": fmt(max(budget - spent, Decimal("0")))})

        attempts = 0
        completion = None
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                completion = self.upstream(request)
                break
            except UpstreamError as err:
                if err.usage is not None:
                    self.ledger.record(Entry(user_id, month, model, err.usage, request_cost(model, err.usage), "failed_attempt"))
                if not err.retryable:
                    break
        if completion is None:
            return Response(502, {"error": "upstream_failed", "attempts": attempts})

        usage = completion.usage
        cost = request_cost(model, usage)
        self.ledger.record(Entry(user_id, month, model, usage, cost, "ok"))
        headers = {}
        if budget is not None:
            spent = self.ledger.spent(user_id, month)
            headers["X-Budget-Remaining"] = fmt(max(budget - spent, Decimal("0")))
            if spent >= budget:
                headers["X-Budget-Warning"] = "100%"
            elif spent >= budget * Decimal("0.8"):
                headers["X-Budget-Warning"] = "80%"
        response = Response(200, {
            "content": completion.content,
            "usage": {"prompt_tokens": usage.prompt_tokens, "cached_tokens": usage.cached_tokens,
                      "completion_tokens": usage.completion_tokens},
            "cost_usd": fmt(cost),
        }, headers)
        if rid is not None:
            self._replies[(user_id, rid)] = response
        return response
