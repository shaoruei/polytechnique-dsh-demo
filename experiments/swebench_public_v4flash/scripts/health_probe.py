#!/usr/bin/env python3
"""Contemporaneous endpoint-health series for the trials: one small fixed streaming request
per interval to Token Factory PUBLIC (same model), recording TTFT and decode speed.
It separates endpoint-side speed changes from workload differences. Load added: ~1 request/min.
Usage: health_probe.py OUT_JSONL [INTERVAL_S] [STOP_FILE]
"""
import datetime, json, os, sys, time, urllib.request
OUT = sys.argv[1]; IV = float(sys.argv[2]) if len(sys.argv) > 2 else 60; STOP = sys.argv[3] if len(sys.argv) > 3 else None
BODY = {"model": "deepseek-ai/DeepSeek-V4-Flash-0731", "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": 300, "temperature": 0, "messages": [{"role": "user", "content":
        "Write the integers from 1 to 120 separated by spaces. Output only the numbers."}]}
while not (STOP and os.path.exists(STOP)):
    t0 = time.time(); first = last = None; usage = None; err = None
    try:
        req = urllib.request.Request("https://api.tokenfactory.nebius.com/v1/chat/completions", data=json.dumps(BODY).encode(),
              headers={"Authorization": f"Bearer {os.environ.get('TOFA_API_KEY', 'placeholder')}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                c = json.loads(line[5:])
                if c.get("usage"): usage = c["usage"]
                d = (c.get("choices") or [{}])[0].get("delta") or {}
                if d.get("content") or d.get("reasoning_content"):
                    now = time.time(); first = first or now; last = now
    except Exception as e:  # noqa: BLE001
        err = repr(e)[:200]
    o = (usage or {}).get("completion_tokens")
    rec = {"at": datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).isoformat(timespec="seconds"),
           "ttft_s": round(first - t0, 3) if first else None, "latency_s": round(time.time() - t0, 3),
           "output_tokens": o, "decode_tps": round((o - 1) / (last - first), 1) if o and first and last and last > first else None, "error": err}
    open(OUT, "a").write(json.dumps(rec) + "\n")
    time.sleep(max(IV - (time.time() - t0), 1))
