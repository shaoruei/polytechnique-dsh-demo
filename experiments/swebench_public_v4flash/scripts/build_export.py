#!/usr/bin/env python3
"""Aggregate runs/*/ of this experiment into dashboard-compatible export files.

export/runs.json          one record per trial: summary metrics + official outcome + trajectory
                          {lead_s, steps:[{u,c,o,lat,ttft,gap}]} (same shape as data/runs.json
                          `trajectory`, which model/sim.js replays)
export/workload.json      per-instance groups + pooled stats with the keys of data/workload.json
                          (n, mean, p50, p90, min, max, stdev)
export/requests.csv       every LLM request of every trial in order (the full workload trace)
export/trajectories.json  [{task, effort, success, lead_s, steps}] - the exact input format of
                          model/sim.js simulate() ("trajectories" parameter)
The dashboard is NOT modified; these files are not read by dashboard/build.mjs.
Usage: build_export.py
"""
import csv, json, os, statistics, subprocess, sys
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXP.parents[1] / "harness"))
from metrics import _pct  # noqa: E402  (same percentile definition as analysis/build_data.py)

MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"n": len(values), "mean": round(statistics.fmean(values), 4), "p50": round(_pct(values, 0.5), 4),
            "p90": round(_pct(values, 0.9), 4), "min": round(min(values), 4), "max": round(max(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0}


runs = []
for d in sorted((EXP / "runs").iterdir()):
    if not (d / "run.json").exists():
        continue
    # re-run the (current) integrity scanner so every trial is judged by the same rules
    subprocess.run([sys.executable, str(EXP.parents[1] / "live_demo/scripts/summarize_session.py"), str(d / "session.jsonl"),
                    str(d / "integrity")], check=True, capture_output=True)
    integ = json.load(open(d / "integrity" / "metrics.json"))
    # regenerate the trace from the raw session log with the current extractor
    subprocess.run([sys.executable, str(EXP / "scripts/extract_trace.py"), str(d / "session.jsonl"), str(d), "--price-in", "0.14",
                    "--price-cached", "0.01", "--price-out", "0.28"], check=True, capture_output=True)
    meta = json.load(open(d / "run.json")); tr = json.load(open(d / "trace.json"))
    meta["integrity_verdict"] = integ["integrity_verdict"]; meta["integrity_flags"] = [f["kind"] for f in integ["integrity_flags"]]
    json.dump(meta, open(d / "run.json", "w"), indent=1)
    s = tr["summary"]
    assert meta["model"] == MODEL and meta["endpoint"] == "public", d
    runs.append({**meta, "task": meta["instance_id"], "effort": s["reasoning_effort"], "cohort": "swebench-public-v4flash",
                 "wall_time_s": s["wall_time_s"], "metrics": {k: s[k] for k in (
                     "llm_requests", "tool_calls", "tool_calls_failed", "tool_calls_by_name", "prompt_tokens",
                     "uncached_input_tokens", "cached_input_tokens", "output_tokens", "max_prompt_tokens", "cache_hit_rate",
                     "cost_usd", "cost_usd_without_cache_discount", "llm_time_s", "gap_time_s", "lead_s", "ttft_s_p50",
                     "ttft_s_mean", "decode_tps_p50", "latency_s_p50", "stream_stalls", "stream_stall_s", "turn_started_at_utc")} | {"usage_source": "provider, via DSH session log (no relay)"},
                 "auxiliary_requests": tr["auxiliary_requests"], "trajectory": tr["trajectory"], "_requests": tr["requests"]})


def group(rs):
    m = lambda k: [r["metrics"][k] for r in rs]
    reqs = [q for r in rs for q in r["_requests"]]
    return {"runs": len(rs), "successes": sum(r["success"] for r in rs),
            "success_rate": round(sum(r["success"] for r in rs) / len(rs), 3) if rs else None,
            "wall_time_s": stats([r["wall_time_s"] for r in rs]), "llm_requests": stats(m("llm_requests")),
            "tool_calls": stats(m("tool_calls")), "prompt_tokens": stats(m("prompt_tokens")),
            "uncached_input_tokens": stats(m("uncached_input_tokens")), "cached_input_tokens": stats(m("cached_input_tokens")),
            "output_tokens": stats(m("output_tokens")), "cache_hit_rate": stats(m("cache_hit_rate")), "cost_usd": stats(m("cost_usd")),
            "per_request": {"latency_s": stats([q["latency_s"] for q in reqs]), "ttft_s": stats([q["ttft_s"] for q in reqs]),
                            "decode_tps": stats([q["decode_tps"] for q in reqs]),
                            "decode_tps_excl_stalls": stats([q["decode_tps_excl_stalls"] for q in reqs]),
                            "stream_stall_s": stats([q["stream_stall_s"] for q in reqs]), "gap_after_s": stats([q["gap_after_s"] for q in reqs]),
                            "prompt_tokens": stats([q["prompt_tokens"] for q in reqs]), "output_tokens": stats([q["output_tokens"] for q in reqs])}}


pricing = json.load(open(EXP / "provenance" / "tofa_model_entry.json"))
price = {k: float(pricing["entry"]["pricing"][f]) * 1e6 for k, f in (("input_per_mtok", "prompt"), ("cached_input_per_mtok", "input_cache_read"), ("output_per_mtok", "completion"))}
common = {"schema": 1, "cohort": "swebench-public-v4flash (2026-11-02)", "model": MODEL, "endpoint": "public",
          "base_url": "https://api.tokenfactory.nebius.com/v1", "relay": False, "harness": "stock dsh web 0.2.1-rc.5 (Web UI, standard preset)",
          "pricing_public": {**price, "evidence": "verified", "source": "provenance/tofa_model_entry.json",
                             "rate_limits": pricing["entry"].get("per_request_limits")},
          "selection": "first survivors of live_demo/selection/screen.py hash order, excluding instances that need external info",
          "note": "Public endpoint only. No dedicated measurement and no dedicated estimate here."}
os.makedirs(EXP / "export", exist_ok=True)
json.dump({**common, "runs": [{k: v for k, v in r.items() if k != "_requests"} for r in runs]}, open(EXP / "export" / "runs.json", "w"), indent=1)
groups = {f"{t}|{e}": {"task": t, "effort": e, **group([r for r in runs if r["task"] == t and r["effort"] == e])}
          for t, e in sorted({(r["task"], r["effort"]) for r in runs})}
json.dump({**common, "groups": groups, "pooled": group(runs)}, open(EXP / "export" / "workload.json", "w"), indent=1)
json.dump([{"run_id": r["run_id"], "task": r["task"], "effort": r["effort"], "success": r["success"], **r["trajectory"]} for r in runs],
          open(EXP / "export" / "trajectories.json", "w"), indent=1)
cols = ["run_id", "instance_id", "trial", "success", "seq", "step", "model", "t_start_epoch_s", "t_start_s", "t_end_s", "latency_s", "ttft_s", "decode_s",
        "decode_tps", "stream_stalls", "stream_stall_s", "uncached_input_tokens", "cached_input_tokens", "output_tokens", "prompt_tokens", "stop_reason", "n_tool_calls",
        "tools", "tool_time_s", "gap_after_s", "cost_usd"]
with open(EXP / "export" / "requests.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(cols)
    for r in runs:
        for q in r["_requests"]:
            w.writerow([r["run_id"], r["instance_id"], r["trial"], r["success"], q["seq"], q["step"], q["model"], q["t_start_epoch_s"], q["t_start_s"], q["t_end_s"],
                        q["latency_s"], q["ttft_s"], q["decode_s"], q["decode_tps"], q["stream_stalls"], q["stream_stall_s"], q["uncached_input_tokens"], q["cached_input_tokens"],
                        q["output_tokens"], q["prompt_tokens"], q["stop_reason"], len(q["tool_calls"]), "+".join(t["name"] for t in q["tool_calls"]),
                        round(sum(t["duration_s"] or 0 for t in q["tool_calls"]), 3), q["gap_after_s"], q["cost_usd"]])
print(f"{len(runs)} runs, {sum(len(r['_requests']) for r in runs)} requests -> export/")
for r in runs:
    print(r["run_id"], "success" if r["success"] else "FAIL", r["wall_time_s"], "s", r["metrics"]["llm_requests"], "req", r["metrics"]["cost_usd"], "$", r["integrity_verdict"])
