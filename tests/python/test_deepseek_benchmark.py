"""Tests for harness/benchmark_deepseek_endpoints.py. Offline: a local fake OpenAI-compatible server."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
import benchmark_deepseek_endpoints as bm  # noqa: E402


class FakeServer:
    """Minimal HTTP/1.1 keep-alive server speaking the streaming chat-completions protocol.

    mode: 'ok' streams `max_tokens` one-token chunks; '429' answers 429 with Retry-After;
    'ratelimit_after:N' answers ok for the first N requests then 429; 'close_after_one' closes the
    connection after each response (stale keep-alive); 'wrong_model' answers with another model id.
    """

    def __init__(self, mode="ok", model="m", delay=0.0):
        self.mode, self.model, self.delay = mode, model, delay
        self.requests = []
        self.server = None

    async def handle(self, reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                headers = {}
                while True:
                    h = await reader.readline()
                    if h in (b"\r\n", b""):
                        break
                    k, _, v = h.decode().partition(":")
                    headers[k.strip().lower()] = v.strip()
                body = json.loads(await reader.readexactly(int(headers["content-length"])))
                self.requests.append({"headers": headers, "body": body})
                n = len(self.requests)
                limited = self.mode == "429" or (self.mode.startswith("ratelimit_after:") and n > int(self.mode.split(":")[1]))
                if limited:
                    payload = b'{"error":{"message":"rate limited"}}'
                    writer.write(b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nRetry-After: 2\r\n"
                                 b"x-ratelimit-remaining-requests: 0\r\nx-ratelimit-limit-requests: 10\r\n"
                                 b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
                    await writer.drain()
                    continue
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n"
                             b"x-ratelimit-remaining-requests: 999\r\nx-ratelimit-limit-tokens: 2000000\r\n"
                             b"x-request-id: abc\r\nset-cookie: secret=1\r\n\r\n")
                model = "other" if self.mode == "wrong_model" else body["model"]
                n_out = body["max_tokens"]
                chunks = []
                for i in range(n_out):
                    chunks.append({"model": model, "choices": [{"index": 0, "delta": {"content": "x"},
                                                                 "finish_reason": "length" if i == n_out - 1 else None}]})
                prompt_tokens = len(json.dumps(body["messages"])) // 4
                chunks.append({"model": model, "choices": [], "usage": {"prompt_tokens": prompt_tokens,
                               "completion_tokens": n_out, "prompt_cache_hit_tokens": 0}})
                for c in chunks:
                    if self.delay:
                        await asyncio.sleep(self.delay)
                    # split an SSE event across two HTTP chunks to exercise buffering
                    data = f"data: {json.dumps(c)}\n\n".encode()
                    for part in (data[:7], data[7:]):
                        writer.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                d = b"data: [DONE]\n\n"
                writer.write(f"{len(d):x}\r\n".encode() + d + b"\r\n0\r\n\r\n")
                await writer.drain()
                if self.mode == "close_after_one":
                    break
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    def endpoint(self, billing="per_token"):
        return {"name": "fake", "origin": f"http://127.0.0.1:{self.port}", "model": self.model, "billing": billing}


class TestPrompts(unittest.TestCase):
    def test_deterministic_and_unique(self):
        m1, meta1 = bm.make_request_prompt("A", 3, "s")
        m2, meta2 = bm.make_request_prompt("A", 3, "s")
        m3, meta3 = bm.make_request_prompt("A", 4, "s")
        self.assertEqual(m1, m2)
        self.assertEqual(meta1, meta2)
        self.assertNotEqual(meta1["prompt_sha256"], meta3["prompt_sha256"])
        # unique header at the start of the user message prevents prefix-cache reuse between requests
        self.assertNotEqual(m1[1]["content"][:40], m3[1]["content"][:40])

    def test_sizes_within_profile(self):
        for prof in ("A", "B", "Bc"):
            lo, hi = bm.PROFILES[prof]["input_tokens"]
            for i in range(20):
                _, meta = bm.make_request_prompt(prof, i)
                self.assertTrue(lo <= meta["target_input_tokens"] <= hi)
                est_tokens = meta["prompt_chars"] / bm.CHARS_PER_TOKEN
                self.assertTrue(0.8 * lo <= est_tokens <= 1.1 * hi, (prof, i, est_tokens))

    def test_shared_prefix_profile(self):
        a, _ = bm.make_request_prompt("Bc", 1)
        b, _ = bm.make_request_prompt("Bc", 2)
        ua, ub = a[1]["content"], b[1]["content"]
        common = next(i for i, (x, y) in enumerate(zip(ua, ub)) if x != y)
        self.assertGreater(common / len(ua), 0.6)

    def test_request_body_controls_output(self):
        msgs, _ = bm.make_request_prompt("B", 0)
        body = bm.request_body("m", "B", msgs)
        self.assertEqual(body["max_tokens"], 512)
        self.assertTrue(body["ignore_eos"] and body["stream"])
        self.assertEqual(body["chat_template_kwargs"], {"thinking": False})
        self.assertEqual(body["temperature"], 0)


class TestStats(unittest.TestCase):
    def test_percentile_matches_numpy_linear(self):
        xs = [5, 1, 3, 2, 4]
        self.assertEqual(bm.percentile(xs, 50), 3)
        self.assertAlmostEqual(bm.percentile(xs, 95), 4.8)
        self.assertIsNone(bm.percentile([], 50))

    def test_bootstrap_ci_contains_estimate(self):
        xs = list(range(100))
        lo, hi = bm.bootstrap_ci(xs, 95)
        self.assertLessEqual(lo, bm.percentile(xs, 95))
        self.assertGreaterEqual(hi, bm.percentile(xs, 95) - 1)
        self.assertIsNone(bm.bootstrap_ci([1, 2], 95))

    def test_dist_flags_small_samples(self):
        self.assertFalse(bm.dist(list(range(10)))["p95_reliable"])
        self.assertTrue(bm.dist(list(range(40)))["p95_reliable"])

    def test_public_cost(self):
        # 10k prompt (9k cached) + 512 output
        c = bm.public_cost_usd(10_000, 512, 9_000)
        self.assertAlmostEqual(c, (1000 * 0.14 + 9000 * 0.01 + 512 * 0.28) / 1e6)

    def test_sse_buffering(self):
        buf = bytearray()
        self.assertEqual(list(bm._sse_events(buf, b"data: {\"a\"")), [])
        self.assertEqual(list(bm._sse_events(buf, b":1}\r\n\r\ndata: [DONE]\n")), ['{"a":1}', "[DONE]"])

    def test_poisson_schedule_rate_and_determinism(self):
        s1 = bm.poisson_schedule(600, 60, "x")
        self.assertEqual(s1, bm.poisson_schedule(600, 60, "x"))
        self.assertTrue(500 < len(s1) < 700)
        self.assertTrue(all(0 < t < 60 for t in s1))


class TestClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_streaming_request_record(self):
        async def go():
            async with FakeServer() as srv:
                pool = bm.Pool(srv.endpoint()["origin"])
                rec = await bm.do_request(pool, srv.endpoint(), "A", 1, "t", 0.0, 10)
                rec2 = await bm.do_request(pool, srv.endpoint(), "A", 2, "t", 0.0, 10)
                pool.close()
                return rec, rec2, srv.requests
        rec, rec2, reqs = self.run_async(go())
        self.assertEqual(rec["error_category"], "ok")
        self.assertEqual(rec["completion_tokens"], 256)
        self.assertIsNotNone(rec["ttft_s"])
        self.assertEqual(rec["finish_reason"], "length")
        self.assertTrue(rec["new_connection"])
        self.assertFalse(rec2["new_connection"])  # keep-alive reuse
        # sanitisation: only rate-limit / request-id headers kept, no prompt text, no auth
        self.assertEqual(set(rec["headers"]), {"x-ratelimit-remaining-requests", "x-ratelimit-limit-tokens", "x-request-id"})
        dumped = json.dumps(rec)
        self.assertNotIn("Bearer", dumped)
        self.assertNotIn("Request t-A-000001", dumped)
        self.assertIn("est_cost_usd", rec)
        self.assertTrue(reqs[0]["headers"]["authorization"].startswith("Bearer "))

    def test_stale_connection_reopened(self):
        async def go():
            async with FakeServer(mode="close_after_one") as srv:
                pool = bm.Pool(srv.endpoint()["origin"])
                a = await bm.do_request(pool, srv.endpoint(), "R", 1, "t", 0.0, 10)
                await asyncio.sleep(0.05)
                b = await bm.do_request(pool, srv.endpoint(), "R", 2, "t", 0.0, 10)
                pool.close()
                return a, b, len(srv.requests)
        a, b, n = self.run_async(go())
        self.assertEqual(a["error_category"], "ok")
        self.assertEqual(b["error_category"], "ok")
        self.assertEqual(n, 2)  # each request reached the server exactly once

    def test_429_and_model_mismatch_categories(self):
        async def go(mode):
            async with FakeServer(mode=mode) as srv:
                pool = bm.Pool(srv.endpoint()["origin"])
                r = await bm.do_request(pool, srv.endpoint(), "R", 1, "t", 0.0, 10)
                pool.close()
                return r
        r = self.run_async(go("429"))
        self.assertEqual(r["error_category"], "http_429")
        self.assertEqual(r["headers"]["retry-after"], "2")
        self.assertIn("rate limited", r["error_detail"])
        self.assertEqual(self.run_async(go("wrong_model"))["error_category"], "model_mismatch")

    def test_timeout_category(self):
        async def go():
            async with FakeServer(delay=0.05) as srv:
                pool = bm.Pool(srv.endpoint()["origin"])
                r = await bm.do_request(pool, srv.endpoint(), "A", 1, "t", 0.0, 0.3)
                pool.close()
                return r
        self.assertEqual(self.run_async(go())["error_category"], "timeout")

    def test_connect_error(self):
        ep = {"name": "x", "origin": "http://127.0.0.1:9", "model": "m", "billing": "per_token"}

        async def go():
            pool = bm.Pool(ep["origin"])
            return await bm.do_request(pool, ep, "R", 1, "t", 0.0, 5)
        self.assertEqual(self.run_async(go())["error_category"], "connect_error")

    def test_closed_loop_warmup_and_counts(self):
        async def go():
            async with FakeServer() as srv:
                w = bm.PhaseWriter("p1", self.out)
                res = await bm.run_closed_loop(srv.endpoint("per_gpu_hour"), "R", 3, 12, salt="t", index_base=0,
                                               timeout_s=10, max_seconds=30, phase_id="p1", writer=w, ledger=None)
                w.close()
                return res, len(srv.requests)
        res, n = self.run_async(go())
        recs = res["records"]
        self.assertEqual(n, 15)
        self.assertEqual(sum(r["warmup"] for r in recs), 3)
        self.assertEqual(len({r["prompt_index"] for r in recs}), 15)  # no prompt reused
        s = bm.summarize_group(recs)
        self.assertEqual(s["n_requests"], 12)
        self.assertEqual(s["n_ok"], 12)
        self.assertGreater(s["aggregate_output_tps"], 0)
        self.assertEqual(len((self.out / "raw" / "p1.jsonl").read_text().splitlines()), 15)

    def test_budget_cap_stops_issuing(self):
        async def go():
            async with FakeServer() as srv:
                ledger = bm.Ledger(self.out / "ledger.json", budget_usd=0.0002)
                w = bm.PhaseWriter("p2", self.out)
                res = await bm.run_closed_loop(srv.endpoint(), "A", 1, 50, salt="t", index_base=0, timeout_s=10,
                                               max_seconds=30, phase_id="p2", writer=w, ledger=ledger)
                w.close()
                return res, ledger
        res, ledger = self.run_async(go())
        self.assertEqual(res["stop_reason"], "budget_cap")
        self.assertLess(len(res["records"]), 5)
        self.assertTrue((self.out / "ledger.json").exists())

    def test_open_loop_aborts_on_sustained_429(self):
        async def go():
            async with FakeServer(mode="ratelimit_after:5") as srv:
                w = bm.PhaseWriter("p3", self.out)
                res = await bm.run_open_loop(srv.endpoint(), "R", 1200, 10, salt="t", index_base=0, timeout_s=5,
                                             phase_id="p3", writer=w, ledger=None)
                w.close()
                return res
        res = self.run_async(go())
        self.assertEqual(res["stop_reason"], "sustained_429")
        # stopped well before the ~200 scheduled arrivals
        self.assertLess(len(res["records"]), 60)
        s = bm.summarize_group(res["records"])
        self.assertGreater(s["rate_429"], 0.5)
        self.assertEqual(s["retry_after_values"], ["2"])
        self.assertIsNotNone(s["first_429_at_s"])

    def test_open_loop_rate(self):
        async def go():
            async with FakeServer() as srv:
                w = bm.PhaseWriter("p4", self.out)
                res = await bm.run_open_loop(srv.endpoint(), "R", 600, 3, salt="t", index_base=0, timeout_s=5,
                                             phase_id="p4", writer=w, ledger=None)
                w.close()
                return res
        res = self.run_async(go())
        self.assertIsNone(res["stop_reason"])
        self.assertEqual(len(res["records"]), res["scheduled"])
        self.assertLess(res["dispatch_lag_p99_s"], 0.1)

    def test_aggregate_excludes_smoke(self):
        bm.append_phase({"phase_id": "s", "kind": "smoke", "exclude_from_summary": True}, self.out)
        (self.out / "raw").mkdir(parents=True, exist_ok=True)
        rec = {"phase_id": "q", "experiment": "scaling", "endpoint": "public", "profile": "A", "concurrency": 2,
               "warmup": False, "error_category": "ok", "t_start": 0, "t_end": 2, "ttft_s": 0.5, "latency_s": 2,
               "completion_tokens": 256, "prompt_tokens": 3000, "cached_tokens": 0, "decode_tps": 170, "e2e_output_tps": 128}
        (self.out / "raw" / "q.jsonl").write_text(json.dumps(rec) + "\n")
        (self.out / "raw" / "s.jsonl").write_text(json.dumps({**rec, "phase_id": "s", "experiment": "smoke"}) + "\n")
        s = bm.aggregate(self.out)
        self.assertEqual(s["totals"]["requests"], 1)
        self.assertEqual(s["scaling"]["public"]["A"]["c=2"]["n_ok"], 1)


class TestCommittedResults(unittest.TestCase):
    """Committed raw files must be sanitised."""

    def test_no_secrets_or_prompts_in_results(self):
        d = ROOT / "data" / "deepseek_v4_endpoint_load"
        if not d.exists():
            self.skipTest("no results yet")
        for p in d.rglob("*.json*"):
            text = p.read_text()
            self.assertNotIn("Bearer", text, p)
            self.assertNotIn("authorization", text.lower(), p)
            self.assertNotIn("def load_", text, p)  # synthetic prompt code never stored
            self.assertNotIn("set-cookie", text.lower(), p)


if __name__ == "__main__":
    unittest.main()
