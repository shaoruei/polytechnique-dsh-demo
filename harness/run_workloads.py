#!/usr/bin/env python3
"""Medium/Heavy workload experiment runner (public endpoint, sequential, budget-enforced).

    python3 harness/run_workloads.py pilot      # 1 x M1, 1 x H1   (cohort workload-pilot)
    python3 harness/run_workloads.py formal     # 3 x M1, 3 x H1, interleaved (cohort workload-formal)

Enforced limits (from the experiment brief):
  * at most MAX_ATTEMPTS paid task attempts across pilot + formal (counted from saved runs),
  * at most TOTAL_BUDGET_USD of provider-reported spend across those runs; each run gets a relay
    spending cap = min(PER_RUN_CAP_USD, remaining budget), so the relay refuses further LLM
    requests once a run reaches it,
  * 600 s wall clock per task, strictly sequential,
  * stop on any 401/403 from the provider or on >= 3 provider errors in one run.
Limitation: the cap is checked before each request is forwarded, so the request that crosses the
cap is still completed; one request can add at most ~(131k prompt x $0.15 + 16k output x $0.60)/1M
= ~$0.03. The relay prices tokens at the verified public prices, so the cap is not an invoice.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_ATTEMPTS = 8
TOTAL_BUDGET_USD = 3.00
PER_RUN_CAP_USD = 0.75
TIMEOUT_S = 600
PLANS = {"pilot": ["m1", "h1"], "formal": ["m1", "h1", "m1", "h1", "m1", "h1"]}


def workload_runs() -> list:
    out = []
    for f in sorted((ROOT / "runs").glob("*/result.json")):
        r = json.loads(f.read_text())
        if (r.get("cohort") or "").startswith("workload-"):
            out.append(r)
    return out


def spent(runs) -> float:
    total = 0.0
    for r in runs:
        m = r.get("metrics") or {}
        total += m.get("cost_usd") or r.get("relay_spent_usd") or 0.0
    return total


def main() -> int:
    plan = sys.argv[1] if len(sys.argv) > 1 else ""
    if plan not in PLANS:
        raise SystemExit(f"usage: run_workloads.py {'|'.join(PLANS)}")
    cohort = f"workload-{plan}"
    for i, task in enumerate(PLANS[plan], 1):
        runs = workload_runs()
        used, cost = len(runs), spent(runs)
        remaining = TOTAL_BUDGET_USD - cost
        if used >= MAX_ATTEMPTS:
            print(f"STOP: {used} paid attempts already used (max {MAX_ATTEMPTS})")
            return 2
        if remaining < 0.10:
            print(f"STOP: remaining budget ${remaining:.4f}")
            return 2
        cap = round(min(PER_RUN_CAP_USD, remaining - 0.05), 4)
        print(f"\n[{plan} {i}/{len(PLANS[plan])}] {task}: attempts used {used}/{MAX_ATTEMPTS}, "
              f"spent ${cost:.4f}/{TOTAL_BUDGET_USD:.2f}, per-run cap ${cap}", flush=True)
        proc = subprocess.run([sys.executable, str(ROOT / "harness" / "run_task.py"), task, "--endpoint", "public",
                               "--effort", "medium", "--timeout", str(TIMEOUT_S), "--cohort", cohort, "--label", cohort,
                               "--max-cost-usd", str(cap)], cwd=ROOT, capture_output=True, text=True)
        tail = [l for l in proc.stdout.splitlines() if l.startswith(("run ", "success", "wall time", "tokens", "HARNESS"))]
        print("\n".join(tail), flush=True)
        latest = max((ROOT / "runs").glob("*/result.json"), key=lambda p: p.stat().st_mtime)
        r = json.loads(latest.read_text())
        http = ((r.get("metrics") or {}).get("http") or {})
        statuses = set(http.get("statuses") or [])
        print(f"  cost ${((r.get('metrics') or {}).get('cost_usd') or 0):.4f}  relay ${r.get('relay_spent_usd')}  "
              f"http errors {http.get('errors')} {sorted(statuses)}", flush=True)
        if statuses & {401, 403}:
            print("STOP: authorization failure")
            return 3
        if (http.get("errors") or 0) >= 3 and not statuses <= {400}:
            print("STOP: repeated provider errors")
            return 3
    runs = workload_runs()
    print(f"\ndone: {len(runs)} workload attempts, spent ${spent(runs):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
