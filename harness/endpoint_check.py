#!/usr/bin/env python3
"""Phase-1 compatibility check of one endpoint, with minimal requests and no relay in between.

    python3 harness/endpoint_check.py dedicated [--tool-trials 3]

1. GET /v1/models: is the routing key listed?
2. non-streaming chat completion (tiny)
3. streaming chat completion (tiny): TTFT, usage in the stream
4. streaming tool call, repeated: raw tool_call deltas are checked for the index/id anomaly seen on
   the public endpoint (last argument fragment with a new index and no id)

Writes data/provenance/stream_compat_<endpoint>_<UTC date>.json (sanitised: request shapes, response
models, usage, timings and the raw tool_call deltas; no headers, no credentials).
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from endpoints import get_endpoint  # noqa: E402
from tofa_relay import ToolCallIndexRepair  # noqa: E402

TOOL = {"type": "function", "function": {"name": "read", "description": "Read a text file",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "offset": {"type": "number"},
                                                        "limit": {"type": "number"}}, "required": ["file_path"]}}}


def post(origin, path, body, stream=False, timeout=120):
    key = os.environ.get("TOFA_API_KEY", "proxy-injected")  # placeholder; the egress proxy injects the real key
    req = urllib.request.Request(origin + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:500], "latency_s": round(time.time() - t0, 3)}
    if not stream:
        data = json.loads(resp.read())
        return {"status": resp.status, "latency_s": round(time.time() - t0, 3), "response_model": data.get("model"),
                "usage": data.get("usage"), "finish_reason": data["choices"][0].get("finish_reason"),
                "content": (data["choices"][0]["message"].get("content") or "")[:200]}
    chunks, first, model, usage, finish = [], None, None, None, None
    for raw in resp:
        line = raw.decode()
        if not line.startswith("data: ") or line.strip() == "data: [DONE]":
            continue
        c = json.loads(line[6:])
        model = model or c.get("model")
        usage = c.get("usage") or usage
        for ch in c.get("choices") or []:
            d = ch.get("delta") or {}
            if first is None and (d.get("content") or d.get("reasoning_content") or d.get("reasoning") or d.get("tool_calls")):
                first = time.time()
            finish = ch.get("finish_reason") or finish
        chunks.append(c)
    return {"status": resp.status, "latency_s": round(time.time() - t0, 3), "ttft_s": round(first - t0, 3) if first else None,
            "response_model": model, "usage": usage, "finish_reason": finish, "chunks": chunks}


def tool_analysis(chunks):
    deltas = [tc for c in chunks for ch in (c.get("choices") or []) for tc in ((ch.get("delta") or {}).get("tool_calls") or [])]
    det = ToolCallIndexRepair()
    for c in chunks:
        det.fix_chunk(json.loads(json.dumps(c)), apply=False)
    # reassemble as a spec-following client would (by index)
    calls = {}
    for tc in deltas:
        i = tc.get("index")
        e = calls.setdefault(i, {"id": None, "name": None, "arguments": ""})
        e["id"] = e["id"] or tc.get("id")
        e["name"] = e["name"] or (tc.get("function") or {}).get("name")
        e["arguments"] += (tc.get("function") or {}).get("arguments") or ""
    parsed_ok = []
    for e in calls.values():
        try:
            json.loads(e["arguments"])
            parsed_ok.append(bool(e["name"]))
        except ValueError:
            parsed_ok.append(False)
    return {"n_deltas": len(deltas), "anomalies": det.repairs, "calls_seen_by_spec_client": len(calls),
            "all_calls_valid_without_repair": all(parsed_ok) and len(calls) >= 1,
            "raw_tool_call_deltas": deltas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("endpoint")
    ap.add_argument("--tool-trials", type=int, default=3)
    args = ap.parse_args()
    ep = get_endpoint(args.endpoint)
    o, model = ep["origin"], ep["model"]
    out = {"endpoint": ep["name"], "label": ep["label"], "origin": o, "model": model,
           "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    req = urllib.request.Request(o + "/v1/models", headers={"Authorization": "Bearer " + os.environ.get("TOFA_API_KEY", "proxy-injected")})
    with urllib.request.urlopen(req, timeout=30) as r:
        ids = [m["id"] for m in json.load(r)["data"]]
    out["models_listed"] = model in ids
    print(f"[{ep['name']}] model listed: {out['models_listed']}")

    base = {"model": model, "max_tokens": 200, "reasoning_effort": "low",
            "messages": [{"role": "user", "content": "Reply with exactly the word OK."}]}
    r = post(o, "/v1/chat/completions", base)
    out["non_streaming"] = r
    print(f"[{ep['name']}] non-streaming: HTTP {r['status']} model={r.get('response_model')} {r.get('latency_s')}s content={r.get('content')!r} usage={r.get('usage')}")

    r = post(o, "/v1/chat/completions", {**base, "stream": True, "stream_options": {"include_usage": True}}, stream=True)
    r.pop("chunks", None)
    out["streaming"] = r
    print(f"[{ep['name']}] streaming: HTTP {r['status']} model={r.get('response_model')} ttft={r.get('ttft_s')}s total={r.get('latency_s')}s usage={r.get('usage')}")

    tool_body = {"model": model, "stream": True, "stream_options": {"include_usage": True}, "max_tokens": 300,
                 "reasoning_effort": "low", "tools": [TOOL],
                 "messages": [{"role": "system", "content": "You are a coding agent. Use tools."},
                              {"role": "user", "content": "Read the file gradebook/grades.py from line 1, with a limit of 2000 lines."}]}
    out["tool_trials"] = []
    for i in range(args.tool_trials):
        r = post(o, "/v1/chat/completions", tool_body, stream=True)
        a = tool_analysis(r.pop("chunks", []))
        out["tool_trials"].append({**r, **a})
        print(f"[{ep['name']}] tool call #{i + 1}: HTTP {r['status']} model={r.get('response_model')} deltas={a['n_deltas']} "
              f"anomalies={a['anomalies']} valid_without_repair={a['all_calls_valid_without_repair']} ttft={r.get('ttft_s')}s")
    trials = out["tool_trials"]
    out["summary"] = {
        "all_responses_from_expected_model": all(t.get("response_model") == model for t in [out["non_streaming"], out["streaming"], *trials]),
        "tool_trials": len(trials),
        "tool_trials_with_index_anomaly": sum(1 for t in trials if t["anomalies"]),
        "relay_repair_needed": any(t["anomalies"] for t in trials),
    }
    print(f"[{ep['name']}] summary: {out['summary']}")
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    path = ROOT / "data" / "provenance" / f"stream_compat_{ep['name']}_{day}.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
