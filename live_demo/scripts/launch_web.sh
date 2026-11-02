#!/usr/bin/env bash
# Launch the stock DSH Web UI for the live demo.
#   - native DeepSeek provider (needs DEEPSEEK_API_KEY in the environment or "Add API Key" in the UI)
#   - web search/fetch backends removed (config/offline-web-tools.patch.yml)
#   - `python` on PATH = the workspace virtualenv
# Usage: launch_web.sh [LIVE_ROOT] [extra dsh launcher flags, e.g. --patch other.yml]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_ROOT="${1:-${LIVE_ROOT:-$HOME/dsh-live}}"; shift || true
# DEEPSEEK_API_KEY lives in a private env file (chmod 600) so that wiping DSH_HOME during a
# reset never loses it:  echo 'DEEPSEEK_API_KEY=sk-...' > ~/.config/dsh-live.env; chmod 600 ~/.config/dsh-live.env
if [ -f "$HOME/.config/dsh-live.env" ]; then set -a; . "$HOME/.config/dsh-live.env"; set +a; fi
export DSH_HOME="${DSH_HOME:-$LIVE_ROOT/dsh-home}"
export PATH="$LIVE_ROOT/venv/bin:$PATH"
cd "$LIVE_ROOT/django"
exec dsh --profile web --patch "$HERE/../config/offline-web-tools.patch.yml" "$@" --no-open --port "${DSH_PORT:-3080}"
