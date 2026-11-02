#!/usr/bin/env bash
# OFFICIAL SWE-bench evaluation (swebench==4.1.0 harness, official prebuilt swebench/* image) of one
# patch for one instance of this experiment. Same procedure as live_demo/scripts/evaluate_official.sh.
# Usage: evaluate_official.sh INSTANCE_ID PATCH_FILE|gold OUT_DIR [MODEL_NAME]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IID="$1"; PATCH="$2"; [ "$PATCH" = gold ] || PATCH="$(cd "$(dirname "$PATCH")" && pwd)/$(basename "$PATCH")"
OUT="$(mkdir -p "$3" && cd "$3" && pwd)"; NAME="${4:-dsh-v4flash-public}"
DATA="$HERE/../instances/$IID/instance.json"
VENV="${SWEBENCH_VENV:-$HOME/.cache/swebench-4.1.0-venv}"
[ -x "$VENV/bin/python" ] || { python3 -m venv "$VENV" && "$VENV/bin/pip" -q install "swebench==4.1.0"; }
IMG="swebench/sweb.eval.x86_64.$(echo "$IID" | sed 's/__/_1776_/'):latest"
if ! docker image inspect "$IMG" >/dev/null 2>&1; then
  for wait in 0 30 120 300; do sleep "$wait"; docker pull -q "$IMG" && break; done
fi
docker image inspect "$IMG" >/dev/null || { echo "ERROR: could not pull $IMG" >&2; exit 2; }
RUN_ID="eval-$(date -u +%Y%m%dT%H%M%SZ)-$$"
WORK="$(mktemp -d)"; cd "$WORK"
if [ "$PATCH" = gold ]; then PRED=gold; NAME=gold; else
  python3 - "$PATCH" "$NAME" "$IID" > preds.json <<'PY'
import json, sys
print(json.dumps([{"instance_id": sys.argv[3], "model_name_or_path": sys.argv[2], "model_patch": open(sys.argv[1]).read()}]))
PY
  PRED=preds.json; cp preds.json "$OUT/predictions.json"
fi
"$VENV/bin/python" -m swebench.harness.run_evaluation -d "$DATA" -s test -i "$IID" -p "$PRED" --max_workers 1 \
  -id "$RUN_ID" --namespace swebench --cache_level instance > "$OUT/harness.log" 2>&1 || true
cp logs/run_evaluation/"$RUN_ID"/"$NAME"/"$IID"/* "$OUT/" 2>/dev/null || true
cp ./*."$RUN_ID".json "$OUT/summary.json" 2>/dev/null || true
docker image inspect --format '{{index .RepoDigests 0}}' "$IMG" > "$OUT/image_digest.txt"
cd /; rm -rf "$WORK"
[ -f "$OUT/report.json" ] || { echo "ERROR: no report.json for $IID; see $OUT/" >&2; exit 3; }
python3 - "$OUT/report.json" "$IID" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))[sys.argv[2]]; t = r["tests_status"]
n = lambda k: f"{len(t[k]['success'])}/{len(t[k]['success']) + len(t[k]['failure'])}"
print(f"OFFICIAL {sys.argv[2]}: resolved={r['resolved']} applied={r['patch_successfully_applied']} FAIL_TO_PASS {n('FAIL_TO_PASS')} PASS_TO_PASS {n('PASS_TO_PASS')}")
PY
