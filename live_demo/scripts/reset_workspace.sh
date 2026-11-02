#!/usr/bin/env bash
# Recreate the agent workspace from scratch: django/django at the task's base commit,
# with NO history after that commit, NO remote, and NO evaluation material inside it.
# Usage: live_demo/scripts/reset_workspace.sh [LIVE_ROOT]     (default: ~/dsh-live)
set -euo pipefail
BASE_COMMIT=19e6efa50b603af325e7f62058364f278596758f
LIVE_ROOT="${1:-${LIVE_ROOT:-$HOME/dsh-live}}"
WS="$LIVE_ROOT/django"
VENV="$LIVE_ROOT/venv"
CACHE="$LIVE_ROOT/.cache/django-base.git"   # pristine bare copy, so later resets work offline

mkdir -p "$LIVE_ROOT/.cache"
if [ ! -d "$CACHE" ]; then
  git init -q --bare "$CACHE"
  git -C "$CACHE" fetch -q --depth 1 https://github.com/django/django.git "$BASE_COMMIT"
fi
git -C "$CACHE" cat-file -e "$BASE_COMMIT^{commit}"

BASE_TREE=$(git -C "$CACHE" rev-parse "$BASE_COMMIT^{tree}")
rm -rf "$WS"; mkdir -p "$WS"
# DSH's workspace-changes feature keeps file snapshots (including any previous fix) here.
find /tmp -maxdepth 1 -name 'dsh-workspace-changes-*' -user "$(id -u)" -exec rm -rf {} + 2>/dev/null || true
git -C "$CACHE" archive "$BASE_COMMIT" | tar -x -C "$WS"
git -C "$WS" init -q -b live-demo
git -C "$WS" add -A
GIT_AUTHOR_DATE="2022-09-29T11:00:00Z" GIT_COMMITTER_DATE="2022-09-29T11:00:00Z" \
  git -C "$WS" -c user.name="workspace" -c user.email="workspace@localhost" \
  commit -q -m "Import source snapshot"
test "$(git -C "$WS" rev-parse 'HEAD^{tree}')" = "$BASE_TREE"   # byte-identical tree to upstream base

# Python 3.9 virtualenv (same interpreter + pins as the reference evaluation image)
if [ ! -x "$VENV/bin/python" ]; then
  uv venv -q --python 3.9 "$VENV"
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIRTUAL_ENV="$VENV" uv pip install -q -r "$HERE/../env/requirements-reference-image.txt"
VIRTUAL_ENV="$VENV" uv pip install -q --no-deps -e "$WS"

# Sanity: exactly one commit, clean tree, nothing evaluation-related present.
test "$(git -C "$WS" rev-list --count HEAD)" = 1
test -z "$(git -C "$WS" status --porcelain)"
# (patterns are base64-encoded so this kit does not itself name the benchmark task)
! grep -q -E "$(echo dGVzdF9odHRwX21ldGhvZF9ub3RfYWxsb3dlZF9yZXNwb25kc19jb3JyZWN0bHk= | base64 -d)" "$WS/tests/async/tests.py"
# Nothing in the workspace may name the benchmark or the instance (rehearsal 1 showed the
# model will use such a hint to go looking for the upstream fix).
! git -C "$WS" log --format=%B | grep -i -q -E "$(echo c3dlLT9iZW5jaHwxNjEzNnwzNDA2Mg== | base64 -d)"
! grep -r -l -i -E "$(echo c3dlLT9iZW5jaHxkamFuZ29fX2RqYW5nbw== | base64 -d)" "$WS" --include=*.py --include=*.txt --include=*.cfg --include=*.toml -q
echo "workspace ready: $WS @ $BASE_COMMIT (python: $("$VENV/bin/python" --version))"
