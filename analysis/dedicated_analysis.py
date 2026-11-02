#!/usr/bin/env python3
"""Public vs Dedicated benchmark analysis (2026-11-02) -> data/dedicated_benchmark.json

    python3 analysis/dedicated_analysis.py

Cohorts:
  public-historical  the 33 public-endpoint runs of 2026-10-30 (all efforts; comparisons use medium)
  public-control     3 paired public runs on 2026-11-02, inside the dedicated measurement window
  dedicated-seq      9 sequential dedicated runs (3 x T1/T2/T3)
  conc-2/3/5         dedicated concurrency waves (2 waves per level)

Dedicated cost is GPU billing time x $18.80/h. It is never derived from a per-token price. Each
dedicated request also gets a "public-equivalent token cost" (its tokens at public prices). This is
labelled as a counterfactual and is not what the run cost.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from metrics import _pct, cost_usd  # noqa: E402

DEDICATED_PRICE_PER_HOUR = 18.80  # 4x H100, 1 replica (user-provided; matches 4 x $4.70)
PROV = ROOT / "data" / "provenance"


def iso(ts: str) -> float:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def stats(values: list[float]) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"n": 0}
    out = {"n": len(v), "mean": round(statistics.fmean(v), 4), "p50": round(_pct(v, 0.5), 4),
           "min": round(min(v), 4), "max": round(max(v), 4)}
    if len(v) >= 20:  # p90/p95 only when the sample can support them
        out["p90"] = round(_pct(v, 0.9), 4)
        out["p95"] = round(_pct(v, 0.95), 4)
    return out


def load_runs() -> list[dict]:
    runs = []
    for f in sorted((ROOT / "runs").glob("*/result.json")):
        r = json.loads(f.read_text())
        wire_path = f.parent / "requests.jsonl"
        wire = [json.loads(l) for l in wire_path.read_text().splitlines()] if wire_path.exists() else []
        endpoint = r.get("endpoint", "public")
        cohort = r.get("cohort") or ("public-historical" if endpoint == "public" else "dedicated-unlabelled")
        r["_wire"] = [w for w in wire if w.get("path") == "/v1/chat/completions" and w.get("method") == "POST"]
        r["_endpoint"], r["_cohort"] = endpoint, cohort
        runs.append(r)
    return runs


def inflight_at(t: float, intervals: list[tuple[float, float]]) -> int:
    return sum(1 for a, b in intervals if a <= t < b)


def cohort_summary(runs: list[dict]) -> dict:
    reqs = [w for r in runs for w in r["_wire"]]
    ok = [w for w in reqs if w.get("status") == 200]
    by_task = {}
    for r in runs:
        by_task.setdefault(r["task"], []).append(r)
    prompt = sum((w.get("usage") or {}).get("prompt_tokens", 0) for w in ok)
    cached = sum(((w.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens") or 0 for w in ok)
    out_tok = sum((w.get("usage") or {}).get("completion_tokens", 0) for w in ok)
    cached_reported = any(((w.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens") is not None for w in ok)
    return {
        "runs": len(runs),
        "successes": sum(1 for r in runs if r["success"]),
        "by_task": {t: {"runs": len(rs), "successes": sum(1 for r in rs if r["success"]),
                        "task_time_s": stats([r["wall_time_s"] for r in rs]),
                        "llm_requests": stats([r["metrics"]["llm_requests"] for r in rs]),
                        "prompt_tokens": stats([r["metrics"]["prompt_tokens"] for r in rs]),
                        "output_tokens": stats([r["metrics"]["output_tokens"] for r in rs])}
                    for t, rs in sorted(by_task.items())},
        "task_time_s": stats([r["wall_time_s"] for r in runs]),
        "llm_requests_per_task": stats([r["metrics"]["llm_requests"] for r in runs]),
        "tool_calls_per_task": stats([r["metrics"]["tool_calls"] for r in runs]),
        "tool_calls_failed": sum(r["metrics"]["tool_calls_failed"] for r in runs),
        "requests": len(reqs),
        "http_errors": sum(1 for w in reqs if w.get("status") != 200 or w.get("error")),
        "timeouts": sum(1 for r in runs if r.get("timed_out")),
        "ttft_s": stats([w["t_first_token"] - w["t_recv"] for w in ok if w.get("t_first_token")]),
        "latency_s": stats([w["t_end"] - w["t_recv"] for w in ok if w.get("t_end")]),
        "decode_tps": stats([(w["usage"]["completion_tokens"] / (w["t_end"] - w["t_first_token"]))
                             for w in ok if w.get("t_first_token") and w.get("usage") and w["t_end"] - w["t_first_token"] > 0.05
                             and w["usage"]["completion_tokens"] > 1]),
        "prompt_tokens": prompt, "cached_tokens": cached, "output_tokens": out_tok,
        "cached_tokens_reported": cached_reported,
        "cache_hit_rate": round(cached / prompt, 4) if (prompt and cached_reported) else None,
        "tool_index_repairs": sum(w.get("tool_index_repairs") or 0 for w in ok),
        "public_token_cost_usd": round(sum(cost_usd(
            w["usage"]["prompt_tokens"] - (((w["usage"].get("prompt_tokens_details") or {}).get("cached_tokens")) or 0),
            ((w["usage"].get("prompt_tokens_details") or {}).get("cached_tokens")) or 0,
            w["usage"]["completion_tokens"]) for w in ok if w.get("usage")), 6),
        "endpoint_verified_runs": sum(1 for r in runs if (r.get("endpoint_verification") or {}).get("verified")),
    }


def main() -> None:
    runs = load_runs()
    groups: dict[str, list[dict]] = {}
    for r in runs:
        groups.setdefault(r["_cohort"], []).append(r)
    med = lambda rs: [r for r in rs if r["reasoning_effort"] == "medium"]  # noqa: E731

    # ---- endpoint verification: no request may be attributed to the wrong endpoint
    verification = {"dedicated_runs": 0, "dedicated_runs_verified": 0, "public_runs_new": 0, "public_runs_new_verified": 0,
                    "dedicated_requests": 0, "dedicated_requests_answered_by_dedicated": 0,
                    "public_labelled_requests_answered_by_dedicated": 0, "dedicated_labelled_requests_answered_by_public": 0}
    for r in runs:
        for w in r["_wire"]:
            rm = w.get("response_model")
            if r["_endpoint"] == "dedicated":
                verification["dedicated_requests"] += 1
                verification["dedicated_requests_answered_by_dedicated"] += int(rm == r.get("request_model"))
                verification["dedicated_labelled_requests_answered_by_public"] += int(rm == "openai/gpt-oss-120b")
            elif rm and rm.startswith("dedicated/"):
                verification["public_labelled_requests_answered_by_dedicated"] += 1
        if r["_endpoint"] == "dedicated":
            verification["dedicated_runs"] += 1
            verification["dedicated_runs_verified"] += int(bool((r.get("endpoint_verification") or {}).get("verified")))
        elif r.get("endpoint_verification"):
            verification["public_runs_new"] += 1
            verification["public_runs_new_verified"] += int(bool(r["endpoint_verification"]["verified"]))

    # ---- in-flight load seen by every dedicated request (all dedicated traffic on the one replica)
    ded_runs = [r for r in runs if r["_endpoint"] == "dedicated"]
    ded_reqs = [w for r in ded_runs for w in r["_wire"] if w.get("status") == 200 and w.get("t_end")]
    intervals = [(w["t_recv"], w["t_end"]) for w in ded_reqs]
    per_request = []
    for w in ded_reqs:
        # average number of in-flight requests during this request's decode phase
        t0, t1 = (w.get("t_first_token") or w["t_recv"]), w["t_end"]
        samples = [inflight_at(t0 + (t1 - t0) * k / 10, intervals) for k in range(10)] if t1 > t0 else [inflight_at(t0, intervals)]
        gen = t1 - t0
        out_tok = (w.get("usage") or {}).get("completion_tokens", 0)
        per_request.append({
            "inflight": round(statistics.fmean(samples), 2),
            "ttft_s": round(w["t_first_token"] - w["t_recv"], 4) if w.get("t_first_token") else None,
            "latency_s": round(w["t_end"] - w["t_recv"], 4),
            "decode_tps": round(out_tok / gen, 1) if gen > 0.05 and out_tok > 1 else None,
            "prompt_tokens": (w.get("usage") or {}).get("prompt_tokens"),
            "output_tokens": out_tok,
        })
    by_load = {}
    for q in per_request:
        b = min(5, max(1, round(q["inflight"])))
        by_load.setdefault(b, []).append(q)
    load_curve = {str(b): {"requests": len(qs), "decode_tps": stats([q["decode_tps"] for q in qs]),
                           "ttft_s": stats([q["ttft_s"] for q in qs]), "latency_s": stats([q["latency_s"] for q in qs])}
                  for b, qs in sorted(by_load.items())}
    # prefill behaviour: TTFT vs prompt size at low load (prefix caching shows up as flat TTFT)
    low = [q for q in per_request if q["inflight"] <= 1.5 and q["ttft_s"] is not None and q["prompt_tokens"]]
    small = [q["ttft_s"] for q in low if q["prompt_tokens"] < 6000]
    large = [q["ttft_s"] for q in low if q["prompt_tokens"] >= 9000]
    prefill = {"ttft_p50_prompt_lt_6k": round(_pct(small, 0.5), 4) if small else None, "n_lt_6k": len(small),
               "ttft_p50_prompt_ge_9k": round(_pct(large, 0.5), 4) if large else None, "n_ge_9k": len(large)}

    # ---- concurrency waves
    waves = []
    seq_med = {t: _pct([r["wall_time_s"] for r in groups.get("dedicated-seq", []) if r["task"] == t], 0.5)
               for t in {r["task"] for r in groups.get("dedicated-seq", [])}}
    for f in sorted((ROOT / "runs" / "waves").glob("*.json")):
        w = json.loads(f.read_text())
        members = [r for r in runs if r["run_id"] in w["run_ids"]]
        reqs = [q for r in members for q in r["_wire"] if q.get("status") == 200 and q.get("t_end")]
        t_first = min(q["t_recv"] for q in reqs)
        t_last = max(q["t_end"] for q in reqs)
        out_tok = sum(q["usage"]["completion_tokens"] for q in reqs if q.get("usage"))
        waves.append({
            "wave": w["wave"], "level": w["level"], "tasks": [r["task"] for r in members],
            "successes": sum(1 for r in members if r["success"]), "wall_s": w["wall_s"],
            "llm_active_window_s": round(t_last - t_first, 3),
            "output_tokens": out_tok,
            "aggregate_output_tps": round(out_tok / (t_last - t_first), 1),
            "peak_inflight": max(inflight_at(q["t_recv"] + 1e-6, [(x["t_recv"], x["t_end"]) for x in reqs]) for q in reqs),
            "tasks_per_min": round(len(members) / (w["wall_s"] / 60), 2),
            "task_time_s": [r["wall_time_s"] for r in members],
            "slowdown_vs_seq_median": [round(r["wall_time_s"] / seq_med[r["task"]], 3) for r in members if r["task"] in seq_med],
            "errors": sum(1 for r in members for q in r["_wire"] if q.get("status") != 200),
        })
    levels = {}
    for w in waves:
        levels.setdefault(w["level"], []).append(w)
    seq = groups.get("dedicated-seq", [])
    seq_reqs = [q for r in seq for q in r["_wire"] if q.get("status") == 200 and q.get("t_end")]
    seq_active = sum(r["metrics"]["llm_time_s"] for r in seq)
    concurrency = {"1": {"waves": 0, "agents": len(seq), "source": "dedicated-seq runs (one agent at a time)",
                         "aggregate_output_tps": round(sum(q["usage"]["completion_tokens"] for q in seq_reqs) / seq_active, 1) if seq_active else None,
                         "tasks_per_min": round(len(seq) / (sum(r["wall_time_s"] for r in seq) / 60), 2) if seq else None,
                         "task_time_s": stats([r["wall_time_s"] for r in seq]),
                         "slowdown_vs_seq_median": stats([r["wall_time_s"] / seq_med[r["task"]] for r in seq])}}
    for lvl, ws in sorted(levels.items()):
        concurrency[str(lvl)] = {
            "waves": len(ws), "agents": sum(len(w["tasks"]) for w in ws),
            "aggregate_output_tps": round(statistics.fmean(w["aggregate_output_tps"] for w in ws), 1),
            "tasks_per_min": round(statistics.fmean(w["tasks_per_min"] for w in ws), 2),
            "task_time_s": stats([t for w in ws for t in w["task_time_s"]]),
            "slowdown_vs_seq_median": stats([s for w in ws for s in w["slowdown_vs_seq_median"]]),
            "peak_inflight": max(w["peak_inflight"] for w in ws),
            "successes": sum(w["successes"] for w in ws),
        }

    # ---- billing
    ep_snap = json.loads((PROV / "dedicated_endpoint_2026-11-02.json").read_text())["endpoint"][0]
    created = iso(ep_snap["created_at"])
    window = [iso((ROOT / ".cache" / f).read_text().strip()) if (ROOT / ".cache" / f).exists() else None
              for f in ("live_window_start", "live_window_end")]
    stop_requested = window[1]
    stopped_observed = iso("2026-11-02T10:59:39Z")  # first poll showing status=stopped, ready_replicas=0
    # the live window opens with the Phase-1 compatibility requests, before the first DSH request
    ded_first = min([w["t_recv"] for w in ded_reqs] + ([window[0]] if window[0] else []))
    ded_last = max(w["t_end"] for w in ded_reqs)
    per_min = DEDICATED_PRICE_PER_HOUR / 60
    tasks_done = len(ded_runs)
    succ = sum(1 for r in ded_runs if r["success"])
    billing = {
        "price_per_hour": DEDICATED_PRICE_PER_HOUR,
        "price_source": "user-provided for the 4x H100 deployment (~$18.80/h = $0.31/min); not yet verified against an invoice",
        "endpoint_created_at": ep_snap["created_at"],
        "live_window_start": dt.datetime.fromtimestamp(window[0], dt.timezone.utc).isoformat() if window[0] else None,
        "first_dedicated_request": dt.datetime.fromtimestamp(ded_first, dt.timezone.utc).isoformat(),
        "last_dedicated_request_end": dt.datetime.fromtimestamp(ded_last, dt.timezone.utc).isoformat(),
        "stop_requested_at": dt.datetime.fromtimestamp(stop_requested, dt.timezone.utc).isoformat() if stop_requested else None,
        "stopped_observed_at": dt.datetime.fromtimestamp(stopped_observed, dt.timezone.utc).isoformat(),
        "max_billable_minutes": round((stopped_observed - created) / 60, 2),
        "max_billable_usd": round((stopped_observed - created) / 3600 * DEDICATED_PRICE_PER_HOUR, 2),
        "max_billable_note": "upper bound: endpoint creation -> stop observed. Provisioning (not ready) and graceful shutdown are not billed per the billing policy, so the invoice should be lower.",
        "benchmark_window_definition": "live window start (Phase-1 checks) -> end of the last dedicated request",
        "benchmark_window_minutes": round((ded_last - ded_first) / 60, 2),
        "benchmark_window_usd": round((ded_last - ded_first) / 60 * per_min, 2),
        "dedicated_tasks": tasks_done,
        "dedicated_successful_tasks": succ,
        "cost_per_completed_task_benchmark_window": round((ded_last - ded_first) / 60 * per_min / tasks_done, 4),
        "cost_per_successful_task_benchmark_window": round((ded_last - ded_first) / 60 * per_min / succ, 4),
        "cost_per_completed_task_incl_idle": round((stopped_observed - created) / 3600 * DEDICATED_PRICE_PER_HOUR / tasks_done, 4),
        "public_equivalent_token_cost_of_dedicated_traffic_usd": cohort_summary(ded_runs)["public_token_cost_usd"],
        "public_equivalent_note": "what the same tokens would have cost on the public endpoint, assuming no cache discount (dedicated does not report cached tokens); a counterfactual, not the dedicated cost",
        "invoice_verified": False,
    }
    best = max(concurrency.values(), key=lambda c: c.get("tasks_per_min") or 0)
    billing["cost_per_task_at_best_measured_rate"] = round(per_min / best["tasks_per_min"], 4)
    billing["best_measured_tasks_per_min"] = best["tasks_per_min"]

    compat = {e: json.loads((PROV / f"stream_compat_{e}_2026-11-02.json").read_text())["summary"]
              for e in ("dedicated", "public")}
    for e in compat:
        d = json.loads((PROV / f"stream_compat_{e}_2026-11-02.json").read_text())
        compat[e]["tool_call_deltas_per_call"] = [t["n_deltas"] for t in d["tool_trials"]]
        compat[e]["cached_tokens_in_usage"] = bool(((d["streaming"].get("usage") or {}).get("prompt_tokens_details") or {}))

    out = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "endpoint": {k: ep_snap[k] for k in ("id", "name", "routing_key", "model_name", "flavor_name", "region", "gpu_type", "gpu_count", "scaling")},
        "routing_note": "Dedicated requests were sent to the global API host https://api.tokenfactory.nebius.com/v1 with the endpoint's routing key. The regional URL https://api.tokenfactory.eu-north1.nebius.com/v1 returned 401 (no Network Secret configured for that host in this session).",
        "verification": verification,
        "compatibility": compat,
        "cohorts": {k: cohort_summary(v) for k, v in sorted(groups.items())},
        "cohorts_medium": {k: cohort_summary(med(v)) for k, v in sorted(groups.items()) if med(v)},
        "concurrency": concurrency,
        "waves": waves,
        "load_curve": load_curve,
        "prefill": prefill,
        "per_request_dedicated": per_request,
        "billing": billing,
        "total_benchmark_api_requests": {
            "phase1_compat": 5 * 2,  # 1 non-streaming + 1 streaming + 3 tool trials, per endpoint
            "phase1_models_list": 2,
            "dsh_chat_requests_dedicated": verification["dedicated_requests"],
            "dsh_chat_requests_public_control": cohort_summary(groups.get("public-control", []))["requests"],
            "control_plane": "list/templates reads, 1 PATCH (stop), ~3 status polls",
        },
    }
    (ROOT / "data" / "dedicated_benchmark.json").write_text(json.dumps(out, indent=1) + "\n")
    c = out["cohorts_medium"]
    for k in ("public-historical", "public-control", "dedicated-seq", "conc-2", "conc-3", "conc-5"):
        if k in c:
            s = c[k]
            print(f"{k:18s} runs={s['runs']:2d} succ={s['successes']:2d} task_p50={s['task_time_s'].get('p50')} "
                  f"req/task={s['llm_requests_per_task'].get('mean')} ttft_p50={s['ttft_s'].get('p50')} "
                  f"lat_p50={s['latency_s'].get('p50')} decode_p50={s['decode_tps'].get('p50')} hit={s['cache_hit_rate']} errors={s['http_errors']}")
    print("\nconcurrency:", json.dumps({k: {x: v.get(x) for x in ('agents', 'aggregate_output_tps', 'tasks_per_min', 'peak_inflight')} | {'slow_p50': v['slowdown_vs_seq_median'].get('p50') if isinstance(v['slowdown_vs_seq_median'], dict) else None} for k, v in concurrency.items()}, indent=0))
    print("\nload curve:", json.dumps({k: (v['requests'], v['decode_tps'].get('p50'), v['ttft_s'].get('p50')) for k, v in load_curve.items()}))
    print("prefill:", prefill)
    print("verification:", verification)
    print("billing:", json.dumps(billing, indent=0))


if __name__ == "__main__":
    main()
