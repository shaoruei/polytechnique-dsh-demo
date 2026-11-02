#!/usr/bin/env bash
# One controlled trial: stock DSH Web UI -> Token Factory PUBLIC deepseek-ai/DeepSeek-V4-Flash-0731
# (direct, no relay), agent as an unprivileged user, fresh workspace + fresh DSH home, official eval.
# Run as admin/root. Strictly one trial at a time.
# Usage: run_trial.sh INSTANCE_ID TRIAL_NO
# Env:   AGENT_USER (default presenter)  AGENT_ENV_FILE (optional file sourced in the agent shell,
#        e.g. proxy settings)  PORT (default 3090)  MAX_WAIT_S (default 1500)  SWEBENCH_VENV
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; EXP="$(cd "$HERE/.." && pwd)"; REPO="$(cd "$EXP/../.." && pwd)"
IID="$1"; TRIAL="$2"; U="${AGENT_USER:-presenter}"; UH=$(getent passwd "$U" | cut -d: -f6)
PORT="${PORT:-3090}"; MAX_WAIT_S="${MAX_WAIT_S:-1500}"; ENVF="${AGENT_ENV_FILE:-/dev/null}"
PRICE_IN=0.14; PRICE_CACHED=0.01; PRICE_OUT=0.28          # USD / 1M tokens, public list price (provenance/tofa_model_entry.json)
. "$EXP/instances/$IID/kit/meta.env"                       # ALIAS BASE_COMMIT PYTHON
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_${IID#django__django-}_t${TRIAL}"
OUT="$EXP/runs/$RUN_ID"; mkdir -p "$OUT/ui"
KIT="$UH/swe-kit"; WS="$UH/swe/$ALIAS/django"; DH="$UH/swe/dsh-home"
as_agent() { su - "$U" -c "set -a; . '$ENVF'; set +a; $1"; }
stop_ui() {  # stop every Web UI of the agent user and make sure the port is free again
  pkill -u "$U" -f 'dsh --profile web' 2>/dev/null || true
  for _ in $(seq 30); do curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/" || return 0; sleep 1; done
  echo "port $PORT still busy" >&2; return 1
}
echo "== $RUN_ID ($IID as $ALIAS, python $PYTHON)"

# 1. agent-safe kit (scripts + this task only; nothing evaluation-related)
install -d -o "$U" -g "$U" "$KIT" "$KIT/config" "$KIT/tasks/$ALIAS"
install -o "$U" -g "$U" -m 755 "$HERE/prepare_workspace.sh" "$KIT/"
install -o "$U" -g "$U" -m 644 "$EXP/config/tofa-public-deepseek-v4-flash-0731.patch.yml" "$REPO/live_demo/config/offline-web-tools.patch.yml" "$KIT/config/"
install -o "$U" -g "$U" -m 644 "$EXP/instances/$IID/kit/"* "$KIT/tasks/$ALIAS/"

# 2. fresh workspace and DSH home
stop_ui
as_agent "~/swe-kit/prepare_workspace.sh ~/swe-kit/tasks/$ALIAS ~/swe && rm -rf ~/swe/dsh-home"

# 3. stock Web UI (offline web tools + public provider overlay), agent's venv first on PATH
LOG="$OUT/ui/server.log"
as_agent "cd $WS && export DSH_HOME=$DH PATH=$UH/swe/$ALIAS/venv/bin:\$PATH && unset DEEPSEEK_API_KEY && exec dsh --profile web --patch ~/swe-kit/config/offline-web-tools.patch.yml --patch ~/swe-kit/config/tofa-public-deepseek-v4-flash-0731.patch.yml --no-open --port $PORT" > "$LOG" 2>&1 &
for _ in $(seq 60); do grep -q 'token=' "$LOG" && break; sleep 1; done
URL=$(grep -o "http://127.0.0.1:$PORT/?token=[^ ]*" "$LOG" | head -1); [ -n "$URL" ] || { echo "server did not start" >&2; exit 4; }
STARTED=$(date -u +%FT%TZ)

# 4. paste the prompt and wait for the turn to end
node "$HERE/drive_webui.cjs" "$URL" "$WS" "$EXP/instances/$IID/kit/prompt.txt" "$OUT/ui/shots" "$MAX_WAIT_S" > "$OUT/ui/driver.log" 2>&1 || true
stop_ui
mkdir -p "$OUT/ui/keep"; for f in 01-prompt-pasted.png 99-final.png page-text.txt approvals.log; do
  [ -f "$OUT/ui/shots/$f" ] && cp "$OUT/ui/shots/$f" "$OUT/ui/keep/"; done; rm -rf "$OUT/ui/shots"; mv "$OUT/ui/keep" "$OUT/ui/shots"
sed -i 's/token=[A-Za-z0-9_-]*/token=<redacted>/' "$LOG"

# 5. evidence: session log -> trace, integrity scan, patch
S=$(ls -t "$DH"/sessions/*/session-*/session.v4.jsonl.zstd | head -1)
node "$REPO/harness/decode_session.mjs" "$S" > "$OUT/session.jsonl"
python3 "$HERE/extract_trace.py" "$OUT/session.jsonl" "$OUT" --price-in $PRICE_IN --price-cached $PRICE_CACHED --price-out $PRICE_OUT | tee "$OUT/trace_summary.txt"
mkdir -p "$OUT/integrity"; python3 "$REPO/live_demo/scripts/summarize_session.py" "$OUT/session.jsonl" "$OUT/integrity" > "$OUT/integrity/summary.txt" 2>&1 || true
git config --global --add safe.directory "$WS" 2>/dev/null || true
git -C "$WS" add -A -N . && git -C "$WS" diff --binary HEAD -- . ':(exclude)*.egg-info' > "$OUT/diff.patch"; git -C "$WS" reset -q
git -C "$WS" diff --stat HEAD -- . ':(exclude)*.egg-info' > "$OUT/diff.stat" || true

# 6. remove everything that now contains a fix from the agent account
rm -rf "$DH"; find /tmp -maxdepth 1 -name 'dsh-workspace-changes-*' -user "$U" -exec rm -rf {} + 2>/dev/null || true
as_agent "~/swe-kit/prepare_workspace.sh ~/swe-kit/tasks/$ALIAS ~/swe >/dev/null"

# 7. official evaluation
if [ -s "$OUT/diff.patch" ]; then
  "$HERE/evaluate_official.sh" "$IID" "$OUT/diff.patch" "$OUT/official-eval" "dsh-v4flash-public-$RUN_ID" | tee "$OUT/official_summary.txt" || true
else echo "EMPTY PATCH: not evaluated (counts as unresolved)" | tee "$OUT/official_summary.txt"; fi

python3 - "$OUT" "$IID" "$ALIAS" "$TRIAL" "$STARTED" "$RUN_ID" <<'PY'
import json, os, sys, re
out, iid, alias, trial, started, rid = sys.argv[1:]
t = json.load(open(f"{out}/trace.json"))["summary"]
rep = f"{out}/official-eval/report.json"
r = json.load(open(rep))[iid] if os.path.exists(rep) else None
integ = json.load(open(f"{out}/integrity/metrics.json")) if os.path.exists(f"{out}/integrity/metrics.json") else {}
drv = open(f"{out}/ui/driver.log").read()
m = re.search(r"elapsed_s (\d+)", drv)
json.dump({"run_id": rid, "instance_id": iid, "alias": alias, "trial": int(trial), "started_at": started,
           "endpoint": "public", "base_url": "https://api.tokenfactory.nebius.com/v1", "relay": False,
           "model": t["model"], "reasoning_effort": t["reasoning_effort"], "harness": "dsh web (stock) 0.2.1-rc.5",
           "ui_elapsed_s": int(m.group(1)) if m else None, "turn_end_reason": t["turn_end_reason"],
           "patch_bytes": os.path.getsize(f"{out}/diff.patch"),
           "official": None if r is None else {"resolved": r["resolved"], "applied": r["patch_successfully_applied"],
               "FAIL_TO_PASS": {k: len(v) for k, v in r["tests_status"]["FAIL_TO_PASS"].items()},
               "PASS_TO_PASS": {k: len(v) for k, v in r["tests_status"]["PASS_TO_PASS"].items()}},
           "success": bool(r and r["resolved"]), "integrity_verdict": integ.get("integrity_verdict"),
           "integrity_flags": [f["kind"] for f in integ.get("integrity_flags", [])]},
          open(f"{out}/run.json", "w"), indent=1)
print("RESULT", rid, "success=", bool(r and r["resolved"]), "wall=", t["wall_time_s"], "cost=", t["cost_usd"], "integrity=", integ.get("integrity_verdict"))
PY
