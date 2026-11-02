import unittest
from datetime import datetime, timezone
from decimal import Decimal

from gateway import Gateway, Ledger, ScriptedUpstream, Usage, User, UserDirectory, request_cost
from gateway.upstream import Completion

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
MODEL = "openai/gpt-oss-120b"


def make(outcomes):
    directory = UserDirectory([User("alice", "student"), User("prof", "staff")])
    upstream = ScriptedUpstream(outcomes)
    return Gateway(directory, upstream, Ledger(), clock=lambda: NOW), upstream


def req(user="alice", **kw):
    return {"user": user, "model": MODEL, "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1000, "input_tokens": 2000, **kw}


class PricingTest(unittest.TestCase):
    def test_uncached_only(self):
        self.assertEqual(request_cost(MODEL, Usage(1_000_000, 0, 0)), Decimal("0.150000"))

    def test_cached_tokens_use_cached_price(self):
        self.assertEqual(request_cost(MODEL, Usage(1000, 800, 100)), Decimal("0.000170"))


class GatewayTest(unittest.TestCase):
    def test_success_returns_cost(self):
        gw, up = make([Completion("ok", Usage(1000, 800, 100))])
        r = gw.handle(req())
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body["cost_usd"], "0.000170")
        self.assertEqual(len(up.calls), 1)

    def test_unknown_model(self):
        gw, up = make([])
        r = gw.handle(req(model="nope"))
        self.assertEqual((r.status, r.body), (400, {"error": "unknown_model"}))
        self.assertEqual(up.calls, [])


if __name__ == "__main__":
    unittest.main()
