#!/usr/bin/env python3
"""Run a small, budget-capped, strictly sequential experiment plan.

    python3 harness/run_batch.py --plan default --budget-usd 2

Every run is a separate `run_task.py` invocation, never in parallel (no load testing). The batch
stops once the measured spend in runs/ passes the budget. The cumulative spend ledger is
data/experiment_ledger.json (rebuilt by analysis/build_data.py from runs/*/result.json).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLANS = {
    # 3 tasks x 5 repetitions at the default effort, plus a small effort comparison.
    "default": [(t, "medium") for _ in range(5) for t in ("t1", "t2", "t3")]
    + [(t, "low") for _ in range(3) for t in ("t1", "t2", "t3")]
    + [(t, "high") for _ in range(2) for t in ("t1", "t2", "t3")],
    "smoke": [("t1", "medium")],
}


def spent_usd() -> float:
    total = 0.0
    for f in (ROOT / "runs").glob("*/result.json"):
        m = json.loads(f.read_text()).get("metrics") or {}
        total += m.get("cost_usd") or 0.0
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="default", choices=sorted(PLANS))
    ap.add_argument("--budget-usd", type=float, default=2.0)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--label", default="batch")
    args = ap.parse_args()
    plan = PLANS[args.plan]
    print(f"plan {args.plan}: {len(plan)} runs, budget ${args.budget_usd:.2f}, already spent ${spent_usd():.4f}")
    for i, (task, effort) in enumerate(plan, 1):
        if spent_usd() >= args.budget_usd:
            print("budget reached, stopping")
            return 2
        print(f"\n[{i}/{len(plan)}] {task} effort={effort}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "harness" / "run_task.py"), task, "--effort", effort,
                        "--timeout", str(args.timeout), "--label", args.label], cwd=ROOT)
    print(f"\ndone; total measured spend ${spent_usd():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
