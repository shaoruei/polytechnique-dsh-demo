#!/usr/bin/env bash
# Build a fresh agent workspace for one task of the kit (runs as the unprivileged agent user).
# Same guarantees as live_demo/scripts/reset_workspace.sh: one commit "Import source snapshot"
# whose tree is byte-identical to upstream BASE_COMMIT, no later history, no remote, nothing that
# names the benchmark; venv with the official image's interpreter version and pins.
# Usage: prepare_workspace.sh KIT_TASK_DIR [ROOT]   -> ROOT/<alias>/{django,venv}  (ROOT default ~/swe)
set -euo pipefail
TASK="$(cd "$1" && pwd)"; ROOT="${2:-$HOME/swe}"
. "$TASK/meta.env"                                   # ALIAS, BASE_COMMIT, PYTHON
WS="$ROOT/$ALIAS/django"; VENV="$ROOT/$ALIAS/venv"; CACHE="$ROOT/.cache/$ALIAS.git"
mkdir -p "$ROOT/.cache"
if [ ! -d "$CACHE" ]; then
  git init -q --bare "$CACHE"
  git -C "$CACHE" fetch -q --depth 1 https://github.com/django/django.git "$BASE_COMMIT"
fi
BASE_TREE=$(git -C "$CACHE" rev-parse "$BASE_COMMIT^{tree}")
rm -rf "$WS"; mkdir -p "$WS"
find /tmp -maxdepth 1 -name 'dsh-workspace-changes-*' -user "$(id -u)" -exec rm -rf {} + 2>/dev/null || true
git -C "$CACHE" archive "$BASE_COMMIT" | tar -x -C "$WS"
git -C "$WS" init -q -b main
git -C "$WS" add -A
GIT_AUTHOR_DATE="2023-01-01T00:00:00Z" GIT_COMMITTER_DATE="2023-01-01T00:00:00Z" \
  git -C "$WS" -c user.name=workspace -c user.email=workspace@localhost commit -q -m "Import source snapshot"
test "$(git -C "$WS" rev-parse 'HEAD^{tree}')" = "$BASE_TREE"
[ -x "$VENV/bin/python" ] || uv venv -q --python "$PYTHON" "$VENV"
VIRTUAL_ENV="$VENV" uv pip install -q -r "$TASK/requirements.txt"
VIRTUAL_ENV="$VENV" uv pip install -q --no-deps -e "$WS"
test "$(git -C "$WS" rev-list --count HEAD)" = 1
test -z "$(git -C "$WS" status --porcelain)"
! grep -r -l -i -E "$(echo c3dlLT9iZW5jaHxkamFuZ29fX2RqYW5nbw== | base64 -d)" "$WS" --include=*.py --include=*.txt --include=*.cfg --include=*.toml -q
echo "workspace ready: $WS (python $("$VENV/bin/python" -c 'import platform;print(platform.python_version())'))"
