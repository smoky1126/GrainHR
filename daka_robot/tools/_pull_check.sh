#!/bin/bash
export PATH="$HOME/android-sdk/platform-tools:$PATH"
echo "==== ls"
adb shell ls -l /sdcard/Download
echo "==== data"
adb shell content query --uri content://media/external/downloads --projection _display_name:_size
mkdir -p "$HOME/daka-robot/outbox"
name="$(adb shell content query --uri content://media/external/downloads --projection _display_name | sed -n 's/.*_display_name=//p' | head -1 | tr -d '\r')"
echo "NAME $name"
adb pull "/sdcard/Download/$name" "$HOME/daka-robot/outbox/sample.csv"
python3 - <<'PY'
import csv
from pathlib import Path
path = Path.home() / "daka-robot" / "outbox" / "sample.csv"
if not path.exists():
    raise SystemExit("sample missing")
raw = path.read_bytes()
print("bytes", len(raw))
text = raw.decode("utf-8-sig", errors="replace")
rows = list(csv.reader(text.splitlines()))
print("rows", len(rows))
if not rows:
    raise SystemExit("empty")
header = rows[0]
print("cols", len(header))
print("header", " | ".join(header[:16]))
print("has_name", "姓名" in header)
print("has_date", "日期" in header)
print("in_cols", sum(1 for name in header if name == "上班"))
print("out_cols", sum(1 for name in header if name == "下班"))
if "日期" in header:
    at = header.index("日期")
    dates = sorted({row[at].strip() for row in rows[1:] if len(row) > at and row[at].strip()})
    print("date_count", len(dates))
    if dates:
        print("date_first", dates[0])
        print("date_last", dates[-1])
PY
