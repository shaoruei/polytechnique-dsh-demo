"""data/endpoint_bench.json (analysis/build_endpoint_bench.py) must mirror the API benchmark summary."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "endpoint_bench.json"
SRC = ROOT / "data" / "deepseek_v4_endpoint_load" / "summary.json"


@unittest.skipUnless(OUT.exists() and SRC.exists(), "run analysis/build_endpoint_bench.py first")
class EndpointBenchDataTest(unittest.TestCase):
    def test_scaling_matches_summary(self):
        out, src = json.loads(OUT.read_text()), json.loads(SRC.read_text())
        for prof in ("A", "B"):
            for row in out["scaling"][prof]:
                cell = src["scaling"]["public"][prof][f"c={row['c']}"]
                self.assertEqual(row["agg_out_tps"], cell["aggregate_output_tps"])
                self.assertEqual(row["lat_p95"], cell["latency_s"]["p95"])

    def test_dedicated_not_presented_as_measured(self):
        out, src = json.loads(OUT.read_text()), json.loads(SRC.read_text())
        self.assertEqual(src["totals"]["dedicated_requests"], 0)
        self.assertEqual(out["dedicated"]["status"], "not measured")
        self.assertNotIn("dedicated", out["scaling"])


if __name__ == "__main__":
    unittest.main()
