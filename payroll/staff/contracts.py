"""Mainland contract terms. A later start date leaves the months in between unpaid.

The staff file keeps one 合約完結日期, the end of the current term. When a new
term starts after that date, the earlier term stays here so a rebuilt month
still stops the day before the old end.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from payroll.core.config import home
from payroll.staff.staff import _as_date, _text


def terms_path():
    return home() / "data" / "contract_terms.xlsx"


_cache = None


def clear_contract_cache():
    global _cache
    _cache = None


def _load():
    global _cache
    path = terms_path()
    from payroll.core.excel_io import file_stamp
    try:
        stamp = file_stamp(path) if path.exists() else None
    except OSError:
        stamp = None
    if _cache and _cache[0] == (str(path), stamp):
        return _cache[1]
    found = {}
    if path.exists():
        from payroll.core.excel_io import read_excel
        frame = read_excel(path, engine="openpyxl")
        for _, row in frame.iterrows():
            number = _text(row.get("employee_no"))
            started = _as_date(row.get("start"))
            ended = _as_date(row.get("end"))
            if number and ended is not None:
                found.setdefault(number, []).append((started, ended))
        for number in found:
            found[number].sort(key=lambda item: (item[0] or item[1], item[1]))
    _cache = ((str(path), stamp), found)
    return found


def saved_terms(employee_no):
    """Saved (start, end) pairs. End is the 合約完結日期, not the last working day."""
    return list(_load().get(_text(employee_no), []))


def periods_for(record):
    """Terms that decide pay. Without a saved gap, the staff-file date is the only term."""
    if _text(record.get("sheet")) != "內地勞工":
        return []
    saved = saved_terms(record.get("employee_no"))
    if saved:
        return saved
    ended = _as_date(record.get("contract_end"))
    if ended is None:
        return []
    return [(_as_date(record.get("join_date")), ended)]


def covered_span(record, month_start, month_end):
    """The employed days of one month, or None when no term covers it."""
    blocks = []
    for started, ended in periods_for(record):
        if ended is None:
            continue
        last = ended - timedelta(days=1)
        first = started or month_start
        begin = max(month_start, first)
        finish = min(month_end, last)
        if begin <= finish:
            blocks.append((begin, finish))
    if not blocks:
        return None
    blocks.sort()
    begin, finish = blocks[0]
    for start, end in blocks[1:]:
        if start > finish + timedelta(days=1):
            break
        finish = max(finish, end)
    return begin, finish


def term_cutoff(record, day):
    """Last working day of the term that includes day, or None."""
    if day is None:
        return None
    for started, ended in periods_for(record):
        if ended is None:
            continue
        last = ended - timedelta(days=1)
        first = started or date.min
        if first <= day <= last:
            return last
    return None


def ending_this_month(record, info):
    """Last working day when a term ends inside the payroll month."""
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    for started, ended in periods_for(record):
        if ended is None:
            continue
        last = ended - timedelta(days=1)
        if start <= last <= end and (started is None or started <= last):
            return last
    return None


def _write(rows):
    path = terms_path()
    frame = pd.DataFrame(rows, columns=["employee_no", "start", "end"])
    from payroll.core.excel_io import save_excel
    save_excel(path, frame)
    clear_contract_cache()
    return path


def _rows():
    rows = []
    for number, terms in _load().items():
        for started, ended in terms:
            rows.append({
                "employee_no": number,
                "start": started.isoformat() if started else "",
                "end": ended.isoformat(),
            })
    return rows


def apply_renewal(employee_no, join, old_end, new_start, new_end):
    """Record a renewal. A start after the old end leaves the gap unpaid."""
    number = _text(employee_no)
    if not number:
        raise SystemExit("找不到員工編號。")
    if old_end is None or new_start is None or new_end is None:
        raise SystemExit("請填新合約的開始和完結日期。")
    if new_end <= new_start:
        raise SystemExit("合約完結日期要遲過開始日期。")
    terms = saved_terms(number)
    if new_start <= old_end:
        if not terms:
            return
        kept = terms[:-1] + [(terms[-1][0], new_end)]
    else:
        earlier = [item for item in terms if item[0] is None or item[0] < new_start]
        if earlier:
            started = earlier[-1][0]
            kept = earlier[:-1] + [(started, old_end), (new_start, new_end)]
        else:
            kept = [(join, old_end), (new_start, new_end)]
    rows = [row for row in _rows() if row["employee_no"] != number]
    for started, ended in kept:
        rows.append({
            "employee_no": number,
            "start": started.isoformat() if started else "",
            "end": ended.isoformat(),
        })
    _write(rows)
