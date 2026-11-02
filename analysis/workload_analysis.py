#!/usr/bin/env python3
"""Small vs Medium vs Heavy coding workloads (public endpoint) -> data/workload_comparison.json

    python3 analysis/workload_analysis.py

Groups (all medium reasoning effort, public endpoint, same DSH configuration):
  small   T1-T3, cohort public-historical (2026-10-30), 18 runs: the original baseline
  medium  M1, cohort workload-formal (2026-11-02), 3 runs
  heavy   H1, cohort workload-formal (2026-11-02), 3 runs
  pilot   M1 + H1 pilot runs (workload-pilot), reported separately, never pooled

All token counts are provider-reported usage, recorded per request at the relay. Costs are those
tokens x verified public prices, recomputed here independently. The dedicated columns are
estimates from the calibrated 4xH100 model and are labelled as such.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from metrics import _pct, cost_usd  # noqa: E402

GROUPS = {
    "small": {"label": "Small: T1-T3", "cohort": "public-historical", "tasks": ("t1-", "t2-", "t3-")},
    "medium": {"label": "Medium: M1 late-penalty grading", "cohort": "workload-formal", "tasks": ("m1-",)},
    "heavy": {"label": "Heavy: H1 usage accounting & budgets", "cohort": "workload-formal", "tasks": ("h1-",)},
    "pilot": {"label": "Pilot (M1 + H1, not pooled)", "cohort": "workload-pilot", "tasks": ("m1-", "h1-")},
}


def stats(v):
    v = [x for x in v if x is not None]
    if not v:
        return {"n": 0}
    return {"n": len(v), "mean": round(statistics.fmean(v), 4), "p50": round(_pct(v, 0.5), 4),
            "min": round(min(v), 4), "max": round(max(v), 4)}


def load():
    runs = []
    for f in sorted((ROOT / "runs").glob("*/result.json")):
        r = json.loads(f.read_text())
        if r.get("reasoning_effort") != "medium" or r.get("endpoint", "public") != "public":
            continue
        r["_cohort"] = r.get("cohort") or "public-historical"
        wire = f.parent / "requests.jsonl"
        r["_wire"] = [json.loads(l) for l in wire.read_text().splitlines()] if wire.exists() else []
        runs.append(r)
    return runs


def checks_passed(r):
    a = r["acceptance"]
    return (a["tests_run"] - a["failures"] - a["errors"]) / a["tests_run"] if a["tests_run"] else None


def summarise(runs):
    reqs = [q for r in runs for q in r["metrics"]["requests"] if q["status"] == 200]
    M = lambda k: [r["metrics"][k] for r in runs]  # noqa: E731
    # independent cost: raw wire usage x prices
    wire_cost = []
    for r in runs:
        c = 0.0
        for w in r["_wire"]:
            if w.get("path") == "/v1/chat/completions" and w.get("status") == 200 and w.get("usage"):
                u = w["usage"]
                cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                c += cost_usd(u["prompt_tokens"] - cached, cached, u["completion_tokens"])
        wire_cost.append(c)
    succ = sum(1 for r in runs if r["success"])
    total_cost = sum(wire_cost)
    prompt = sum(M("prompt_tokens"))
    out = sum(M("output_tokens"))
    unc = sum(M("uncached_input_tokens"))
    cached = sum(M("cached_input_tokens"))
    return {
        "runs": len(runs),
        "successes": succ,
        "success_rate": round(succ / len(runs), 4) if runs else None,
        "hidden_checks_passed_fraction": stats([checks_passed(r) for r in runs]),
        "task_time_s": stats([r["wall_time_s"] for r in runs]),
        "llm_time_s": stats(M("llm_time_s")),
        "tool_time_s": stats(M("tool_time_s")),
        "llm_requests": stats(M("llm_requests")),
        "tool_calls": stats(M("tool_calls")),
        "tool_calls_failed": stats(M("tool_calls_failed")),
        "prompt_tokens": stats(M("prompt_tokens")),
        "uncached_input_tokens": stats(M("uncached_input_tokens")),
        "cached_input_tokens": stats(M("cached_input_tokens")),
        "output_tokens": stats(M("output_tokens")),
        "max_prompt_tokens": stats(M("max_prompt_tokens")),
        "cache_hit_rate": round(cached / prompt, 4) if prompt else None,
        "cached_share_of_cost": round(cached * 0.10 / (unc * 0.15 + cached * 0.10 + out * 0.60), 4) if prompt else None,
        "uncached_to_output_ratio": round(unc / out, 3) if out else None,
        "prompt_plus_output_per_task": round((prompt + out) / len(runs)) if runs else None,
        "ttft_s": stats([q["ttft_s"] for q in reqs]),
        "latency_s": stats([q["latency_s"] for q in reqs]),
        "decode_tps": stats([q["decode_tps"] for q in reqs]),
        "http_errors": sum(((r["metrics"].get("http") or {}).get("errors") or 0) for r in runs),
        "timeouts": sum(1 for r in runs if r["timed_out"]),
        "cost_per_task_usd": stats(wire_cost),
        "cost_total_usd": round(total_cost, 6),
        "cost_per_successful_task_usd": round(total_cost / succ, 6) if succ else None,
        "public_cost_per_million_output_usd": round(total_cost / out * 1e6, 3) if out else None,
        "context_growth": [[q["prompt_tokens"] for q in r["metrics"]["requests"] if q["status"] == 200] for r in runs],
        "run_ids": [r["run_id"] for r in runs],
        "fixture_sha256": sorted({r.get("fixture_sha256") for r in runs if r.get("fixture_sha256")}),
    }


def dedicated_estimates() -> dict:
    """Calibrated 4xH100 model applied to each workload's measured traces (node, shared model)."""
    js = r"""
import { readFileSync } from 'node:fs';
import { soloRequestSeconds, capacityPerGpu } from './model/capacity.js';
import { publicCost } from './model/cost.js';
import { trajectoriesFrom, perTaskProfile } from './model/data.js';
const j = (p) => JSON.parse(readFileSync(p));
const runs = j('data/runs.json'); const prof = j('data/dedicated_profiles.json').gpus.h100x4; const pr = j('data/pricing.json');
const sets = {
  small: trajectoriesFrom(runs).filter((t) => t.effort === 'medium'),
  medium: trajectoriesFrom(runs, { cohorts: ['workload-formal'] }).filter((t) => t.task.startsWith('m1-')),
  heavy: trajectoriesFrom(runs, { cohorts: ['workload-formal'] }).filter((t) => t.task.startsWith('h1-')),
};
const med = (a) => { const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const out = {};
const replicaPrice = pr.dedicated.gpus.h100x4.price_per_replica_hour;
const perReplica90 = capacityPerGpu(prof, 90) * prof.gpus_per_replica;   // output tok/s at 90 tok/s/user
for (const [k, tr] of Object.entries(sets)) {
  const p = perTaskProfile(tr);
  const pubPerTask = publicCost(p.tokens, pr.public);
  out[k] = {
    traces: tr.length,
    idle_replica_task_time_s_p50: med(tr.map((t) => t.lead_s + t.steps.reduce((a, x) => a + soloRequestSeconds(prof, x) + x.gap, 0))),
    measured_public_task_time_s_p50: med(tr.map((t) => t.lead_s + t.steps.reduce((a, x) => a + x.lat + x.gap, 0))),
    public_cost_per_task: pubPerTask,
    output_tokens_per_task: p.tokens.output,
    // decode-slot capacity at 90 tok/s/user (extrapolated above 5 in flight): tasks per replica-hour
    tasks_per_replica_hour_at_full_use: perReplica90 * 3600 / p.tokens.output,
    breakeven_utilisation: (replicaPrice * p.tokens.output) / (perReplica90 * 3600 * pubPerTask),
    tasks_per_minute_to_match_public: replicaPrice / 60 / pubPerTask,
    task_starts_per_minute_within_default_tpm: pr.public.rate_limits.tokens_per_minute / p.tokens.prompt_plus_output,
  };
}
console.log(JSON.stringify(out));
"""
    res = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def main():
    runs = load()
    groups = {}
    for key, g in GROUPS.items():
        sel = [r for r in runs if r["_cohort"] == g["cohort"] and r["task"].startswith(g["tasks"])]
        groups[key] = {"label": g["label"], "cohort": g["cohort"], **summarise(sel)}
    per_task = {}
    for r in runs:
        if r["_cohort"] in ("workload-formal", "public-historical"):
            per_task.setdefault(r["task"], []).append(r)
    ded = dedicated_estimates()
    bench = json.loads((ROOT / "data" / "dedicated_benchmark.json").read_text())
    spend = [r for r in runs if r["_cohort"].startswith("workload-")]
    out = {
        "schema": 1,
        "groups": groups,
        "per_task": {t: {"runs": len(rs), "successes": sum(1 for r in rs if r["success"]),
                         "task_time_s_p50": round(_pct([r["wall_time_s"] for r in rs], 0.5), 3),
                         "cost_per_task_usd_mean": round(statistics.fmean(r["metrics"]["cost_usd"] for r in rs), 6)}
                     for t, rs in sorted(per_task.items())},
        "dedicated_estimates": ded,
        "dedicated_measured_reference": {
            "note": "Measured on ecole-demo (4x H100) for T1-T3 only, 2026-11-02",
            "seq_task_time_s_p50": bench["cohorts_medium"]["dedicated-seq"]["task_time_s"]["p50"],
            "decode_tps_p50": bench["cohorts_medium"]["dedicated-seq"]["decode_tps"]["p50"],
            "best_measured_tasks_per_min": bench["billing"]["best_measured_tasks_per_min"],
            "price_per_hour": bench["billing"]["price_per_hour"],
        },
        "experiment": {
            "paid_attempts": len(spend),
            "pilot_attempts": sum(1 for r in spend if r["_cohort"] == "workload-pilot"),
            "formal_attempts": sum(1 for r in spend if r["_cohort"] == "workload-formal"),
            "provider_reported_spend_usd": round(sum(r["metrics"]["cost_usd"] for r in spend), 6),
            "relay_counted_spend_usd": round(sum(r.get("relay_spent_usd") or 0 for r in spend), 6),
            "cap_rejections": sum(1 for r in spend for w in r["_wire"] if w.get("cap_rejected")),
            "http_errors": sum(((r["metrics"].get("http") or {}).get("errors") or 0) for r in spend),
            "fixtures": {t: sorted({r.get("fixture_sha256") for r in spend if r["task"] == t}) for t in sorted({r["task"] for r in spend})},
        },
    }
    (ROOT / "data" / "workload_comparison.json").write_text(json.dumps(out, indent=1) + "\n")
    hdr = f"{'':8s} {'n':>2s} {'succ':>5s} {'checks':>6s} {'time p50':>8s} {'req':>5s} {'tools(err)':>10s} {'prompt':>8s} {'uncached':>8s} {'output':>7s} {'hit':>5s} {'maxctx':>7s} {'ttft':>5s} {'lat':>5s} {'tok/s':>5s} {'$/task':>7s} {'$/succ':>7s}"
    print(hdr)
    for k, g in groups.items():
        print(f"{k:8s} {g['runs']:2d} {g['successes']:2d}/{g['runs']:<2d} {g['hidden_checks_passed_fraction'].get('mean', 0):6.2f} "
              f"{g['task_time_s'].get('p50', 0):8.1f} {g['llm_requests'].get('mean', 0):5.1f} "
              f"{g['tool_calls'].get('mean', 0):5.1f}({g['tool_calls_failed'].get('mean', 0):3.1f}) {g['prompt_tokens'].get('mean', 0):8.0f} "
              f"{g['uncached_input_tokens'].get('mean', 0):8.0f} {g['output_tokens'].get('mean', 0):7.0f} {g['cache_hit_rate'] or 0:5.2f} "
              f"{g['max_prompt_tokens'].get('mean', 0):7.0f} {g['ttft_s'].get('p50', 0):5.2f} {g['latency_s'].get('p50', 0):5.2f} "
              f"{g['decode_tps'].get('p50', 0):5.0f} {g['cost_per_task_usd'].get('mean', 0):7.4f} {g['cost_per_successful_task_usd'] or float('nan'):7.4f}")
    print("\ndedicated estimates:", json.dumps(ded, indent=0))
    print("experiment:", json.dumps(out["experiment"]))


if __name__ == "__main__":
    main()
