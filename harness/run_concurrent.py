#!/usr/bin/env python3
"""Bounded concurrency waves: N DSH agents started together, each in its own workspace.

    python3 harness/run_concurrent.py --endpoint dedicated --levels 2 3 5 --waves 1

Each agent is a separate `run_task.py` process (own scratch workspace, own DSH_HOME, own relay),
started at the same moment. Tasks rotate T3, T1, T2 so every wave mixes task types. Hard limits:
at most 5 agents at once (MAX_AGENTS), a per-agent timeout, and a wall-clock budget for the whole
call. A wave is summarised in runs/waves/<wave-id>.json.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_AGENTS = 5
ROTATION = ["t3", "t1", "t2"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="dedicated")
    ap.add_argument("--levels", type=int, nargs="+", default=[2, 3, 5])
    ap.add_argument("--waves", type=int, default=1, help="waves per level")
    ap.add_argument("--timeout", type=int, default=300, help="per-agent timeout (s)")
    ap.add_argument("--budget-s", type=int, default=600, help="stop starting new waves after this many seconds")
    ap.add_argument("--effort", default="medium")
    args = ap.parse_args()
    if max(args.levels) > MAX_AGENTS:
        raise SystemExit(f"refusing: more than {MAX_AGENTS} concurrent agents")
    (ROOT / "runs" / "waves").mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()
    offset = 0
    for level in args.levels:
        for w in range(args.waves):
            if time.monotonic() - t_start > args.budget_s:
                print("time budget reached; not starting more waves")
                return 2
            wave = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_c{level}_{args.endpoint}"
            tasks = [ROTATION[(offset + i) % len(ROTATION)] for i in range(level)]
            offset += level
            print(f"\n=== wave {wave}: {level} agents {tasks}", flush=True)
            t0 = time.time()
            procs = []
            for i, task in enumerate(tasks):
                cmd = [sys.executable, str(ROOT / "harness" / "run_task.py"), task, "--endpoint", args.endpoint,
                       "--effort", args.effort, "--timeout", str(args.timeout), "--cohort", f"conc-{level}",
                       "--wave", wave, "--suffix", f"c{level}a{i}", "--label", "concurrency"]
                procs.append(subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
            outputs = [p.communicate()[0] for p in procs]
            t1 = time.time()
            run_ids = []
            for out in outputs:
                rid = next((ln.split()[1].rstrip(":") for ln in out.splitlines() if ln.startswith("run ")), None)
                run_ids.append(rid)
                tail = [ln for ln in out.splitlines() if ln.startswith(("success", "wall time"))]
                print(f"  {rid}: {' | '.join(tail)}")
            summary = {"wave": wave, "endpoint": args.endpoint, "level": level, "tasks": tasks, "run_ids": run_ids,
                       "t_start": t0, "t_end": t1, "wall_s": round(t1 - t0, 3)}
            (ROOT / "runs" / "waves" / f"{wave}.json").write_text(json.dumps(summary, indent=1) + "\n")
            print(f"  wave wall time {t1 - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
