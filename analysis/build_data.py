#!/usr/bin/env python3
"""Aggregate runs/*/result.json into the data files used by the model and the dashboard.

    python3 analysis/build_data.py

Writes:
  data/runs.json        one record per run (summary metrics + per-request detail + trajectory)
  data/workload.json    per task / effort aggregates (means, percentiles) and pooled profile
  data/experiment_ledger.json  measured spend of all experiment runs (exact usage x verified prices)

Only runs that went through the relay (provider-reported per-request usage + wire timing) and
that issued at least one request are used for workload statistics. Others are still listed.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from metrics import _pct, cost_usd  # noqa: E402

RUNS = ROOT / "runs"
DATA = ROOT / "data"
TASK_TITLES = {
    "t1-grade-average": "T1 Fix weighted grade average (1 file bug-fix)",
    "t2-duration-parser": "T2 Implement duration parser + tests (feature from spec)",
    "t3-schedule-conflicts": "T3 Fix timetable clash detection (multi-file debugging)",
}


def trajectory(result: dict) -> dict:
    """Replayable agent trajectory: per LLM request tokens + measured latency + gap afterwards."""
    reqs = [r for r in result["metrics"]["requests"] if r["status"] == 200]
    steps = []
    for i, r in enumerate(reqs):
        end = r["t_start"] + (r["latency_s"] or 0)
        gap = (reqs[i + 1]["t_start"] - end) if i + 1 < len(reqs) else 0.0
        steps.append({
            "u": r["uncached_input_tokens"], "c": r["cached_tokens"], "o": r["completion_tokens"],
            "lat": round(r["latency_s"] or 0, 3), "ttft": r["ttft_s"], "gap": round(max(gap, 0.0), 3),
        })
    total_req = sum(s["lat"] for s in steps)
    lead = max(result["wall_time_s"] - total_req - sum(s["gap"] for s in steps), 0.0)
    return {"lead_s": round(lead, 3), "steps": steps}


def summarise(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "p50": round(_pct(values, 0.5), 4),
        "p90": round(_pct(values, 0.9), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
    }


def group_stats(runs: list[dict]) -> dict:
    ok = [r for r in runs if r["usable"]]
    m = lambda key: [r["metrics"][key] for r in ok if r["metrics"].get(key) is not None]  # noqa: E731
    reqs = [q for r in ok for q in r["metrics"]["requests"] if q["status"] == 200]
    unc = sum(q["uncached_input_tokens"] for q in reqs)
    out = sum(q["completion_tokens"] for q in reqs)
    return {
        "runs": len(ok),
        "successes": sum(1 for r in ok if r["success"]),
        "success_rate": round(sum(1 for r in ok if r["success"]) / len(ok), 4) if ok else None,
        "wall_time_s": summarise([r["wall_time_s"] for r in ok]),
        "llm_requests": summarise(m("llm_requests")),
        "tool_calls": summarise(m("tool_calls")),
        "prompt_tokens": summarise(m("prompt_tokens")),
        "uncached_input_tokens": summarise(m("uncached_input_tokens")),
        "cached_input_tokens": summarise(m("cached_input_tokens")),
        "output_tokens": summarise(m("output_tokens")),
        "cache_hit_rate": summarise(m("cache_hit_rate")),
        "cost_usd": summarise(m("cost_usd")),
        "llm_time_s": summarise(m("llm_time_s")),
        "tool_time_s": summarise(m("tool_time_s")),
        "per_request": {
            "n": len(reqs),
            "ttft_s": summarise([q["ttft_s"] for q in reqs if q["ttft_s"] is not None]),
            "latency_s": summarise([q["latency_s"] for q in reqs if q["latency_s"] is not None]),
            "decode_tps": summarise([q["decode_tps"] for q in reqs if q["decode_tps"] is not None]),
            "prompt_tokens": summarise([q["prompt_tokens"] for q in reqs]),
            "uncached_input_tokens": summarise([q["uncached_input_tokens"] for q in reqs]),
            "completion_tokens": summarise([q["completion_tokens"] for q in reqs]),
            "uncached_to_output_ratio": round(unc / out, 3) if out else None,
        },
    }


def main() -> None:
    runs = []
    for f in sorted(RUNS.glob("*/result.json")):
        r = json.loads(f.read_text())
        m = r.get("metrics") or {}
        usable = bool(r.get("relay")) and (m.get("llm_requests") or 0) > 0 and m.get("usage_source", "").startswith("provider (relay")
        rec = {
            "run_id": r["run_id"], "label": r.get("label", ""), "task": r["task"],
            "task_title": TASK_TITLES.get(r["task"], r["task"]), "effort": r["reasoning_effort"],
            "started_at": r["started_at"], "success": r["success"], "timed_out": r["timed_out"],
            "dsh_exit_code": r["dsh_exit_code"], "turn_end_reason": r.get("turn_end_reason"),
            "wall_time_s": r["wall_time_s"],
            "acceptance": {k: r["acceptance"][k] for k in ("tests_run", "failures", "errors", "ok")},
            "agent_suite_ok": r["agent_test_suite"]["ok"],
            "diff_stats": r["diff_stats"], "modified_test_files": r["modified_test_files"],
            "usable": usable,
            "metrics": {k: v for k, v in m.items() if k != "tools"},
            "tools": m.get("tools", []),
        }
        if usable:
            # independent recomputation of cost from per-request provider usage
            rec["metrics"]["cost_usd_recomputed"] = round(sum(
                cost_usd(q["uncached_input_tokens"], q["cached_tokens"], q["completion_tokens"])
                for q in m["requests"] if q["status"] == 200), 6)
            rec["trajectory"] = trajectory(r)
        runs.append(rec)

    DATA.mkdir(exist_ok=True)
    (DATA / "runs.json").write_text(json.dumps({"schema": 1, "runs": runs}, indent=1) + "\n")

    workload: dict = {"schema": 1, "groups": {}, "by_effort": {}, "tasks": TASK_TITLES}
    for task in sorted({r["task"] for r in runs}):
        for effort in ("low", "medium", "high"):
            sel = [r for r in runs if r["task"] == task and r["effort"] == effort]
            if sel:
                workload["groups"][f"{task}|{effort}"] = {"task": task, "effort": effort, **group_stats(sel)}
    for effort in ("low", "medium", "high"):
        sel = [r for r in runs if r["effort"] == effort]
        if sel:
            workload["by_effort"][effort] = group_stats(sel)
    workload["pooled"] = group_stats(runs)
    (DATA / "workload.json").write_text(json.dumps(workload, indent=1) + "\n")

    ledger = {
        "schema": 1,
        "note": "Measured spend of every saved experiment run: provider-reported usage x verified public prices. "
                "Excludes a handful of tiny manual probe requests (<1k tokens each) made while debugging.",
        "runs": len(runs),
        "llm_requests": sum((r["metrics"].get("llm_requests") or 0) for r in runs),
        "prompt_tokens": sum((r["metrics"].get("prompt_tokens") or 0) for r in runs),
        "output_tokens": sum((r["metrics"].get("output_tokens") or 0) for r in runs),
        "total_cost_usd": round(sum((r["metrics"].get("cost_usd") or 0) for r in runs), 6),
    }
    (DATA / "experiment_ledger.json").write_text(json.dumps(ledger, indent=1) + "\n")
    print(f"{len(runs)} runs ({sum(r['usable'] for r in runs)} usable); spend ${ledger['total_cost_usd']:.4f}")


if __name__ == "__main__":
    main()
