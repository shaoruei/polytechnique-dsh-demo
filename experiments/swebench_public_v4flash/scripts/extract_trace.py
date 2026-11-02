#!/usr/bin/env python3
"""Per-request workload trace from a decoded DSH session log (no relay, no proxy).

Source of every number: DSH's own session events.
  t_start   `step/start` of the agent-loop step that issues the request (the request is sent
            within milliseconds; for step 1 `request/header` is logged ~15 ms later)
  t_first   first streamed token, reconstructed from the `stream` record stored with each
            `assistant/message` (chunk time / packed runs: time0 + cumulative dt), i.e. what
            DSH's own UI uses for tok/s
  t_last    last streamed chunk;  t_end = `assistant/message` time (response settled)
  u, c, o   `assistant/message.usage`: inputTokens (uncached), cacheReadTokens, outputTokens
            as reported by the provider stream (`prompt_tokens` = u + c)
  gap       next request's t_start - t_end: tool execution + harness overhead (tools in between
            are listed with their own durations from tool/call -> tool/result)
Cost uses the public list price passed on the command line.

Usage: extract_trace.py SESSION_JSONL OUT_DIR --price-in X --price-cached Y --price-out Z  (USD per 1M tokens)
Writes OUT_DIR/trace.json and OUT_DIR/requests.csv; prints a one-line summary.
"""
import argparse, csv, json, os, statistics

ap = argparse.ArgumentParser()
ap.add_argument("session"); ap.add_argument("out")
ap.add_argument("--price-in", type=float, required=True); ap.add_argument("--price-cached", type=float, required=True)
ap.add_argument("--price-out", type=float, required=True)
a = ap.parse_args()
ev = [json.loads(l) for l in open(a.session) if l.strip()]
S = lambda ms: ms / 1000.0


STALL_MS = 1000  # inter-fragment pause counted as a server-side stall


def stalls(stream):
    """(count, seconds) of pauses > STALL_MS between consecutive token fragments of one response."""
    times = []
    for r in stream or []:
        if r.get("type") != "chunk":
            t = r["time0"]; times.append(t)
            for dt in r.get("dt", []):
                t += dt; times.append(t)
    times.sort(); gaps = [b - a for a, b in zip(times, times[1:]) if b - a > STALL_MS]
    return len(gaps), round(sum(gaps) / 1000, 3)


def stream_times(stream):
    """(first_token_ms, last_chunk_ms, n_token_chunks) from a compact stream record list."""
    first = last = None; n = 0
    for r in stream or []:
        if r.get("type") == "chunk":
            t = r["time"]; ch = r.get("chunk", {})
            is_tok = ch.get("type") in ("text-delta", "reasoning-delta", "tool-call-delta") and (ch.get("text") or ch.get("delta") or ch.get("argsDelta") or ch.get("name"))
            if is_tok:
                n += 1; first = t if first is None else first
            last = t if last is None else max(last, t)
        else:  # packed run: time0 + cumulative dt over fragments
            t = r.get("time0"); frags = r.get("args") if r.get("type") == "tool-call-chunks" else r.get("texts", [])
            dts = [0] + list(r.get("dt", []))
            for i, fr in enumerate(frags or []):
                t = r["time0"] + sum(dts[: i + 1])
                if fr or (r.get("type") == "tool-call-chunks" and r.get("name") and i == 0):
                    n += 1; first = t if first is None else first
                last = t if last is None else max(last, t)
            if r.get("type") == "tool-call-chunks" and r.get("name") is not None and first is None:
                first = r["time0"]
    return first, last, n


turn_start = next(e["time"] for e in ev if e["type"] == "turn/start")
turn_end = max(e["time"] for e in ev if e["type"] == "turn/end")
end_reason = [e["data"].get("reason", {}).get("kind") for e in ev if e["type"] == "turn/end"]
header = next((e["data"]["header"]["config"] for e in ev if e["type"] == "request/header"), {})
step_start = {e["data"]["step"]: e["time"] for e in ev if e["type"] == "step/start"}
calls = {}
for e in ev:
    if e["type"] == "tool/call":
        calls[e["data"]["callId"]] = {"step": e["data"]["step"], "name": e["data"]["name"], "t_call": e["time"]}
    elif e["type"] == "tool/result":
        m = e["data"]["message"]; c = calls.get(m.get("toolCallId"))
        if c:
            c["t_result"] = e["time"]
            txt = "".join(x.get("text", "") for x in m.get("content", []) if isinstance(x, dict))
            c["error"] = bool(m.get("isError")) or txt.lstrip().startswith(("Error", "[stderr]\nerror"))

reqs = []
for e in ev:
    if e["type"] != "assistant/message":
        continue
    d = e["data"]; u = d.get("usage") or {}; st = d.get("step")
    t0 = step_start.get(st, e["time"]); first, last, ntok = stream_times(d.get("stream"))
    rs = (d["message"].get("source") or {}).get("replayState", {}).get("response", {})
    tools = [c for c in calls.values() if c["step"] == st]
    o = u.get("outputTokens") or 0
    dec = S(last - first) if first and last and last > first else None
    n_st, st_s = stalls(d.get("stream"))
    reqs.append({
        "seq": len(reqs) + 1, "kind": "agent", "step": st, "model": rs.get("model") or header.get("model"),
        "provider": rs.get("provider") or header.get("provider"), "response_id": rs.get("responseId"),
        "stop_reason": rs.get("stopReason"),
        "t_start_epoch_s": round(S(t0), 3), "t_start_s": round(S(t0 - turn_start), 3), "t_end_s": round(S(e["time"] - turn_start), 3),
        "latency_s": round(S(e["time"] - t0), 3),
        "ttft_s": round(S(first - t0), 3) if first else None,
        "decode_s": round(dec, 3) if dec else None,
        "decode_tps": round(o / dec, 1) if dec and o else None,
        "stream_stalls": n_st, "stream_stall_s": st_s,
        "decode_tps_excl_stalls": round(o / (dec - st_s), 1) if dec and o and dec - st_s > 0.05 else None,
        "uncached_input_tokens": u.get("inputTokens") or 0, "cached_input_tokens": u.get("cacheReadTokens") or 0,
        "output_tokens": o, "prompt_tokens": (u.get("inputTokens") or 0) + (u.get("cacheReadTokens") or 0),
        "tool_calls": [{"name": c["name"], "duration_s": round(S(c["t_result"] - c["t_call"]), 3) if c.get("t_result") else None,
                        "error": c.get("error")} for c in sorted(tools, key=lambda c: c["t_call"])],
    })
for i, r in enumerate(reqs):
    nxt = reqs[i + 1]["t_start_s"] if i + 1 < len(reqs) else S(turn_end - turn_start)
    r["gap_after_s"] = round(max(nxt - r["t_end_s"], 0.0), 3)
    r["cost_usd"] = round((r["uncached_input_tokens"] * a.price_in + r["cached_input_tokens"] * a.price_cached
                           + r["output_tokens"] * a.price_out) / 1e6, 8)

aux = []
tq = next((e for e in ev if e["type"] == "session/title-llm-request"), None)
td = next((e for e in ev if e["type"] == "session/title" and (e["data"].get("source") or {}).get("kind") == "provider"), None)
if tq:
    aux.append({"kind": "session-title", "model": (tq["data"].get("route") or {}).get("model"),
                "t_start_s": round(S(tq["time"] - turn_start), 3),
                "latency_s": round(S(td["time"] - tq["time"]), 3) if td else None,
                "tokens": None, "note": "DSH logs no usage for the title request; small (first prompt, <=4096 output cap)"})

tot = lambda k: sum(r[k] for r in reqs)
prompt = tot("prompt_tokens"); lat = [r["latency_s"] for r in reqs]; ttft = [r["ttft_s"] for r in reqs if r["ttft_s"] is not None]
tps = [r["decode_tps"] for r in reqs if r["decode_tps"]]
wall = S(turn_end - turn_start)
import datetime
summary = {
    "turn_started_at_utc": datetime.datetime.fromtimestamp(S(turn_start), datetime.timezone.utc).isoformat(timespec="milliseconds"),
    "model": header.get("model"), "provider": header.get("provider"), "reasoning_effort": header.get("reasoningEffort"),
    "turn_end_reason": end_reason, "wall_time_s": round(wall, 3),
    "llm_requests": len(reqs), "tool_calls": sum(len(r["tool_calls"]) for r in reqs),
    "tool_calls_failed": sum(1 for r in reqs for t in r["tool_calls"] if t["error"]),
    "tool_calls_by_name": {n: sum(1 for r in reqs for t in r["tool_calls"] if t["name"] == n)
                           for n in sorted({t["name"] for r in reqs for t in r["tool_calls"]})},
    "prompt_tokens": prompt, "uncached_input_tokens": tot("uncached_input_tokens"), "cached_input_tokens": tot("cached_input_tokens"),
    "output_tokens": tot("output_tokens"), "max_prompt_tokens": max((r["prompt_tokens"] for r in reqs), default=0),
    "cache_hit_rate": round(tot("cached_input_tokens") / prompt, 4) if prompt else None,
    "cost_usd": round(sum(r["cost_usd"] for r in reqs), 6),
    "cost_usd_without_cache_discount": round((prompt * a.price_in + tot("output_tokens") * a.price_out) / 1e6, 6),
    "llm_time_s": round(sum(lat), 3), "gap_time_s": round(sum(r["gap_after_s"] for r in reqs), 3),
    "lead_s": round(reqs[0]["t_start_s"], 3) if reqs else None,
    "ttft_s_p50": round(statistics.median(ttft), 3) if ttft else None, "ttft_s_mean": round(statistics.mean(ttft), 3) if ttft else None,
    "decode_tps_p50": round(statistics.median(tps), 1) if tps else None,
    "stream_stall_s": round(sum(r["stream_stall_s"] for r in reqs), 3),
    "stream_stalls": sum(r["stream_stalls"] for r in reqs), "latency_s_p50": round(statistics.median(lat), 3) if lat else None,
    "requests_missing_cache_after_first": [r["seq"] for r in reqs[1:] if r["cached_input_tokens"] == 0],
    "pricing_usd_per_mtok": {"input": a.price_in, "cached_input": a.price_cached, "output": a.price_out},
}
os.makedirs(a.out, exist_ok=True)
json.dump({"summary": summary, "requests": reqs, "auxiliary_requests": aux,
           "trajectory": {"lead_s": summary["lead_s"], "steps": [{"u": r["uncached_input_tokens"], "c": r["cached_input_tokens"],
                          "o": r["output_tokens"], "lat": r["latency_s"], "ttft": r["ttft_s"], "gap": r["gap_after_s"]} for r in reqs]}},
          open(os.path.join(a.out, "trace.json"), "w"), indent=1)
cols = ["seq", "step", "model", "t_start_epoch_s", "t_start_s", "t_end_s", "latency_s", "ttft_s", "decode_s", "decode_tps", "stream_stalls", "stream_stall_s", "uncached_input_tokens",
        "cached_input_tokens", "output_tokens", "prompt_tokens", "stop_reason", "n_tool_calls", "tools", "tool_time_s", "gap_after_s", "cost_usd"]
with open(os.path.join(a.out, "requests.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(cols)
    for r in reqs:
        w.writerow([r["seq"], r["step"], r["model"], r["t_start_epoch_s"], r["t_start_s"], r["t_end_s"], r["latency_s"], r["ttft_s"], r["decode_s"], r["decode_tps"],
                    r["stream_stalls"], r["stream_stall_s"], r["uncached_input_tokens"], r["cached_input_tokens"], r["output_tokens"], r["prompt_tokens"], r["stop_reason"],
                    len(r["tool_calls"]), "+".join(t["name"] for t in r["tool_calls"]),
                    round(sum(t["duration_s"] or 0 for t in r["tool_calls"]), 3), r["gap_after_s"], r["cost_usd"]])
print(json.dumps({k: summary[k] for k in ("model", "wall_time_s", "llm_requests", "tool_calls", "prompt_tokens", "cached_input_tokens",
                                          "output_tokens", "cache_hit_rate", "cost_usd", "ttft_s_p50", "decode_tps_p50")}))
