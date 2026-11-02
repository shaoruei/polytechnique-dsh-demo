#!/usr/bin/env bash
# UNOFFICIAL quick check (~10 s, no Docker): copy the agent's workspace to a temp dir,
# apply the benchmark's test patch there (never in the agent workspace), run the same
# test module the official harness runs, and grade the FAIL_TO_PASS / PASS_TO_PASS lists.
# This is a convenience for the live moment; the verdict of record is evaluate_official.sh.
# Usage: evaluate_local_unofficial.sh [LIVE_ROOT]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_ROOT="${1:-${LIVE_ROOT:-$HOME/dsh-live}}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cp -a "$LIVE_ROOT/django" "$T/django"
cd "$T/django"
git checkout -q HEAD -- tests/async/tests.py          # same reset the official eval script does
git apply "$HERE/../eval/test.patch"
cd tests
"$LIVE_ROOT/venv/bin/python" runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 async.tests > "$T/out.txt" 2>&1 || true
python3 - "$T/out.txt" "$HERE/../eval/django__django-16136.json" <<'PY'
import json, re, sys
out = open(sys.argv[1]).read(); row = json.load(open(sys.argv[2]))[0]
failed = set(re.findall(r"^(?:FAIL|ERROR): (\S+ \([^)]+\))", out, re.M))
ran = re.search(r"Ran (\d+) tests", out)
def ok(name):  # docstring-named tests are matched by their first line
    return not any(name in f or f.startswith(name.split(" (")[0]) for f in failed)
f2p = json.loads(row["FAIL_TO_PASS"]); p2p = json.loads(row["PASS_TO_PASS"])
f2p_ok = [t for t in f2p if ok(t)]; p2p_ok = [t for t in p2p if ok(t)]
print(out.strip().splitlines()[-1] if out.strip() else "no output", "| ran:", ran.group(1) if ran else "?")
print(f"UNOFFICIAL RESULT: FAIL_TO_PASS {len(f2p_ok)}/{len(f2p)}  PASS_TO_PASS {len(p2p_ok)}/{len(p2p)}  "
      f"=> {'RESOLVED (unofficial)' if len(f2p_ok)==len(f2p) and len(p2p_ok)==len(p2p) else 'NOT RESOLVED (unofficial)'}")
PY
