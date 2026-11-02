#!/usr/bin/env bash
# Copy ONLY agent-safe files (no gold patch, no benchmark tests, no rehearsal logs) into a kit
# directory the presenter user owns. Run from the private prep clone; the prep clone itself
# must not be readable by the user that runs `dsh web` (see docs/LIVE_DEMO.md, section 3).
# Usage: sudo live_demo/scripts/install_presenter_kit.sh PRESENTER_USER [KIT_DIR]
set -euo pipefail
U="$1"; H=$(getent passwd "$U" | cut -d: -f6); KIT="${2:-$H/dsh-kit}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$SRC/.." && pwd)"
install -d -o "$U" -g "$U" "$KIT" "$KIT/scripts" "$KIT/env" "$KIT/config"
install -o "$U" -g "$U" -m 755 "$SRC/scripts/reset_workspace.sh" "$SRC/scripts/collect_evidence.sh" \
  "$SRC/scripts/summarize_session.py" "$SRC/scripts/launch_web.sh" "$KIT/scripts/"
install -o "$U" -g "$U" -m 644 "$SRC/scripts/repro_issue.py" "$REPO/harness/decode_session.mjs" "$KIT/scripts/"
install -o "$U" -g "$U" -m 644 "$SRC/env/requirements-reference-image.txt" "$KIT/env/"
install -o "$U" -g "$U" -m 644 "$SRC/config/offline-web-tools.patch.yml" "$KIT/config/"
install -o "$U" -g "$U" -m 644 "$SRC/PROMPT.txt" "$KIT/"
# Guard: nothing evaluation-related may be in the kit.
! grep -r -l -F -e "test_http_method_not_allowed_responds_correctly" -e "response = HttpResponseNotAllowed(self._allowed_methods())" "$KIT"
echo "kit installed in $KIT"; ls -R "$KIT"
