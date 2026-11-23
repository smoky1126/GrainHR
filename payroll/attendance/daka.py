"""Clock punches from the DAKA export. These are what actually happened."""

from datetime import datetime

import pandas as pd

from payroll.core.settings import shop_keywords


def _minutes(value):
    text = "" if value is None else str(value).strip()
    if text in {"", "nan", "None", "NaT"} or ":" not in text:
        return None
    text = text.replace("：", ":")
    try:
        clock = datetime.strptime(text[:5] if len(text) >= 5 else text, "%H:%M")
    except ValueError:
        return None
    return clock.hour * 60 + clock.minute


def _clock(value):
    minutes = _minutes(value)
    if minutes is None:
        return ""
    return f"{minutes // 60}:{minutes % 60:02d}"


def _place_code(place):
    text = "" if place is None else str(place)
    if text in {"", "nan", "None"}:
        return ""
    lowered = text.lower()
    pairs = shop_keywords()
    for word, code in pairs:
        if word.lower() in lowered:
            return code
    tokens = set(text.replace("-", " ").replace("/", " ").split())
    codes = sorted({code for _word, code in pairs}, key=len, reverse=True)
    for code in codes:
        if code in tokens:
            return code
    return ""


def _shown(value):
    text = "" if value is None else str(value).strip()
    if text.lower() in {"", "nan", "none", "nat"}:
        return ""
    return text


def _column_kind(name):
    """上班, 下班, or a place column. Scheduled 應上班 columns are ignored."""
    base = str(name).split(".")[0]
    if base.startswith("應") or "地" in base:
        return ""
    if base == "上班位置":
        return "in-place"
    if base == "下班位置":
        return "out-place"
    if base == "上班":
        return "in"
    if base == "下班":
        return "out"
    return ""


def _read(path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "ANSI"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except Exception as error:
            last_error = error
    raise SystemExit(f"讀不到 DAKA 檔案 {path}（{last_error}）")


def _pair_punches(columns, values):
    """First 上班 is arrival. Last 下班 is leaving. The lunch pair in between is ignored."""
    arrivals = []
    leaves = []
    pending_in = None
    pending_out = None
    for index, name in enumerate(columns):
        kind = _column_kind(name)
        if kind == "in":
            if pending_in is not None and _clock(pending_in[0]):
                arrivals.append(pending_in)
            pending_in = (values[index], "")
        elif kind == "in-place" and pending_in is not None:
            pending_in = (pending_in[0], _shown(values[index]))
        elif kind == "out":
            if pending_out is not None and _clock(pending_out[0]):
                leaves.append(pending_out)
            pending_out = (values[index], "")
        elif kind == "out-place" and pending_out is not None:
            pending_out = (pending_out[0], _shown(values[index]))
    if pending_in is not None and _clock(pending_in[0]):
        arrivals.append(pending_in)
    if pending_out is not None and _clock(pending_out[0]):
        leaves.append(pending_out)
    clock_in, in_place = ("", "")
    clock_out, out_place = ("", "")
    if arrivals:
        clock_in, in_place = _clock(arrivals[0][0]), arrivals[0][1]
    if leaves:
        clock_out, out_place = _clock(leaves[-1][0]), leaves[-1][1]
    return clock_in, in_place, clock_out, out_place


def _clocks(columns, values):
    """Filled 上班 and 下班 times, in the order DAKA stored them."""
    found = []
    for index, column in enumerate(columns):
        kind = _column_kind(column)
        if kind not in {"in", "out"}:
            continue
        clock = _clock(values[index])
        if clock:
            found.append(("上班" if kind == "in" else "下班", clock))
    return found


def format_clocks(clocks):
    return "、".join(f"{kind} {clock}" for kind, clock in clocks)


def punch_logs(path):
    """Every clock time for each person on each date, in DAKA column order."""
    table = _read(path)
    columns = [str(name) for name in table.columns]
    name_at = columns.index("姓名")
    date_at = columns.index("日期")
    logs = {}
    for row in table.itertuples(index=False):
        values = list(row)
        name = str(values[name_at]).strip()
        if not name or name.lower() == "nan":
            continue
        try:
            when = pd.to_datetime(values[date_at]).strftime("%Y-%m-%d")
        except Exception:
            continue
        clocks = _clocks(columns, values)
        if clocks:
            logs[(name, when)] = clocks
    return logs


def punch_counts(path):
    """How many clock times DAKA stored for each person on each date.

    Each filled 上班 or 下班 counts. A normal day with a lunch break is four:
    arrive, leave for lunch, return, and leave.
    """
    return {key: len(clocks) for key, clocks in punch_logs(path).items()}


_daka_cache = {"key": None, "value": None}


def load_daka(path):
    """One punch record per person per date.

    The parsed file is kept until its size or save time changes.
    """
    from pathlib import Path
    target = Path(path)
    try:
        key = (str(target.resolve()), target.stat().st_mtime_ns, target.stat().st_size)
    except OSError:
        key = (str(target), 0, 0)
    if _daka_cache["key"] == key and _daka_cache["value"] is not None:
        found = dict(_daka_cache["value"])
        found["__names__"] = set(found.get("__names__") or ())
        return found
    punches = _parse_daka(target)
    _daka_cache["key"] = key
    _daka_cache["value"] = punches
    return punches


def _parse_daka(path):
    """One punch record per person per date.

    Clock-in is the first 上班 column. Clock-out is the last 下班 column.
    A lunch break is the pair in between and is not the start or the end.
    """
    table = _read(path)
    columns = [str(name) for name in table.columns]
    name_at = columns.index("姓名")
    date_at = columns.index("日期")
    punches = {}
    names = set()
    for row in table.itertuples(index=False):
        values = list(row)
        name = str(values[name_at]).strip()
        if not name or name.lower() == "nan":
            continue
        names.add(name)
        try:
            date = pd.to_datetime(values[date_at]).strftime("%Y-%m-%d")
        except Exception:
            continue
        clock_in, in_place, clock_out, out_place = _pair_punches(columns, values)
        punches[(name, date)] = {
            "in": clock_in,
            "out": clock_out,
            "place": in_place,
            "code": _place_code(in_place),
            "in_place": in_place,
            "out_place": out_place,
            "in_code": _place_code(in_place),
            "out_code": _place_code(out_place),
        }
    punches["__names__"] = names
    return punches


def punch_for(punches, name, date):
    found = punches.get((name, date))
    if found:
        return found
    return {
        "in": "", "out": "", "place": "", "code": "",
        "in_place": "", "out_place": "", "in_code": "", "out_code": "",
    }


def daka_names(punches):
    return punches.get("__names__", set())
