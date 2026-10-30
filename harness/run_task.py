#!/usr/bin/env python3
"""Run one coding task with DeepSeek Harness (DSH) on Nebius Token Factory and record everything.

    python3 harness/run_task.py t1 --live

For each run, the harness:
  1. copies the task's fixture workspace into a fresh scratch directory (a throwaway git repo),
  2. runs `dsh --profile headless --json` in it with the Token Factory overlay (dsh/tofa.patch.yml),
     under a hard wall-clock timeout,
  3. judges the result itself: it runs the pristine visible tests plus the hidden acceptance tests
     against the agent's code. The agent's own claim of success is never trusted,
  4. decodes DSH's session log and derives per-request metrics (harness/metrics.py),
  5. writes runs/<run-id>/{result.json, events.jsonl, session.jsonl, diff.patch, prompt.md}.

Credentials: the harness never reads or writes an API key. `apiKeyEnv: TOFA_API_KEY` in the overlay
names an environment variable. In the Claude Code cloud environment that variable gets a dummy
placeholder, because the egress proxy injects the real key. Elsewhere, export your own key before
running.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402
import tofa_relay  # noqa: E402
from sanitize import sanitize_text  # noqa: E402

TASKS_DIR = ROOT / "tasks"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / ".cache" / "runs"
PATCH = ROOT / "dsh" / "tofa.patch.yml"
DECODER = ROOT / "harness" / "decode_session.mjs"
PLACEHOLDER_KEY = "proxy-injected"  # not a secret: the egress proxy replaces it


def resolve_task(name: str) -> Path:
    matches = sorted(p for p in TASKS_DIR.iterdir() if p.is_dir() and (p.name == name or p.name.startswith(name + "-")))
    if len(matches) != 1:
        raise SystemExit(f"unknown or ambiguous task {name!r}; available: {[p.name for p in TASKS_DIR.iterdir() if p.is_dir()]}")
    return matches[0]


def dsh_version() -> str:
    return subprocess.run(["dsh", "--version"], capture_output=True, text=True, check=True).stdout.strip()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def init_workspace(task_dir: Path, work: Path) -> None:
    shutil.copytree(task_dir / "workspace", work)
    git(work, "init", "-q", "-b", "main")
    git(work, "-c", "user.email=harness@example.invalid", "-c", "user.name=harness", "add", "-A")
    git(work, "-c", "user.email=harness@example.invalid", "-c", "user.name=harness", "commit", "-q", "-m", "fixture")


UNITTEST_SUMMARY = re.compile(r"^Ran (\d+) tests? in", re.M)
UNITTEST_FAIL = re.compile(r"^FAILED \(([^)]*)\)", re.M)


def run_unittests(cwd: Path, timeout: int = 120) -> dict:
    """Run `python3 -m unittest discover -s tests` and parse its summary."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = f"TIMEOUT after {timeout}s\n{exc.stdout or ''}{exc.stderr or ''}", -1
    ran = UNITTEST_SUMMARY.search(output)
    failed = {"failures": 0, "errors": 0}
    m = UNITTEST_FAIL.search(output)
    if m:
        for part in m.group(1).split(","):
            key, _, val = part.strip().partition("=")
            if key in failed:
                failed[key] = int(val)
    total = int(ran.group(1)) if ran else 0
    ok = code == 0 and ran is not None and total > 0
    return {
        "ok": ok,
        "exit_code": code,
        "tests_run": total,
        "failures": failed["failures"],
        "errors": failed["errors"],
        "duration_s": round(time.monotonic() - started, 3),
        "output_tail": output[-3000:],
    }


def acceptance(task_dir: Path, work: Path) -> dict:
    """Judge the agent's code with the pristine visible tests plus the hidden tests."""
    with tempfile.TemporaryDirectory() as tmp:
        judge = Path(tmp) / "judge"
        shutil.copytree(work, judge, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        shutil.rmtree(judge / "tests", ignore_errors=True)
        shutil.copytree(task_dir / "workspace" / "tests", judge / "tests")
        for hidden in (task_dir / "hidden").glob("*.py"):
            shutil.copy(hidden, judge / "tests" / hidden.name)
        return run_unittests(judge)


def modified_test_files(task_dir: Path, work: Path) -> list[str]:
    changed = []
    for f in (task_dir / "workspace" / "tests").rglob("*.py"):
        rel = f.relative_to(task_dir / "workspace")
        if not (work / rel).exists() or (work / rel).read_bytes() != f.read_bytes():
            changed.append(str(rel))
    return changed


def find_session_log(dsh_home: Path, session_id: str | None) -> Path | None:
    logs = list((dsh_home / "sessions").rglob("session.v4.jsonl.zstd"))
    if session_id:
        logs = [p for p in logs if p.parent.name == session_id] or logs
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def decode_session(path: Path) -> str:
    return subprocess.run(["node", str(DECODER), str(path)], capture_output=True, text=True, check=True).stdout


def pretty(event: dict, t0: float) -> str | None:
    """One human-readable line per streamed event, for the live demo."""
    t = f"{time.monotonic() - t0:6.1f}s"
    kind = event.get("type")
    if kind == "session":
        return f"{t}  session {event.get('sessionId')}"
    if kind == "status":
        phase = event.get("phase")
        if phase == "step_end":
            u = event.get("usage") or {}
            return (f"{t}  └ step {event.get('step')} done: in={u.get('inputTokens', 0)} "
                    f"cached={u.get('cacheReadTokens', 0)} out={u.get('outputTokens', 0)}")
        if phase == "step_start":
            return f"{t}  ┌ LLM request #{event.get('step')}"
        if phase == "turn_end":
            return f"{t}  turn ended: {json.dumps(event.get('reason'))[:200]}"
        return None
    if kind == "thinking":
        text = " ".join(event.get("text", "").split())
        return f"{t}  │ thinking: {text[:160]}{'...' if len(text) > 160 else ''}"
    if kind == "text":
        text = " ".join(event.get("text", "").split())
        return f"{t}  │ says: {text[:200]}{'...' if len(text) > 200 else ''}"
    if kind == "tool_call":
        args = event.get("arguments") or event.get("input") or {}
        if isinstance(args, dict):
            detail = args.get("command") or args.get("path") or args.get("file_path") or args.get("pattern") or json.dumps(args)
        else:
            detail = str(args)
        detail = " ".join(str(detail).split())
        return f"{t}  │ \U0001f527 {event.get('name') or event.get('tool')}: {detail[:160]}"
    if kind == "tool_result":
        content = event.get("output") or event.get("content") or event.get("result") or ""
        if not isinstance(content, str):
            content = json.dumps(content)
        first = " ".join(content.split())[:140]
        flag = " (error)" if event.get("isError") or event.get("error") else ""
        return f"{t}  │   ↳ result{flag}: {first}"
    if kind == "final":
        return f"{t}  final answer: {' '.join(event.get('text', '').split())[:300]}"
    if kind == "error":
        return f"{t}  ERROR: {json.dumps(event)[:300]}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", help="task id prefix, e.g. t1 or t2-duration-parser")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"], help="gpt-oss reasoning effort")
    ap.add_argument("--timeout", type=int, default=600, help="hard wall-clock limit for the agent (s)")
    ap.add_argument("--permission-mode", default="workspace-write",
                    choices=["workspace-write", "danger-full-access"], help="DSH_PERMISSION_MODE")
    ap.add_argument("--live", action="store_true", help="print the agent trajectory while it runs")
    ap.add_argument("--label", default="", help="free-form label stored with the run (e.g. 'live-demo')")
    ap.add_argument("--no-relay", action="store_true",
                    help="talk to Token Factory directly (tool calls break on the current stream bug)")
    ap.add_argument("--keep-workdir", action="store_true", help="keep the scratch workspace and DSH home")
    args = ap.parse_args()

    task_dir = resolve_task(args.task)
    prompt = (task_dir / "task.md").read_text()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{task_dir.name.split('-')[0]}_{args.effort}"
    out = RUNS_DIR / run_id
    scratch = CACHE_DIR / run_id
    work, dsh_home = scratch / "workspace", scratch / "dsh-home"
    out.mkdir(parents=True)
    scratch.mkdir(parents=True)
    init_workspace(task_dir, work)
    (out / "prompt.md").write_text(prompt)

    # Loopback relay (stream repair + wire-level measurement), see harness/tofa_relay.py.
    relay = tofa_relay.serve(0, str(out / "requests.jsonl"))
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    relay_url = f"http://127.0.0.1:{relay.server_address[1]}/v1"

    # Per-run overlay = the committed overlay with the run's reasoning effort and, unless
    # --no-relay, the loopback relay as base URL.
    overlay = PATCH.read_text().replace("reasoningEffort: medium", f"reasoningEffort: {args.effort}")
    if not args.no_relay:
        overlay = overlay.replace("baseURL: https://api.tokenfactory.nebius.com/v1", f"baseURL: {relay_url}")
    run_patch = scratch / "run.patch.yml"
    run_patch.write_text(overlay)
    (out / "dsh-overlay.yml").write_text(overlay.replace(relay_url, "http://127.0.0.1:<relay-port>/v1"))
    env = dict(os.environ)
    env["DSH_HOME"] = str(dsh_home)
    env["DSH_TELEMETRY_MODE"] = "DISABLED"
    env["DSH_PERMISSION_MODE"] = args.permission_mode
    env.setdefault("TOFA_API_KEY", PLACEHOLDER_KEY)
    cmd = ["dsh", "--profile", "headless", "--patch", str(run_patch), "--json", prompt]

    print(f"run {run_id}: task={task_dir.name} effort={args.effort} timeout={args.timeout}s", flush=True)
    started_at = dt.datetime.now(dt.timezone.utc)
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    timed_out = False

    def on_timeout(*_):
        nonlocal timed_out
        timed_out = True
        os.killpg(proc.pid, signal.SIGTERM)

    signal.signal(signal.SIGALRM, on_timeout)
    signal.alarm(args.timeout)
    events, session_id = [], None
    with open(out / "events.jsonl", "w") as ev_file:
        for line in proc.stdout:
            line = sanitize_text(line)
            ev_file.write(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event["_t"] = round(time.monotonic() - t0, 3)
            events.append(event)
            if event.get("type") == "session":
                session_id = event.get("sessionId")
            if args.live and (msg := pretty(event, t0)):
                print(msg, flush=True)
    stderr = proc.stderr.read()
    code = proc.wait()
    signal.alarm(0)
    relay.shutdown()
    wall = time.monotonic() - t0
    ended_at = dt.datetime.now(dt.timezone.utc)

    print(f"agent exited with {code} after {wall:.1f}s{' (TIMEOUT)' if timed_out else ''}; judging...", flush=True)
    judged = acceptance(task_dir, work)
    agent_suite = run_unittests(work)
    diff = git(work, "diff", "--", ".", ":(exclude)**/__pycache__/**")
    untracked = [f for f in git(work, "ls-files", "--others", "--exclude-standard").split() if "__pycache__" not in f]
    (out / "diff.patch").write_text(sanitize_text(diff))

    session_text = ""
    log = find_session_log(dsh_home, session_id)
    if log:
        session_text = sanitize_text(decode_session(log))
        (out / "session.jsonl").write_text(session_text)
    requests_path = out / "requests.jsonl"
    wire = [json.loads(l) for l in requests_path.read_text().splitlines()] if requests_path.exists() else []
    run_metrics = metrics.compute(session_text, wire)

    final = next((e.get("text", "") for e in reversed(events) if e.get("type") == "final"), None)
    turn_end = next((e.get("reason") for e in reversed(events) if e.get("type") == "status" and e.get("phase") == "turn_end"), None)
    result = {
        "schema": 1,
        "run_id": run_id,
        "label": args.label,
        "task": task_dir.name,
        "model": "openai/gpt-oss-120b",
        "provider": "Nebius Token Factory (public endpoint)",
        "base_url": "https://api.tokenfactory.nebius.com/v1",
        "reasoning_effort": args.effort,
        "dsh_version": dsh_version(),
        "permission_mode": args.permission_mode,
        "relay": not args.no_relay,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "wall_time_s": round(wall, 3),
        "timeout_s": args.timeout,
        "timed_out": timed_out,
        "dsh_exit_code": code,
        "dsh_stderr_tail": sanitize_text(stderr[-2000:]),
        "turn_end_reason": turn_end,
        "agent_final_answer": final,
        "success": bool(judged["ok"]) and not timed_out,
        "acceptance": judged,
        "agent_test_suite": agent_suite,
        "modified_test_files": modified_test_files(task_dir, work),
        "diff_stats": {
            "files_changed": len([l for l in diff.splitlines() if l.startswith("diff --git")]),
            "lines_added": len([l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]),
            "lines_removed": len([l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]),
            "untracked_files": untracked,
        },
        "metrics": run_metrics,
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if not args.keep_workdir:
        shutil.rmtree(scratch, ignore_errors=True)

    m = run_metrics or {}
    print(
        f"\n=== {run_id} ===\n"
        f"success (hidden+visible tests): {result['success']}  "
        f"[{judged['tests_run']} tests, {judged['failures']} failures, {judged['errors']} errors]\n"
        f"wall time: {wall:.1f}s   LLM requests: {m.get('llm_requests')}   tool calls: {m.get('tool_calls')}\n"
        f"tokens: uncached in={m.get('uncached_input_tokens')} cached in={m.get('cached_input_tokens')} "
        f"out={m.get('output_tokens')}   cache hit={m.get('cache_hit_rate')}\n"
        f"saved to {out.relative_to(ROOT)}"
    )
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
