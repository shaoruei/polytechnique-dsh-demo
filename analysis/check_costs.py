#!/usr/bin/env python3
"""Independent check of every monetary figure derived from the experiments.

Path A (used everywhere else): harness/metrics.py -> runs/*/result.json -> data/runs.json, with
float prices from data/pricing.json.
Path B (this script): the raw relay wire logs (runs/*/requests.jsonl), the per-token price
strings returned by the Token Factory API (data/provenance/...), and exact Decimal arithmetic.

    python3 analysis/check_costs.py      # exit code 1 on any mismatch
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    api = json.loads((ROOT / "data/provenance/tofa_models_verbose_2026-10-30.json").read_text())["entry"]["pricing"]
    p_in, p_cached, p_out = Decimal(api["prompt"]), Decimal(api["input_cache_read"]), Decimal(api["completion"])
    cfg = json.loads((ROOT / "data/pricing.json").read_text())["public"]
    assert Decimal(str(cfg["input_per_mtok"])) == p_in * 10**6, "pricing.json input price != API"
    assert Decimal(str(cfg["cached_input_per_mtok"])) == p_cached * 10**6, "pricing.json cached price != API"
    assert Decimal(str(cfg["output_per_mtok"])) == p_out * 10**6, "pricing.json output price != API"

    runs = {r["run_id"]: r for r in json.loads((ROOT / "data/runs.json").read_text())["runs"]}
    total, bad, checked = Decimal(0), 0, 0
    for wire_file in sorted((ROOT / "runs").glob("*/requests.jsonl")):
        run_id = wire_file.parent.name
        cost = Decimal(0)
        for line in wire_file.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("path") != "/v1/chat/completions" or rec.get("status") != 200:
                continue
            u = rec.get("usage") or {}
            prompt = u.get("prompt_tokens", 0)
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            cost += (prompt - cached) * p_in + cached * p_cached + u.get("completion_tokens", 0) * p_out
        total += cost
        derived = Decimal(str(runs[run_id]["metrics"]["cost_usd"])) if run_id in runs else None
        checked += 1
        if derived is None or abs(derived - cost) > Decimal("0.000001"):
            bad += 1
            print(f"MISMATCH {run_id}: wire={cost} derived={derived}")
    ledger = Decimal(str(json.loads((ROOT / "data/experiment_ledger.json").read_text())["total_cost_usd"]))
    print(f"checked {checked} runs; wire-log total ${total:.6f}; ledger ${ledger}")
    if abs(total - ledger) > Decimal("0.00001"):
        print("MISMATCH ledger total")
        bad += 1
    print("OK" if not bad else f"{bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
