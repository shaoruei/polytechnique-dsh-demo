#!/usr/bin/env bash
# Run as admin BEFORE the live run (and after every dry run): move everything that contains a
# fix (evidence dirs, backup tarballs, old DSH sessions) out of the presenter account into the
# private prep clone, then verify that nothing readable by the presenter still contains it.
# Usage: sudo live_demo/scripts/archive_presenter_evidence.sh PRESENTER_USER
set -euo pipefail
U="$1"; H=$(getent passwd "$U" | cut -d: -f6)
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/rehearsal/vm-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST"
shopt -s nullglob
for p in "$H"/evidence "$H"/backup "$H"/*.tgz "$H"/dsh-live/dsh-home /tmp/dsh-workspace-changes-*; do
  [ -e "$p" ] || continue; echo "archiving $p"; mv "$p" "$DEST/"
done
chown -R root:root "$DEST"; chmod -R go-rwx "$DEST"
# The fixed code contains this line (absent from the base commit); it must not exist anywhere the presenter can read
# outside the (freshly reset) workspace. Pattern base64-encoded to keep it out of the kit.
PAT=$(echo 'cmVzcG9uc2UgPSBIdHRwUmVzcG9uc2VOb3RBbGxvd2VkKHNlbGYuX2FsbG93ZWRfbWV0aG9kcygpKQ==' | base64 -d)
HITS=$(sudo -u "$U" grep -r -l -F "$PAT" "$H" /tmp /var/tmp 2>/dev/null | grep -v "^$H/dsh-live/django/" || true)
if [ -n "$HITS" ]; then
  echo "$HITS"; echo "WARNING: files above are readable by $U and contain the fix" >&2; exit 1
fi
if sudo -u "$U" grep -q -F "$PAT" "$H/dsh-live/django/django/views/generic/base.py" 2>/dev/null; then
  echo "WARNING: workspace still modified; run reset_workspace.sh as $U" >&2; exit 1
fi
echo "OK: archived to $DEST; presenter account is clean"
