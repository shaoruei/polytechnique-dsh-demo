import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402
from sanitize import sanitize_text  # noqa: E402
from tofa_relay import ToolCallIndexRepair  # noqa: E402


def chunk(*tool_calls):
    return {"choices": [{"delta": {"tool_calls": list(tool_calls)}}]}


class RelayRepairTest(unittest.TestCase):
    def test_observed_tofa_stream_is_repaired(self):
        # Exact shape captured from Token Factory on 2026-10-30.
        r = ToolCallIndexRepair()
        seq = [
            chunk({"id": "chatcmpl-tool-1", "type": "function", "index": 0, "function": {"name": "read", "arguments": ""}}),
            chunk({"index": 0, "function": {"arguments": "{\"file_path\": \"a.py\""}}),
            chunk({"index": 1, "function": {"arguments": "\n}"}}),
        ]
        indices = [r.fix_chunk(c)["choices"][0]["delta"]["tool_calls"][0]["index"] for c in seq]
        self.assertEqual(indices, [0, 0, 0])
        self.assertEqual(r.repairs, 1)

    def test_genuine_parallel_calls_untouched(self):
        r = ToolCallIndexRepair()
        seq = [
            chunk({"id": "a", "index": 0, "function": {"name": "read", "arguments": "{}"}}),
            chunk({"id": "b", "index": 1, "function": {"name": "glob", "arguments": ""}}),
            chunk({"index": 1, "function": {"arguments": "{}"}}),
            chunk({"index": 0, "function": {"arguments": ""}}),
        ]
        indices = [r.fix_chunk(c)["choices"][0]["delta"]["tool_calls"][0]["index"] for c in seq]
        self.assertEqual(indices, [0, 1, 1, 0])
        self.assertEqual(r.repairs, 0)

    def test_non_tool_chunks_pass_through(self):
        r = ToolCallIndexRepair()
        c = {"choices": [{"delta": {"content": "hi"}}], "usage": {"prompt_tokens": 3}}
        self.assertEqual(r.fix_chunk(json.loads(json.dumps(c))), c)


class MetricsTest(unittest.TestCase):
    def test_cost_formula_matches_hand_calculation(self):
        # 1M uncached @0.15 + 1M cached @0.10 + 1M output @0.60
        self.assertAlmostEqual(metrics.cost_usd(1_000_000, 1_000_000, 1_000_000), 0.85)
        self.assertAlmostEqual(metrics.cost_usd(9970, 24944, 849), 0.0044993, places=7)

    def test_wire_requests(self):
        wire = [
            {"method": "GET", "path": "/v1/models", "status": 200},
            {"method": "POST", "path": "/v1/chat/completions", "status": 200, "t_recv": 100.0,
             "t_first_token": 100.5, "t_end": 101.5, "finish_reason": "tool_calls", "tool_index_repairs": 1,
             "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 800}}},
        ]
        reqs = metrics.requests_from_wire(wire)
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual((r["uncached_input_tokens"], r["cached_tokens"], r["completion_tokens"]), (200, 800, 200))
        self.assertEqual((r["ttft_s"], r["latency_s"], r["decode_tps"]), (0.5, 1.5, 200.0))

    def test_compute_aggregates(self):
        wire = [{"method": "POST", "path": "/v1/chat/completions", "status": 200, "t_recv": 0.0,
                 "t_first_token": 1.0, "t_end": 2.0,
                 "usage": {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 50}}}] * 2
        session = "\n".join(json.dumps(e) for e in [
            {"type": "tool/call", "seq": 1, "time": 1000, "data": {"callId": "x", "name": "bash", "step": 1}},
            {"type": "tool/result", "seq": 2, "time": 1500, "data": {"message": {"toolCallId": "x", "isError": False}}},
        ])
        m = metrics.compute(session, wire)
        self.assertEqual(m["llm_requests"], 2)
        self.assertEqual(m["cache_hit_rate"], 0.5)
        self.assertEqual(m["tool_time_s"], 0.5)
        self.assertEqual(m["tool_calls_by_name"], {"bash": 1})


class SanitizeTest(unittest.TestCase):
    def test_redacts_credentials(self):
        txt = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\nNEBIUS_API_KEY=supersecretvalue123"
        out = sanitize_text(txt)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", out)
        self.assertNotIn("supersecretvalue123", out)

    def test_keeps_placeholder_and_code(self):
        txt = "TOFA_API_KEY=proxy-injected\ndef final_grade(items):"
        self.assertEqual(sanitize_text(txt), txt)


class IndependentCostCheckTest(unittest.TestCase):
    def test_wire_logs_match_derived_costs(self):
        import subprocess
        res = subprocess.run([sys.executable, str(ROOT / "analysis" / "check_costs.py")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
