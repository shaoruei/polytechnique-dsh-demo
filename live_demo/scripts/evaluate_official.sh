#!/usr/bin/env bash
# OFFICIAL SWE-bench evaluation of one patch for django__django-16136.
# Uses the official harness (swebench==4.1.0) and the official prebuilt image
# swebench/sweb.eval.x86_64.django_1776_django-16136 from Docker Hub.
# Dataset row: live_demo/eval/django__django-16136.json (see docs/LIVE_DEMO.md §1.3 for provenance).
#
# Usage: evaluate_official.sh PATCH_FILE OUT_DIR [MODEL_NAME]
#        evaluate_official.sh gold OUT_DIR            # gold-patch validation
# Needs: docker (user in the docker group), python3 -m venv, ~5 GB disk, network for the first pull.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$HERE/../eval/django__django-16136.json"
PATCH="$1"; [ "$PATCH" = gold ] || PATCH="$(cd "$(dirname "$PATCH")" && pwd)/$(basename "$PATCH")"; OUT="$(mkdir -p "$2" && cd "$2" && pwd)"; NAME="${3:-dsh-live-demo}"
VENV="${SWEBENCH_VENV:-$HOME/.cache/swebench-4.1.0-venv}"
[ -x "$VENV/bin/python" ] || { python3 -m venv "$VENV" && "$VENV/bin/pip" -q install "swebench==4.1.0"; }
IMG=swebench/sweb.eval.x86_64.django_1776_django-16136:latest
if ! docker image inspect "$IMG" >/dev/null 2>&1; then          # pre-pull, with backoff (Docker Hub rate limits)
  for wait in 0 30 120 300; do sleep "$wait"; docker pull -q "$IMG" && break; done
fi
docker image inspect "$IMG" >/dev/null || { echo "ERROR: could not pull $IMG (Docker Hub rate limit? run 'docker login')" >&2; exit 2; }
RUN_ID="eval-$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"; cd "$WORK"
if [ "$PATCH" = gold ]; then PRED=gold; NAME=gold; else
  python3 - "$PATCH" "$NAME" > preds.json <<'PY'
import json, sys
print(json.dumps([{"instance_id": "django__django-16136", "model_name_or_path": sys.argv[2],
                   "model_patch": open(sys.argv[1]).read()}]))
PY
  PRED=preds.json; cp preds.json "$OUT/predictions.json"
fi
"$VENV/bin/python" -m swebench.harness.run_evaluation -d "$DATA" -s test -i django__django-16136 \
  -p "$PRED" --max_workers 1 -id "$RUN_ID" --namespace swebench --cache_level instance 2>&1 | tee "$OUT/harness.log" | tail -12
cp logs/run_evaluation/"$RUN_ID"/"$NAME"/django__django-16136/* "$OUT/"
[ -f "$OUT/report.json" ] || { echo "ERROR: harness produced no report.json; see $OUT/run_instance.log" >&2; exit 3; }
cp ./*."$RUN_ID".json "$OUT/summary.json"
python3 - "$OUT/report.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["django__django-16136"]; t = r["tests_status"]
print(f"OFFICIAL RESULT: resolved={r['resolved']}  "
      f"FAIL_TO_PASS {len(t['FAIL_TO_PASS']['success'])}/{len(t['FAIL_TO_PASS']['success'])+len(t['FAIL_TO_PASS']['failure'])}  "
      f"PASS_TO_PASS {len(t['PASS_TO_PASS']['success'])}/{len(t['PASS_TO_PASS']['success'])+len(t['PASS_TO_PASS']['failure'])}")
PY
rm -rf "$WORK"
