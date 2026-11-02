"""Derive per-request and per-run metrics from a DSH session log and the relay's wire log.

Definitions, used throughout the project and in docs/METRICS.md:

* LLM request: one chat-completions call (one DSH agent "step"). Wire log record with path
  /v1/chat/completions.
* prompt_tokens / cached_tokens / completion_tokens: provider-reported `usage` block (exact).
  uncached_input = prompt_tokens - cached_tokens. Reasoning tokens are included in completion.
* request latency: relay receipt of the request -> last byte of the streamed response.
* TTFT: relay receipt of the request -> first streamed delta of ANY kind (reasoning, text or tool
  call). gpt-oss streams its reasoning, so this is time to the first generated token, not to the
  first visible answer word.
* decode throughput: completion_tokens / (last byte - first token), per request. It is a
  client-observed streaming rate and includes network/proxy chunking effects.
* tool execution time: DSH session log `tool/call` -> matching `tool/result` timestamps.
* cache hit rate: sum(cached_tokens) / sum(prompt_tokens).
* cost: tokens x data/pricing.json public prices (exact usage x verified prices).

When the relay log is missing (``--no-relay``), usage falls back to DSH's per-step usage. That
usage is still provider-reported, as relayed by pi-ai. TTFT then comes from the session log's
stream timestamps. Each run records which source was used.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

PRICING = json.loads((Path(__file__).resolve().parents[1] / "data" / "pricing.json").read_text())["public"]


def cost_usd(uncached: int, cached: int, output: int, prices: dict = PRICING) -> float:
    return (uncached * prices["input_per_mtok"] + cached * prices["cached_input_per_mtok"]
            + output * prices["output_per_mtok"]) / 1e6


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def _round(x, nd=3):
    return None if x is None else round(x, nd)


def parse_session(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def requests_from_wire(wire: list[dict]) -> list[dict]:
    out = []
    for r in wire:
        if r.get("path") != "/v1/chat/completions" or r.get("method") != "POST":
            continue
        usage = r.get("usage") or {}
        prompt = usage.get("prompt_tokens") or 0
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        completion = usage.get("completion_tokens") or 0
        t0, t_first, t_end = r.get("t_recv"), r.get("t_first_token"), r.get("t_end")
        gen = (t_end - t_first) if (t_first and t_end) else None
        out.append({
            "t_start": t0,
            "status": r.get("status"),
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "uncached_input_tokens": prompt - cached,
            "completion_tokens": completion,
            "latency_s": _round(t_end - t0) if t_end and t0 else None,
            "ttft_s": _round(t_first - t0) if t_first and t0 else None,
            "decode_tps": _round(completion / gen, 1) if gen and gen > 0.05 and completion > 1 else None,
            "finish_reason": r.get("finish_reason"),
            "tool_index_repairs": r.get("tool_index_repairs", 0),
            "n_messages": r.get("n_messages"),
            "usage_source": "provider (relay wire log)",
            "error": r.get("error"),
        })
    return out


def requests_from_session(events: list[dict]) -> list[dict]:
    """Fallback when no wire log exists: per-step usage + stream timestamps from DSH."""
    out, last_request_t = [], None
    for e in events:
        if e["type"] in ("request/context", "request/header"):
            last_request_t = e["time"] / 1000
        if e["type"] != "assistant/message":
            continue
        u = e["data"].get("usage") or {}
        stream = e["data"].get("stream") or []
        times = [s.get("time") or s.get("time0") for s in stream if (s.get("time") or s.get("time0"))]
        t_first = min(times) / 1000 if times else None
        t_end = e["time"] / 1000
        cached, uncached, completion = u.get("cacheReadTokens", 0), u.get("inputTokens", 0), u.get("outputTokens", 0)
        gen = t_end - t_first if t_first else None
        out.append({
            "t_start": last_request_t,
            "status": 200,
            "prompt_tokens": uncached + cached,
            "cached_tokens": cached,
            "uncached_input_tokens": uncached,
            "completion_tokens": completion,
            "latency_s": _round(t_end - last_request_t) if last_request_t else None,
            "ttft_s": _round(t_first - last_request_t) if (t_first and last_request_t) else None,
            "decode_tps": _round(completion / gen, 1) if gen and gen > 0.05 and completion > 1 else None,
            "finish_reason": None,
            "tool_index_repairs": None,
            "usage_source": "provider via DSH session log",
        })
    return out


def tool_calls_from_session(events: list[dict]) -> list[dict]:
    calls: dict[str, dict] = {}
    order = []
    for e in events:
        if e["type"] == "tool/call":
            cid = e["data"].get("callId") or f"anon-{e['seq']}"
            calls[cid] = {"name": e["data"].get("name"), "t_call": e["time"] / 1000, "step": e["data"].get("step")}
            order.append(cid)
        elif e["type"] == "tool/result":
            msg = e["data"].get("message") or {}
            cid = msg.get("toolCallId") or (msg.get("source") or {}).get("callId")
            if cid in calls:
                calls[cid]["t_result"] = e["time"] / 1000
                calls[cid]["is_error"] = bool(msg.get("isError"))
    out = []
    for cid in order:
        c = calls[cid]
        dur = c["t_result"] - c["t_call"] if "t_result" in c else None
        out.append({"name": c["name"], "step": c["step"], "duration_s": _round(dur), "is_error": c.get("is_error")})
    return out


def verify_endpoint(wire: list[dict], expected_model: str) -> dict:
    """Did every recorded chat request go to, and get answered by, the intended endpoint?"""
    chats = [r for r in wire if r.get("path", "").endswith("/chat/completions") and r.get("method") == "POST"]
    sent_ok = sum(1 for r in chats if r.get("model") == expected_model)
    answered = [r for r in chats if r.get("response_model") is not None]
    answered_ok = sum(1 for r in answered if r["response_model"] == expected_model)
    return {
        "expected_model": expected_model,
        "chat_requests": len(chats),
        "request_model_matches": sent_ok,
        "responses_with_model": len(answered),
        "response_model_matches": answered_ok,
        "guard_rejections": sum(1 for r in chats if r.get("guard_rejected")),
        "upstreams": sorted({r.get("upstream") for r in chats if r.get("upstream")}),
        "verified": bool(chats) and sent_ok == len(chats) and answered_ok == len(answered) and len(answered) > 0,
    }


def http_errors(wire: list[dict]) -> dict:
    """Non-200 chat responses, and time from the first failure to the next success."""
    chats = sorted((r for r in wire if r.get("path", "").endswith("/chat/completions")), key=lambda r: r.get("t_recv", 0))
    errors = [r for r in chats if r.get("status") != 200 or r.get("error")]
    recovery = []
    for i, r in enumerate(chats):
        if r in errors and (i == 0 or chats[i - 1] not in errors):
            nxt = next((q for q in chats[i + 1:] if q not in errors), None)
            if nxt:
                recovery.append(round(nxt["t_recv"] - r["t_recv"], 3))
    return {
        "errors": len(errors),
        "statuses": sorted({r.get("status") for r in errors}),
        "recovery_s": recovery,
        "messages": [str(r.get("error"))[:200] for r in errors][:5],
    }


def compute(session_text: str, wire: list[dict]) -> dict | None:
    events = parse_session(session_text) if session_text else []
    reqs = requests_from_wire(wire) if wire else requests_from_session(events)
    if not reqs and not events:
        return None
    tools = tool_calls_from_session(events)
    ok = [r for r in reqs if r["status"] == 200]
    prompt = sum(r["prompt_tokens"] for r in ok)
    cached = sum(r["cached_tokens"] for r in ok)
    uncached = sum(r["uncached_input_tokens"] for r in ok)
    out_tok = sum(r["completion_tokens"] for r in ok)
    ttfts = [r["ttft_s"] for r in ok if r["ttft_s"] is not None]
    tps = [r["decode_tps"] for r in ok if r["decode_tps"] is not None]
    lat = [r["latency_s"] for r in ok if r["latency_s"] is not None]
    tool_durs = [t["duration_s"] for t in tools if t["duration_s"] is not None]
    times = [e["time"] / 1000 for e in events if "time" in e]
    span = (max(times) - min(times)) if times else None
    by_name: dict[str, int] = {}
    for t in tools:
        by_name[t["name"]] = by_name.get(t["name"], 0) + 1
    return {
        "usage_source": reqs[0]["usage_source"] if reqs else None,
        "llm_requests": len(reqs),
        "llm_requests_failed": len(reqs) - len(ok),
        "prompt_tokens": prompt,
        "cached_input_tokens": cached,
        "uncached_input_tokens": uncached,
        "output_tokens": out_tok,
        "cache_hit_rate": _round(cached / prompt, 4) if prompt else None,
        "max_prompt_tokens": max((r["prompt_tokens"] for r in ok), default=None),
        "cost_usd": round(cost_usd(uncached, cached, out_tok), 6),
        "cost_usd_without_cache_discount": round(cost_usd(prompt, 0, out_tok), 6),
        "llm_time_s": _round(sum(lat)),
        "tool_time_s": _round(sum(tool_durs)),
        "session_span_s": _round(span),
        "ttft_s_p50": _round(_pct(ttfts, 0.5)),
        "ttft_s_p90": _round(_pct(ttfts, 0.9)),
        "ttft_s_mean": _round(statistics.fmean(ttfts)) if ttfts else None,
        "decode_tps_p50": _round(_pct(tps, 0.5), 1),
        "decode_tps_mean": _round(statistics.fmean(tps), 1) if tps else None,
        "latency_s_p50": _round(_pct(lat, 0.5)),
        "tool_calls": len(tools),
        "tool_calls_failed": sum(1 for t in tools if t["is_error"]),
        "tool_calls_by_name": by_name,
        "tool_index_repairs": sum(r.get("tool_index_repairs") or 0 for r in reqs),
        "http": http_errors(wire) if wire else None,
        "requests": reqs,
        "tools": tools,
    }
