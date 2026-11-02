#!/usr/bin/env bash
# Save everything about the most recent DSH session into OUT_DIR:
#   session.jsonl (decoded log), trajectory.md, metrics.json (incl. integrity scan),
#   diff.patch (all workspace changes, including new files), test-run of the issue repro.
# Usage: collect_evidence.sh OUT_DIR [LIVE_ROOT] [DSH_HOME]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="$1"; LIVE_ROOT="${2:-${LIVE_ROOT:-$HOME/dsh-live}}"; DSH_HOME="${3:-${DSH_HOME:-$LIVE_ROOT/dsh-home}}"
WS="$LIVE_ROOT/django"
mkdir -p "$OUT"
S=$(ls -t "$DSH_HOME"/sessions/*/session-*/session.v4.jsonl.zstd | head -1)
DEC="$HERE/decode_session.mjs"; [ -f "$DEC" ] || DEC="$REPO/harness/decode_session.mjs"
node "$DEC" "$S" > "$OUT/session.jsonl"
python3 "$HERE/summarize_session.py" "$OUT/session.jsonl" "$OUT"
git -C "$WS" add -A -N .                                   # include new (untracked) files in the diff
git -C "$WS" diff --binary HEAD -- . ':(exclude)*.egg-info' > "$OUT/diff.patch"
git -C "$WS" reset -q
git -C "$WS" diff --stat HEAD > "$OUT/diff.stat" || true
( cd /tmp && "$LIVE_ROOT/venv/bin/python" "$HERE/repro_issue.py" ) > "$OUT/repro_after.txt" 2>&1 || true
echo "saved to $OUT:"; ls "$OUT"; cat "$OUT/diff.stat"; cat "$OUT/repro_after.txt"
