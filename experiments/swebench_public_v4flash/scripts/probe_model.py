#!/usr/bin/env python3
"""Direct compatibility probes of the target model on Token Factory PUBLIC (no relay, no DSH).

Checks what DSH's openai-completions adapter relies on: streaming, parallel tool calls with
correct `index` values, tool-result round trip (role=tool), usage in the final stream chunk,
cached-token reporting, and `reasoning_effort` acceptance. Writes provenance/probe_<ts>.json.
Key: TOFA_API_KEY (the cloud egress proxy injects the real key; any placeholder works there).
"""
import datetime, json, os, sys, time, urllib.request

BASE = "https://api.tokenfactory.nebius.com/v1"
MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
KEY = os.environ.get("TOFA_API_KEY", "placeholder")
TOOLS = [{"type": "function", "function": {"name": "get_time", "description": "Current time in a timezone",
          "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}, "required": ["tz"]}}}]


def post(body, stream=False):
    req = urllib.request.Request(f"{BASE}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        if not stream:
            return json.load(r), {"latency_s": round(time.time() - t0, 3), "status": r.status}
        chunks, first = [], None
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            c = json.loads(line[5:]); chunks.append(c)
            if first is None and c.get("choices") and (c["choices"][0].get("delta") or {}):
                d = c["choices"][0]["delta"]
                if d.get("content") or d.get("reasoning_content") or d.get("tool_calls"):
                    first = time.time() - t0
        return chunks, {"latency_s": round(time.time() - t0, 3), "ttft_s": round(first or -1, 3), "status": r.status}


out = {"model": MODEL, "endpoint": BASE, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "checks": {}}

# 1. streaming parallel tool calls
msgs = [{"role": "user", "content": "Call get_time twice in parallel: once with tz=UTC and once with tz=Europe/Paris. Do not answer in text."}]
chunks, meta = post({"model": MODEL, "messages": msgs, "tools": TOOLS, "stream": True,
                     "stream_options": {"include_usage": True}, "max_tokens": 800, "reasoning_effort": "high"}, stream=True)
calls = {}
for c in chunks:
    for ch in c.get("choices", []):
        for tc in (ch.get("delta") or {}).get("tool_calls") or []:
            e = calls.setdefault(tc["index"], {"id": None, "name": "", "args": ""})
            e["id"] = tc.get("id") or e["id"]
            e["name"] += (tc.get("function") or {}).get("name") or ""
            e["args"] += (tc.get("function") or {}).get("arguments") or ""
usage = next((c["usage"] for c in reversed(chunks) if c.get("usage")), None)
parsed = {i: json.loads(v["args"]) for i, v in calls.items()}
out["checks"]["stream_parallel_tool_calls"] = {
    **meta, "indices": sorted(calls), "calls": calls, "usage_in_stream": usage,
    "ok": sorted(calls) == list(range(len(calls))) and len(calls) == 2 and all(v["id"] for v in calls.values())
          and {p["tz"] for p in parsed.values()} == {"UTC", "Europe/Paris"}}

# 2. tool-result round trip
asst = {"role": "assistant", "content": None, "tool_calls": [
    {"id": v["id"], "type": "function", "function": {"name": v["name"], "arguments": v["args"]}} for _, v in sorted(calls.items())]}
tool_msgs = [{"role": "tool", "tool_call_id": v["id"], "content": json.dumps({"time": "12:00", "tz": parsed[i]["tz"]})} for i, v in sorted(calls.items())]
r, meta = post({"model": MODEL, "messages": msgs + [asst] + tool_msgs, "tools": TOOLS, "max_tokens": 600})
txt = r["choices"][0]["message"].get("content") or ""
out["checks"]["tool_result_round_trip"] = {**meta, "finish_reason": r["choices"][0]["finish_reason"], "answer": txt[:200],
                                            "usage": r.get("usage"), "ok": "12:00" in txt}

# 3. prompt caching: same ~6k-token prefix twice
prefix = "Reference text. " + " ".join(f"line {i}: the quick brown fox jumps over the lazy dog." for i in range(600))
cache = []
for k in range(2):
    r, meta = post({"model": MODEL, "max_tokens": 20, "messages": [{"role": "system", "content": prefix},
                    {"role": "user", "content": f"Reply with the word ok. ({k})"}]})
    cache.append({**meta, "usage": r.get("usage")})
    time.sleep(1)
ct = (cache[1]["usage"].get("prompt_tokens_details") or {}).get("cached_tokens")
out["checks"]["prompt_caching"] = {"requests": cache, "second_cached_tokens": ct, "ok": bool(ct)}

# 4. reasoning effort accepted
eff = {}
for e in ("low", "high"):
    r, meta = post({"model": MODEL, "reasoning_effort": e, "max_tokens": 2000,
                    "messages": [{"role": "user", "content": "How many primes are below 60? Answer with the number."}]})
    m = r["choices"][0]["message"]
    eff[e] = {**meta, "answer": (m.get("content") or "")[:40], "reasoning_tokens":
              ((r.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"), "usage": r.get("usage")}
out["checks"]["reasoning_effort"] = {**eff, "ok": all(v["status"] == 200 for v in eff.values())}

out["all_ok"] = all(v["ok"] for v in out["checks"].values())
os.makedirs("provenance", exist_ok=True)
fn = f"provenance/probe_{out['at'].replace(':', '').replace('-', '')[:15]}Z.json"
json.dump(out, open(fn, "w"), indent=1)
print(fn); print(json.dumps({k: v["ok"] for k, v in out["checks"].items()}), "all_ok=", out["all_ok"])
print("stream:", out["checks"]["stream_parallel_tool_calls"]["indices"], out["checks"]["stream_parallel_tool_calls"]["usage_in_stream"],
      "ttft", out["checks"]["stream_parallel_tool_calls"]["ttft_s"])
print("cache:", [c["usage"] for c in cache])
print("effort:", {e: (v["reasoning_tokens"], v["answer"]) for e, v in eff.items()})
