"""Fold the SWE-bench / DeepSeek-V4-Flash public trials into one dashboard data file.

Reads only experiments/swebench_public_v4flash/ (recorded results, no API calls) and writes
data/swebench.json. The GPT-OSS data files (runs.json, replays.json, ...) are not touched.

    python3 analysis/build_swebench.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "analysis"))
from build_data import replay_events  # noqa: E402
from sanitize import sanitize_text  # noqa: E402

EXP = ROOT / "experiments" / "swebench_public_v4flash"
OUT = ROOT / "data" / "swebench.json"
# the separate API load benchmark (same public model, same account, same afternoon); optional until merged
LOAD_PHASES = ROOT / "data" / "deepseek_v4_endpoint_load" / "phases.jsonl"


def jl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def diff_stat(patch: str) -> dict:
    files, added, removed = [], 0, 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            files.append(line.split(" b/", 1)[-1])
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"files": files, "lines_added": added, "lines_removed": removed}


def attach_edits(run_dir: Path, events: list[dict], workdir: str) -> None:
    """Give each replayed `edit` call its full file / old / new text, so the viewer can show the source change."""
    calls = []
    for line in (run_dir / "session.jsonl").read_text().splitlines():
        e = json.loads(line) if line.strip() else {}
        if e.get("type") == "assistant/message":
            calls += [b for b in e["data"]["message"]["content"] if b["type"] == "tool-call"]
    replayed = [ev for ev in events if ev["k"] == "call"]
    assert len(calls) == len(replayed), (run_dir, len(calls), len(replayed))
    for block, ev in zip(calls, replayed):
        if block["name"] != "edit":
            continue
        try:
            args = json.loads(block.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        clip = lambda t: sanitize_text(t if len(t) <= 2000 else t[:1999] + "\u2026")  # noqa: E731
        ev["edit"] = {
            "file": str(args.get("file_path", "")).replace(workdir + "/", ""),
            "old": clip(args.get("old_string", "")), "new": clip(args.get("new_string", "")),
        }


def instance_info(iid: str) -> dict:
    row = json.loads((EXP / "instances" / iid / "instance.json").read_text())[0]
    gold_files = re.findall(r"^diff --git a/(\S+)", row["patch"], flags=re.M)
    return {
        "instance_id": iid,
        "repo": row["repo"],
        "version": row["version"],
        "title": row["problem_statement"].strip().splitlines()[0].strip(),
        "fix_files": gold_files,
        "f2p": len(json.loads(row["FAIL_TO_PASS"]) if isinstance(row["FAIL_TO_PASS"], str) else row["FAIL_TO_PASS"]),
        "p2p": len(json.loads(row["PASS_TO_PASS"]) if isinstance(row["PASS_TO_PASS"], str) else row["PASS_TO_PASS"]),
        # the exact text pasted into the Web UI (agent-safe kit; no gold patch, no test names)
        "prompt": sanitize_text((EXP / "instances" / iid / "kit" / "prompt.txt").read_text()),
    }


def load_overlap(requests: list[dict]) -> tuple[list[dict], dict | None]:
    """Benchmark phases on the public endpoint as time intervals, and how the agent's decode speed
    differed inside and outside them. Correlation only: the two sessions used the same public model at the same time."""
    if not LOAD_PHASES.exists():
        return [], None
    phases = []
    for p in jl(LOAD_PHASES):
        if p.get("endpoint") != "public" or "started_at" not in p or p.get("exclude_from_summary"):
            continue
        start = datetime.fromisoformat(p["started_at"]).timestamp()
        rpm = p.get("offered_rpm")
        if rpm is None and p.get("kind") == "scaling":  # closed loop: report the achieved request rate
            rpm = round(60 * p.get("connections_opened", 0) / p["elapsed_s"])
        phases.append({"start": start, "end": start + p["elapsed_s"], "kind": p["kind"], "profile": p.get("profile"),
                       "concurrency": p.get("concurrency"), "rpm": rpm, "stop_reason": p.get("stop_reason")})
    inside = lambda t: any(ph["start"] <= t <= ph["end"] for ph in phases)  # noqa: E731
    a = sorted(q["tps"] for q in requests if inside(q["t"]))
    b = sorted(q["tps"] for q in requests if not inside(q["t"]))
    med = lambda v: v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2  # noqa: E731
    peak = max(phases, key=lambda ph: ph["rpm"] or 0)
    text = (f"agent requests sent while a benchmark phase was running decoded at a median {med(a):.0f} tok/s (n={len(a)}), "
            f"those outside at {med(b):.0f} tok/s (n={len(b)}). The slowest trial ran during the {peak['rpm']:.0f} req/min step, "
            f"which offered more than the published 1,000 req/min limit and ended on {peak['stop_reason'] or 'schedule'}. "
            "This is a correlation within one afternoon, not a controlled experiment.")
    return phases, {"inside_p50": med(a), "inside_n": len(a), "outside_p50": med(b), "outside_n": len(b), "text": text}


def main() -> None:
    export = json.loads((EXP / "export" / "runs.json").read_text())
    workload = json.loads((EXP / "export" / "workload.json").read_text())
    catalog = json.loads((EXP / "provenance" / "tofa_model_entry.json").read_text())
    comparison = {c["run_id"]: c for c in json.loads((EXP / "export" / "patch_comparison.json").read_text())}

    runs, replays, requests, instances = [], {}, [], {}
    for rec in export["runs"]:
        rid = rec["run_id"]
        rdir = EXP / "runs" / rid
        iid = rec["instance_id"]
        instances.setdefault(iid, instance_info(iid) | {"alias": rec["alias"]})
        report = json.loads((rdir / "official-eval" / "report.json").read_text())[iid]
        patch = sanitize_text((rdir / "diff.patch").read_text())
        events = replay_events(rdir)
        workdir = json.loads((rdir / "session.jsonl").read_text().splitlines()[0]).get("cwd", "")
        attach_edits(rdir, events, workdir)
        replays[rid] = events
        final = next((e["text"] for e in reversed(events) if e["k"] == "say"), "")
        trace = json.loads((rdir / "trace.json").read_text())
        for q in trace["requests"]:
            requests.append({
                "run": rid, "seq": q["seq"], "t": q["t_start_epoch_s"], "ts": q["t_start_s"],
                "ttft": q["ttft_s"], "lat": q["latency_s"], "tps": q["decode_tps"], "tpsx": q["decode_tps_excl_stalls"],
                "stalls": q["stream_stalls"], "stall_s": q["stream_stall_s"],
                "u": q["uncached_input_tokens"], "c": q["cached_input_tokens"], "o": q["output_tokens"],
                "cost": q["cost_usd"], "gap": q["gap_after_s"], "tools": [t["name"] for t in q.get("tool_calls", [])],
            })
        ts = report["tests_status"]
        runs.append({
            "run_id": rid, "instance_id": iid, "alias": rec["alias"], "trial": rec["trial"],
            "started_at": rec["started_at"], "turn_started_at_utc": rec["metrics"]["turn_started_at_utc"],
            "model": rec["model"], "endpoint": rec["endpoint"], "effort": rec["reasoning_effort"], "harness": rec["harness"],
            "success": rec["success"], "wall_time_s": rec["wall_time_s"], "metrics": rec["metrics"],
            "official": {
                "resolved": report["resolved"], "applied": report["patch_successfully_applied"],
                "f2p_pass": ts["FAIL_TO_PASS"]["success"], "f2p_fail": ts["FAIL_TO_PASS"]["failure"],
                "p2p_pass": len(ts["PASS_TO_PASS"]["success"]), "p2p_fail": ts["PASS_TO_PASS"]["failure"],
            },
            "integrity": rec["integrity_verdict"],
            "patch": patch, "diff": diff_stat(patch),
            "gold_files_only": comparison[rid]["same_files_as_gold"],
            "identical_to_gold": comparison[rid]["byte_identical_to_gold"],
            "test_files_changed": comparison[rid]["test_files_changed"],
            "final_answer": final,
            "trajectory": rec["trajectory"],
        })
    runs.sort(key=lambda r: r["started_at"])
    requests.sort(key=lambda q: q["t"])
    health = jl(EXP / "provenance" / "endpoint_health_series.jsonl")
    phases, overlap = load_overlap(requests)
    out = {
        "schema": 1,
        "source": "experiments/swebench_public_v4flash (recorded 2026-11-02; see docs/SWEBENCH_PUBLIC_V4FLASH.md)",
        "model": export["model"], "endpoint": export["endpoint"], "base_url": export["base_url"], "harness": workload["harness"],
        "pricing": workload["pricing_public"],
        "catalog": {k: catalog["entry"].get(k) for k in ("context_length", "quantization")},
        "instances": instances, "runs": runs, "replays": replays, "requests": requests, "health": health,
        "pooled": workload["pooled"], "groups": workload["groups"],
        "load_phases": phases, "load_overlap": overlap,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(runs)} runs, {len(requests)} requests, {sum(map(len, replays.values()))} replay events, {len(health)} health probes, {len(phases)} load-benchmark phases")


if __name__ == "__main__":
    main()
