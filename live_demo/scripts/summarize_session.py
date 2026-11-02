#!/usr/bin/env python3
"""Summarize a decoded DSH session (JSONL) into trajectory.md + metrics.json,
and flag anything that could invalidate the run as a benchmark attempt.

Usage: summarize_session.py SESSION_JSONL OUT_DIR
"""
import json, re, sys, os

src, out = sys.argv[1], sys.argv[2]
ev = [json.loads(l) for l in open(src) if l.strip()]
calls, results = [], {}
for d in ev:
    if d["type"] == "tool/call":
        calls.append(d)
    elif d["type"] == "tool/result":
        m = d["data"]["message"]
        results[m.get("toolCallId")] = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict))

t_start = next((d["time"] for d in ev if d["type"] == "turn/start"), None)
t_end = max((d["time"] for d in ev if d["type"] == "turn/end"), default=None)
ends = [d["data"].get("reason", {}).get("kind") for d in ev if d["type"] == "turn/end"]
hdr = next((d["data"]["header"]["config"] for d in ev if d["type"] == "request/header"), {})
steps = sum(1 for d in ev if d["type"] == "step/start")
reasoning = [c.get("text", "") for d in ev if d["type"] == "assistant/message"
             for c in d["data"]["message"]["content"] if c.get("type") == "reasoning"]

NET = re.compile(r"\b(curl|wget|pip(3)?\s+(download|install)|uv\s+pip|git\s+(fetch|clone|pull|remote)|http[s]?://)", re.I)
import base64
HINT = re.compile(base64.b64decode("c3dlLT9iZW5jaHxkamFuZ29fX2RqYW5nb3wxNjEzNnwjPzM0MDYyfDliMGM5ODIx").decode(), re.I)  # encoded: keep task identifiers out of the agent-readable kit
CWD = next((d.get("cwd") for d in ev if d["type"] == "session"), None) or "/nonexistent"


def outside_workspace_search(args):
    """A filesystem search or history probe that reaches beyond the session's workspace."""
    try:
        cmd = json.loads(args).get("command", args)
    except Exception:
        cmd = args
    if re.search(r"find\s+/(\s|$)|git\s+log\s+--all", cmd):
        return True
    if re.search(r"\b(find|ls|grep|locate|du|tree)\b", cmd):
        paths = re.findall(r"(?<![\w.-])(~[\w/.-]*|/[\w/.-]+)", cmd)
        return any(not (p.startswith(CWD) or p.startswith(("/dev/null", "/dev/"))) and
                   re.match(r"(~|/root|/tmp|/opt|/usr|/home|/var|/srv|/mnt)(/|$)", p) for p in paths)
    return False


flags = []
for d in calls:
    name, args = d["data"]["name"], d["data"]["arguments"]
    if name in ("web_search", "web_fetch"):
        res = results.get(d["data"]["callId"], "")
        ok = not re.search(r"error|unavailable|no api key", res[:400], re.I)
        flags.append({"kind": name, "succeeded": ok, "args": args[:300]})
    elif name == "bash" and NET.search(args):
        flags.append({"kind": "bash-network", "args": args[:300]})
    if name == "bash" and outside_workspace_search(args):
        flags.append({"kind": "search-outside-workspace", "args": args[:300]})
    if HINT.search(args):
        flags.append({"kind": "benchmark-hint-in-tool-args", "tool": name, "args": args[:300]})
for r in reasoning:
    m = HINT.search(r)
    if m:
        flags.append({"kind": "benchmark-hint-in-reasoning", "match": m.group(0), "excerpt": r[max(0, m.start()-120):m.end()+120]})
contaminated = any(f["kind"] in ("web_fetch", "web_search") and f.get("succeeded") for f in flags) \
    or any(f["kind"] == "bash-network" for f in flags)

metrics = {
    "model": hdr.get("model"), "provider": hdr.get("provider"), "reasoningEffort": hdr.get("reasoningEffort"),
    "turn_end_reasons": ends, "wall_seconds": round((t_end - t_start) / 1000, 1) if t_start and t_end else None,
    "steps": steps, "tool_calls": len(calls),
    "tool_call_counts": {n: sum(1 for c in calls if c["data"]["name"] == n) for n in sorted({c["data"]["name"] for c in calls})},
    "integrity_flags": flags, "integrity_verdict": "CONTAMINATED" if contaminated else ("REVIEW" if flags else "CLEAN"),
}
os.makedirs(out, exist_ok=True)
json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
with open(os.path.join(out, "trajectory.md"), "w") as f:
    f.write(f"# Trajectory\n\nmodel `{metrics['model']}` via `{metrics['provider']}`, effort `{metrics['reasoningEffort']}`; "
            f"{metrics['wall_seconds']} s, {steps} steps, {len(calls)} tool calls; integrity: **{metrics['integrity_verdict']}**\n\n")
    i = 0
    for d in ev:
        if d["type"] == "assistant/message":
            for c in d["data"]["message"]["content"]:
                if c.get("type") == "reasoning" and c.get("text", "").strip():
                    f.write(f"> _think:_ {c['text'].strip()[:600]}\n\n")
                elif c.get("type") == "text" and c.get("text", "").strip():
                    f.write(f"**assistant:** {c['text'].strip()}\n\n")
        elif d["type"] == "tool/call":
            i += 1
            a = d["data"]["arguments"]
            try:
                a = json.loads(a); a = a.get("command") or a.get("file_path") or a.get("url") or a.get("queries") or a
            except Exception:
                pass
            res = results.get(d["data"]["callId"], "").strip().replace("\n", "\n    ")
            f.write(f"{i}. `{d['data']['name']}`: `{str(a)[:400]}`\n\n    {res[:500]}{' …' if len(res) > 500 else ''}\n\n")
print(json.dumps({k: metrics[k] for k in ("model", "wall_seconds", "steps", "tool_calls", "integrity_verdict")}))
for fl in flags:
    print("FLAG", json.dumps(fl)[:300])
