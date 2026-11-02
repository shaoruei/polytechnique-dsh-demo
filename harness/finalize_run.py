#!/usr/bin/env python3
"""Re-run post-processing for a run whose harness crashed after the agent finished.

    python3 harness/finalize_run.py <run-id>

Needs the preserved scratch workspace (.cache/runs/<run-id>). Uses meta.json when the harness wrote
one. Otherwise it reconstructs the metadata from events.jsonl, the wave file and the session log,
and marks the wall time as reconstructed. No model requests are made.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import run_task  # noqa: E402


def reconstruct(run_id: str, scratch: Path, out: Path) -> dict:
    events, skipped = [], 0
    for line in (out / "events.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            skipped += 1  # line damaged by the pre-fix sanitiser; the raw stdout is not recoverable
    session = [json.loads(l) for l in run_task.decode_session(run_task.find_session_log(scratch / "dsh-home", None)).splitlines() if l.strip()]
    parts = run_id.split("_")
    task = parts[1]
    endpoint = "dedicated" if "dedicated" in parts else "public"
    wave_file = next((f for f in (ROOT / "runs" / "waves").glob("*.json") if run_id in json.loads(f.read_text())["run_ids"]
                      or any((r or "").startswith(run_id) for r in json.loads(f.read_text())["run_ids"])), None)
    if wave_file is None:  # the wave summary lists None for runs whose output was lost; match by wave prefix
        wave_file = next(f for f in (ROOT / "runs" / "waves").glob(f"{parts[0]}*.json"))
    wave = json.loads(wave_file.read_text())
    t_start = wave["t_start"]
    t_last = max(e["time"] for e in session if "time" in e) / 1000
    level = wave["level"]
    final = next((e.get("text", "") for e in reversed(events) if e.get("type") == "final"), None)
    turn_end = next((e.get("reason") for e in reversed(events) if e.get("type") == "status" and e.get("phase") == "turn_end"), None)
    return {
        "run_id": run_id, "label": "concurrency", "task": run_task.resolve_task(task).name, "endpoint": endpoint,
        "cohort": f"conc-{level}", "wave": wave["wave"], "effort": parts[2], "permission_mode": "workspace-write",
        "relay": True, "started_at": dt.datetime.fromtimestamp(t_start, dt.timezone.utc).isoformat(),
        "ended_at": dt.datetime.fromtimestamp(t_last, dt.timezone.utc).isoformat(),
        "wall_time_s": round(t_last - t_start, 3), "timeout_s": 300, "timed_out": False, "dsh_exit_code": None,
        "dsh_stderr_tail": "", "turn_end_reason": turn_end, "agent_final_answer": final,
        "session_id": next((e.get("sessionId") for e in events if e.get("type") == "session"), None),
        "wall_time_source": "reconstructed: wave start -> last DSH session event (harness post-processing crashed)",
        "finalized_offline": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "events_lines_unparseable": skipped,
    }


def main() -> int:
    run_id = sys.argv[1]
    scratch, out = ROOT / ".cache" / "runs" / run_id, ROOT / "runs" / run_id
    meta_path = scratch / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else reconstruct(run_id, scratch, out)
    meta.setdefault("finalized_offline", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    run_task.finalize(meta, scratch, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
