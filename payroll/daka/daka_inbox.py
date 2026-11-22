"""Pull the DAKA export from the Linux server and file it by month.

The phone can also drop a CSV in daka_inbox. A month that already has payslips is left alone.
"""

import csv
import io
import json
import re
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from payroll.core.config import DAKA_REMOTE, DAKA_SERVER, home, parse_month

OFFLINE = "這部電腦連不上 DAKA 伺服器（需要 Tailscale），打卡資料由其他電腦更新。"
_PAID = ("payslips.docx", "payslips_md.docx", "payslips_admin.xlsx")
_EXPORT = re.compile(r"^daka_share_(\d{8}_\d{6})\.csv$")


def inbox_dir():
    folder = home() / "daka_inbox"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def status_path():
    return inbox_dir() / "_狀態.json"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _write_status(payload):
    status_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_status():
    """The server uploads _server.json with each export. The newer report wins."""
    status = _read_json(status_path())
    server = _read_json(inbox_dir() / "_server.json")
    known = (status.get("server") or {}).get("time") or ""
    if server.get("time") and server["time"] >= known:
        status["server"] = server
        status["ok"] = bool(server.get("ok", True))
        status["message"] = server.get("message", "")
        if server["time"] > (status.get("pulled_at") or ""):
            status["pulled_at"] = server["time"]
    return status


def month_is_paid(year, month):
    info = parse_month(f"{year}-{month:02d}")
    return any((info["output"] / name).exists() for name in _PAID)


def _decode(path):
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _rows(path):
    text = _decode(path)
    lines = text.splitlines()
    raw_header = lines[0] if lines else ""
    table = list(csv.reader(io.StringIO(text)))
    if not table:
        return raw_header, [], []
    return raw_header, table[0], table[1:]


def _date(value):
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    if " " in text:
        text = text.split(" ", 1)[0]
    parts = text.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    if len(parts[0]) == 4:
        year, month, day = (int(part) for part in parts)
    else:
        day, month, year = (int(part) for part in parts)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month


def _body(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        padded = list(row) + [""] * max(0, len(header) - len(row))
        writer.writerow(padded[:len(header)])
    return buffer.getvalue()


def _align(row, source, dest):
    if source == dest:
        return row
    taken = {}
    aligned = []
    for name in dest:
        start = taken.get(name, 0)
        found = None
        for index in range(start, len(source)):
            if source[index] == name:
                found = index
                break
        taken[name] = (found + 1) if found is not None else start
        aligned.append(row[found] if found is not None and found < len(row) else "")
    return aligned


def _merge(path, raw_header, header, incoming):
    source = header
    if path.exists():
        existing_header_line, existing_header, existing_rows = _rows(path)
        if existing_header:
            raw_header = existing_header_line
            header = existing_header
    else:
        existing_rows = []
    name_at = header.index("姓名")
    date_at = header.index("日期")
    source_name = source.index("姓名")
    source_date = source.index("日期")
    kept = {}
    order = []
    for row in existing_rows:
        if len(row) <= max(name_at, date_at) or not str(row[name_at]).strip():
            continue
        key = (str(row[name_at]).strip(), _stamp(row[date_at]))
        if key[1] is None:
            continue
        if key not in kept:
            order.append(key)
        kept[key] = row
    for row in incoming:
        if len(row) <= max(source_name, source_date):
            continue
        aligned = _align(row, source, header)
        key = (str(aligned[name_at]).strip(), _stamp(aligned[date_at]))
        if not key[0] or key[1] is None:
            continue
        if key not in kept:
            order.append(key)
        kept[key] = aligned
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _body(header, [kept[key] for key in order])
    path.write_bytes((raw_header + "\n" + body).encode("utf-8-sig"))
    return header


def _stamp(value):
    found = _date(value)
    if found is None:
        return None
    text = str(value).strip().replace(".", "-").replace("/", "-")
    if " " in text:
        text = text.split(" ", 1)[0]
    parts = text.split("-")
    if len(parts[0]) == 4:
        day = int(parts[2])
    else:
        day = int(parts[0])
    return f"{found[0]:04d}-{found[1]:02d}-{day:02d}"


def _discard(path):
    """The month file already has the rows. The downloaded copy is not kept."""
    try:
        path.unlink()
    except OSError:
        pass


def _clear_old(folder):
    done = folder / "_已處理"
    if not done.exists():
        return
    for path in done.glob("*.csv"):
        _discard(path)


def _drop_superseded(folder):
    """Each robot export holds the month so far, so only the latest run is needed.

    One run can save two files on days 1-5 (this month and last month), hence the window.
    Phone drops use other names and are always kept.
    """
    stamps = {}
    for path in folder.glob("daka_share_*.csv"):
        found = _EXPORT.match(path.name)
        if found:
            stamps[path] = datetime.strptime(found.group(1), "%Y%m%d_%H%M%S")
    if not stamps:
        return
    newest = max(stamps.values())
    for path, when in stamps.items():
        if newest - when > timedelta(minutes=15):
            _discard(path)


def file_inbox(folder=None):
    """Split every new CSV by the month in 日期 and merge it into that month's daka.csv."""
    folder = Path(folder) if folder else inbox_dir()
    folder.mkdir(parents=True, exist_ok=True)
    _clear_old(folder)
    _drop_superseded(folder)
    updated, skipped = [], []
    for path in sorted(folder.glob("*.csv")):
        try:
            _raw, header, rows = _rows(path)
        except OSError:
            skipped.append(path.name)
            continue
        if "姓名" not in header or "日期" not in header:
            skipped.append(path.name)
            _discard(path)
            continue
        name_at = header.index("姓名")
        date_at = header.index("日期")
        by_month = {}
        for row in rows:
            if len(row) <= max(name_at, date_at) or not str(row[name_at]).strip():
                continue
            found = _date(row[date_at])
            if found is None:
                continue
            year, month = found
            key = f"{year}-{month:02d}"
            if month_is_paid(year, month):
                if key not in skipped:
                    skipped.append(key)
                continue
            by_month.setdefault((year, month), []).append(row)
        for (year, month), month_rows in by_month.items():
            info = parse_month(f"{year}-{month:02d}")
            _merge(info["daka"], _raw, header, month_rows)
            label = f"{year}-{month:02d}"
            if label not in updated:
                updated.append(label)
        _discard(path)
    payload = read_status()
    payload.update({"filed_at": _now(), "updated": updated, "skipped": skipped})
    _write_status(payload)
    return payload


def _default_run(args, timeout=40):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
    )


def request_export():
    """Ask for a fresh export through the shared drive. andrew checks for these every minute.

    Returns the request time; an export at or after it answers the request.
    """
    stamp = datetime.now()
    host = "".join(ch for ch in socket.gethostname() if ch.isalnum()) or "pc"
    name = f"_request_{host}_{stamp:%Y%m%d_%H%M%S}.txt"
    (inbox_dir() / name).write_text(stamp.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    return stamp.strftime("%Y-%m-%d %H:%M")


def export_now(run=None):
    """Ask andrew for a fresh export (about a minute), then pull it.

    A PC off Tailscale gets OFFLINE after the connect timeout and keeps the shared-drive copy.
    """
    start = run or (lambda args: _default_run(args, timeout=300))
    try:
        done = start([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", DAKA_SERVER,
            "systemctl --user start daka-robot.service",
        ])
    except (OSError, subprocess.SubprocessError):
        request_export()
        return _offline("已請伺服器匯出打卡。約一分鐘後這一頁會自己更新。")
    if getattr(done, "returncode", 1) != 0:
        request_export()
        return _offline("已請伺服器匯出打卡。約一分鐘後這一頁會自己更新。")
    return pull_from_server(run)


def pull_from_server(run=None):
    """Copy new exports from andrew. A connection problem returns a message and does not raise.

    Only PCs on Tailscale can reach andrew. The others read what those PCs filed on the shared drive.
    """
    run = run or _default_run
    folder = inbox_dir()
    remote = (
        f"cat {DAKA_REMOTE}/status.json 2>/dev/null; echo '---FILES---'; "
        f"ls -1 {DAKA_REMOTE}/*.csv 2>/dev/null"
    )
    try:
        done = run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", DAKA_SERVER, remote,
        ])
    except (OSError, subprocess.SubprocessError):
        return _offline(OFFLINE)
    if getattr(done, "returncode", 1) != 0:
        return _offline(OFFLINE)
    text = getattr(done, "stdout", "") or ""
    server_text, _, listing = text.partition("---FILES---")
    server = {}
    try:
        server = json.loads(server_text.strip() or "{}")
    except json.JSONDecodeError:
        server = {}
    seen_path = folder / "_已取.txt"
    seen = set()
    if seen_path.exists():
        seen = {line.strip() for line in seen_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    fresh = []
    for line in listing.splitlines():
        name = line.strip().split("/")[-1]
        if name.endswith(".csv") and name not in seen:
            fresh.append(name)
    for name in fresh:
        try:
            copied = run([
                "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                f"{DAKA_SERVER}:{DAKA_REMOTE}/{name}", str(folder / name),
            ])
        except (OSError, subprocess.SubprocessError):
            return _offline(OFFLINE)
        if getattr(copied, "returncode", 1) != 0:
            return _offline(OFFLINE)
        seen.add(name)
    if fresh:
        seen_path.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")
    filed = file_inbox(folder)
    ok = bool(server.get("ok", True))
    message = server.get("message", "")
    payload = {
        "pulled_at": _now(),
        "ok": ok,
        "message": message,
        "server": server,
        "updated": filed.get("updated", []),
        "skipped": filed.get("skipped", []),
    }
    _write_status(payload)
    return "" if ok else message


def _offline(message):
    """The status file is shared, so one PC that cannot connect must not mark it failed."""
    try:
        file_inbox()
    except OSError:
        pass
    return message
