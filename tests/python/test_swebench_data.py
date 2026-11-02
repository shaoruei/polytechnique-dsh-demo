"""data/swebench.json (built by analysis/build_swebench.py) must match the recorded experiment exactly."""
import json
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "swebench.json"
EXP = ROOT / "experiments" / "swebench_public_v4flash"


@unittest.skipUnless(DATA.exists(), "run analysis/build_swebench.py first")
class SwebenchDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads(DATA.read_text())

    def test_headline_counts(self):
        runs = self.d["runs"]
        self.assertEqual(len(runs), 9)
        self.assertEqual(sum(r["official"]["resolved"] for r in runs), 8)
        self.assertEqual(len(self.d["requests"]), 168)
        self.assertEqual(sum(r["metrics"]["llm_requests"] for r in runs), 168)

    def test_official_verdicts_match_reports(self):
        for r in self.d["runs"]:
            rep = json.loads((EXP / "runs" / r["run_id"] / "official-eval" / "report.json").read_text())[r["instance_id"]]
            self.assertEqual(r["official"]["resolved"], rep["resolved"], r["run_id"])

    def test_request_costs_recompute_from_tokens_at_verified_prices(self):
        entry = json.loads((EXP / "provenance" / "tofa_model_entry.json").read_text())["entry"]["pricing"]
        pin, pcache, pout = (Decimal(entry[k]) for k in ("prompt", "input_cache_read", "completion"))
        total = Decimal(0)
        for q in self.d["requests"]:
            c = q["u"] * pin + q["c"] * pcache + q["o"] * pout
            self.assertAlmostEqual(float(c), q["cost"], places=7, msg=(q["run"], q["seq"]))
            total += c
        self.assertEqual(round(total, 4), Decimal("0.0754"))

    def test_patches_are_the_evaluated_ones(self):
        for r in self.d["runs"]:
            evaluated = (EXP / "runs" / r["run_id"] / "official-eval" / "patch.diff").read_text()
            self.assertEqual(r["patch"].strip(), evaluated.strip(), r["run_id"])

    def test_replay_has_every_request_and_tool_call(self):
        for r in self.d["runs"]:
            ev = self.d["replays"][r["run_id"]]
            self.assertEqual(sum(e["k"] == "step" for e in ev), r["metrics"]["llm_requests"], r["run_id"])
            self.assertEqual(sum(e["k"] == "call" for e in ev), r["metrics"]["tool_calls"], r["run_id"])


if __name__ == "__main__":
    unittest.main()
