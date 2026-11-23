#!/bin/bash
# Start the emulator, export DAKA, then shut the emulator down.
# Software rendering only (-gpu swiftshader_indirect). Nothing is left running.
#
# One-time login, from Windows, with scrcpy in the user profile (not the shared drive):
#   ssh -L 5037:localhost:5037 <robot-computer>
#   scrcpy
# Sign into Play, install DAKA, and log in once. The password is not stored.
# Then fill steps.json from the screen labels. Do not use coordinates.
set -u
ROOT="$HOME/daka-robot"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
export PATH="$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/platform-tools:$PATH"
mkdir -p "$ROOT/outbox"
exec 9>"$ROOT/outbox/run.lock"
if ! flock -n 9; then
  echo "上一次匯出尚未完成。"
  exit 0
fi
if [ ! -e /dev/kvm ]; then
  echo "需要宿主機把 /dev/kvm 傳進這個容器。" >&2
  exit 1
fi
emulator -avd daka -no-window -no-audio -no-boot-anim -no-snapshot-save -gpu swiftshader_indirect >"$ROOT/outbox/emulator.log" 2>&1 &
EMU=$!
cleanup() {
  adb emu kill >/dev/null 2>&1 || true
  wait "$EMU" 2>/dev/null || true
}
trap cleanup EXIT
PYTHON="$ROOT/.venv/bin/python"
"$PYTHON" "$ROOT/robot.py" || "$PYTHON" "$ROOT/robot.py"
RESULT=$?
# Upload this run's export. The rclone path stays in inbox.path, not in this file.
RCLONE="$HOME/bin/rclone"
INBOX_FILE="${DAKA_INBOX_FILE:-$HOME/daka-robot/inbox.path}"
if [ -n "${DAKA_INBOX:-}" ]; then
  INBOX="$DAKA_INBOX"
elif [ -f "$INBOX_FILE" ]; then
  INBOX="$(tr -d '\r\n' < "$INBOX_FILE")"
else
  echo "Write the rclone inbox path to $INBOX_FILE" >&2
  INBOX=""
fi
if [ -n "$INBOX" ] && [ -x "$RCLONE" ]; then
  "$RCLONE" copy "$ROOT/outbox" "$INBOX" --include "*.csv" --max-age 2h || echo "上傳到共用雲端失敗。" >&2
  if [ -f "$ROOT/outbox/status.json" ]; then
    "$RCLONE" copyto "$ROOT/outbox/status.json" "$INBOX/_server.json" || true
  fi
fi
exit $RESULT
