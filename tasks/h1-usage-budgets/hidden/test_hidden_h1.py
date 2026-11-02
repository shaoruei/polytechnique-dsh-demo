"""Hidden acceptance tests for H1 (never shown to the agent). Expected values computed by hand."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from gateway import (Gateway, Ledger, ScriptedUpstream, UnknownModel, UnknownUser, UpstreamError, Usage, User,
                     UserDirectory, request_cost)
from gateway.upstream import Completion

M = "openai/gpt-oss-120b"
NOV = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def ok(p=1000, c=0, o=100, text="ok"):
    return Completion(text, Usage(p, c, o))


def err(retryable=True, usage=None):
    return UpstreamError("boom", retryable=retryable, usage=usage)


def setup(outcomes, clock=None):
    d = UserDirectory([User("alice", "student"), User("bob", "student"), User("tara", "ta"), User("prof", "staff")])
    up = ScriptedUpstream(outcomes)
    ledger = Ledger()
    return Gateway(d, up, ledger, clock=clock or Clock(NOV)), up, ledger, d


def req(user="alice", model=M, max_tokens=1000, input_tokens=2000, **kw):
    return {"user": user, "model": model, "messages": [{"role": "user", "content": "x"}],
            "max_tokens": max_tokens, "input_tokens": input_tokens, **kw}


class R1Pricing(unittest.TestCase):
    def test_formula_and_second_model(self):
        self.assertEqual(request_cost(M, Usage(10_000, 6_000, 2_000)), Decimal("0.002400"))  # 600+600+1200 micro
        self.assertEqual(request_cost("qwen/qwen3-coder-30b", Usage(10_000, 6_000, 2_000)), Decimal("0.001300"))

    def test_rounding_half_up(self):
        self.assertEqual(request_cost(M, Usage(3, 0, 0)), Decimal("0.000000"))   # 0.45 micro
        self.assertEqual(request_cost(M, Usage(5, 5, 0)), Decimal("0.000001"))   # 0.5 micro -> up
        self.assertEqual(request_cost(M, Usage(4, 0, 0)), Decimal("0.000001"))   # 0.6 micro

    def test_unknown_model_raises(self):
        with self.assertRaises(UnknownModel):
            request_cost("nope", Usage(1, 0, 1))


class R3Budgets(unittest.TestCase):
    def test_roles_overrides_unknown(self):
        _, _, _, d = setup([])
        self.assertEqual((d.budget("alice"), d.budget("tara"), d.budget("prof")), (Decimal("5.00"), Decimal("20.00"), None))
        d.set_budget("alice", Decimal("1.50"))
        d.set_budget("prof", Decimal("2"))
        d.set_budget("tara", None)
        self.assertEqual((d.budget("alice"), d.budget("prof"), d.budget("tara")), (Decimal("1.50"), Decimal("2"), None))
        with self.assertRaises(UnknownUser):
            d.budget("mallory")


class R4Handling(unittest.TestCase):
    def test_unknown_user_and_model_do_not_call_provider(self):
        gw, up, _, _ = setup([])
        self.assertEqual((gw.handle(req(user="mallory")).status, gw.handle(req(user="mallory")).body), (403, {"error": "unknown_user"}))
        self.assertEqual(gw.handle(req(model="x")).status, 400)
        self.assertEqual(up.calls, [])

    def test_admission_exact_budget_allowed_then_rejected(self):
        # worst case: 2000 uncached * 0.15 + 1000 * 0.60 = 900 micro
        gw, up, ledger, d = setup([ok(1000, 0, 100)])
        d.set_budget("alice", Decimal("0.000900"))
        self.assertEqual(gw.handle(req()).status, 200)          # 0 + 900 <= 900
        spent = ledger.spent("alice", "2026-11")               # 150 + 60 = 210 micro
        self.assertEqual(spent, Decimal("0.000210"))
        r = gw.handle(req())
        self.assertEqual((r.status, r.body), (402, {"error": "budget_exceeded", "remaining": "0.000690"}))
        self.assertEqual(len(up.calls), 1)

    def test_months_are_separate_and_utc(self):
        clock = Clock(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc))
        gw, _, ledger, d = setup([ok(), ok()], clock)
        d.set_budget("alice", Decimal("0.01"))
        gw.handle(req())
        clock.t = datetime(2026, 11, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))  # = 2026-10-31T22:30Z, still October
        gw.handle(req())
        self.assertEqual(ledger.usage_report("alice", "2026-10")["requests"], 2)
        clock.t = datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(ledger.spent("alice", "2026-11"), Decimal("0"))

    def test_retry_until_success(self):
        gw, up, _, _ = setup([err(), err(), ok()])
        r = gw.handle(req())
        self.assertEqual(r.status, 200)
        self.assertEqual(len(up.calls), 3)

    def test_gives_up_after_three_attempts(self):
        gw, up, _, _ = setup([err(), err(), err(), ok()])
        r = gw.handle(req())
        self.assertEqual((r.status, r.body), (502, {"error": "upstream_failed", "attempts": 3}))
        self.assertEqual(len(up.calls), 3)

    def test_non_retryable_not_retried(self):
        gw, up, _, _ = setup([err(retryable=False), ok()])
        self.assertEqual(gw.handle(req()).body, {"error": "upstream_failed", "attempts": 1})
        self.assertEqual(len(up.calls), 1)

    def test_failed_attempts_with_usage_are_charged(self):
        billed = Usage(4000, 0, 500)   # 600 + 300 = 900 micro
        gw, _, ledger, _ = setup([err(usage=billed), ok(1000, 0, 100)])
        r = gw.handle(req())
        self.assertEqual(r.body["cost_usd"], "0.000210")
        rep = ledger.usage_report("alice", "2026-11")
        self.assertEqual((rep["requests"], rep["failed_attempts"], rep["cost_usd"]), (1, 1, Decimal("0.001110")))
        self.assertEqual((rep["prompt_tokens"], rep["completion_tokens"]), (5000, 600))

    def test_failed_request_still_charges_billed_attempts(self):
        gw, _, ledger, _ = setup([err(usage=Usage(1000, 0, 0)), err(retryable=False)])
        self.assertEqual(gw.handle(req()).status, 502)
        self.assertEqual(ledger.spent("alice", "2026-11"), Decimal("0.000150"))

    def test_budget_headers(self):
        gw, _, _, d = setup([ok(1000, 0, 1000), ok(1000, 0, 1000), ok()])
        d.set_budget("alice", Decimal("0.002"))     # each call: 150 + 600 = 750 micro
        h1 = gw.handle(req()).headers               # spent 750 = 37.5%
        self.assertEqual(h1.get("X-Budget-Remaining"), "0.001250")
        self.assertNotIn("X-Budget-Warning", h1)
        h2 = gw.handle(req()).headers               # spent 1500 = 75%
        self.assertNotIn("X-Budget-Warning", h2)
        d.set_budget("alice", Decimal("0.0018"))
        h3 = gw.handle(req(max_tokens=100, input_tokens=1000)).headers  # worst 210; spent 1710 = 95%
        self.assertEqual((h3.get("X-Budget-Remaining"), h3.get("X-Budget-Warning")), ("0.000090", "80%"))

    def test_budget_warning_100_and_floor(self):
        gw, _, _, d = setup([ok(1000, 0, 1000)])
        d.set_budget("alice", Decimal("0.000750"))
        h = gw.handle(req(input_tokens=1000)).headers   # worst 750 <= 750; spent 750
        self.assertEqual((h.get("X-Budget-Remaining"), h.get("X-Budget-Warning")), ("0.000000", "100%"))

    def test_unlimited_users_get_no_budget_headers(self):
        gw, _, _, _ = setup([ok()])
        r = gw.handle(req(user="prof", max_tokens=10**9))
        self.assertEqual(r.status, 200)
        self.assertNotIn("X-Budget-Remaining", r.headers)
        self.assertNotIn("X-Budget-Warning", r.headers)

    def test_idempotent_replay(self):
        gw, up, ledger, _ = setup([ok(text="first"), ok(text="second"), ok(text="third")])
        a = gw.handle(req(request_id="r1"))
        b = gw.handle(req(request_id="r1"))
        self.assertEqual(b.body, a.body)
        self.assertEqual(b.headers.get("X-Idempotent-Replay"), "true")
        self.assertNotIn("X-Idempotent-Replay", a.headers)
        self.assertEqual(len(up.calls), 1)
        self.assertEqual(ledger.usage_report("alice", "2026-11")["requests"], 1)
        self.assertEqual(gw.handle(req(user="bob", request_id="r1")).body["content"], "second")
        self.assertEqual(gw.handle(req(request_id="r2")).body["content"], "third")

    def test_failed_requests_are_not_stored(self):
        gw, up, _, _ = setup([err(retryable=False), ok(text="later")])
        self.assertEqual(gw.handle(req(request_id="r9")).status, 502)
        r = gw.handle(req(request_id="r9"))
        self.assertEqual((r.status, r.body["content"]), (200, "later"))
        self.assertNotIn("X-Idempotent-Replay", r.headers)


class R5Reports(unittest.TestCase):
    def test_usage_report_and_top_spenders(self):
        gw, _, ledger, _ = setup([ok(1000, 500, 100), ok(2000, 0, 0), ok(10, 0, 0), ok(1000, 0, 100)])
        gw.handle(req(user="alice"))   # 75+50+60 = 185 micro
        gw.handle(req(user="bob"))     # 300 micro
        gw.handle(req(user="tara"))    # 1.5 micro -> 0.000002
        gw.handle(req(user="prof"))    # 210 micro
        rep = ledger.usage_report("alice", "2026-11")
        self.assertEqual(rep, {"requests": 1, "failed_attempts": 0, "prompt_tokens": 1000, "cached_tokens": 500,
                               "completion_tokens": 100, "cost_usd": Decimal("0.000185")})
        self.assertEqual(ledger.top_spenders("2026-11", 3),
                         [("bob", Decimal("0.000300")), ("prof", Decimal("0.000210")), ("alice", Decimal("0.000185"))])
        self.assertEqual(ledger.top_spenders("2026-10", 3), [])

    def test_ties_and_zero_cost_omitted(self):
        gw, _, ledger, _ = setup([ok(1000, 0, 0), ok(1000, 0, 0), ok(1, 0, 0)])
        gw.handle(req(user="bob"))
        gw.handle(req(user="alice"))
        gw.handle(req(user="tara"))    # 0.15 micro -> 0.000000
        self.assertEqual(ledger.top_spenders("2026-11", 10), [("alice", Decimal("0.000150")), ("bob", Decimal("0.000150"))])


if __name__ == "__main__":
    unittest.main()
