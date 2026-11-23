#!/bin/bash
# A PC without Tailscale asks for a fresh export by dropping _request_*.txt in the shared daka_inbox.
# This runs every minute, removes the requests, and starts one export. run_daily.sh uploads the result.
set -u
RCLONE="$HOME/bin/rclone"
INBOX_FILE="${DAKA_INBOX_FILE:-$HOME/daka-robot/inbox.path}"
if [ -n "${DAKA_INBOX:-}" ]; then
  INBOX="$DAKA_INBOX"
elif [ -f "$INBOX_FILE" ]; then
  INBOX="$(tr -d '\r\n' < "$INBOX_FILE")"
else
  echo "Write the rclone inbox path to $INBOX_FILE" >&2
  exit 1
fi
exec 8>/tmp/daka-watch.lock
flock -n 8 || exit 0
found=$("$RCLONE" lsf "$INBOX" --files-only --include "_request_*.txt" --max-depth 1 2>/dev/null)
asked=0
while read -r name; do
  case "$name" in
    _request_*.txt)
      "$RCLONE" deletefile "$INBOX/$name" 2>/dev/null || true
      asked=1
      ;;
  esac
done <<< "$found"
[ "$asked" -eq 1 ] || exit 0
# An export from the last 3 minutes already answers the request.
STATUS="$HOME/daka-robot/outbox/status.json"
if [ -f "$STATUS" ] && [ $(( $(date +%s) - $(stat -c %Y "$STATUS") )) -lt 180 ]; then
  exit 0
fi
systemctl --user start daka-robot.service
