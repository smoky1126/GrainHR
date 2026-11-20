"""Annual leave already taken, from the year's Staff Holiday Record.

The workbook sits in the accounting folder, one sheet per month. Each cell
is a leave code. AL is one day, and AL 0.5 is half a day. The payroll does
not rewrite that file.
"""

import os
import re
from pathlib import Path

from openpyxl import load_workbook

from payroll.core.config import home
from payroll.core.settings import path_for
from payroll.core.names import chinese

ACCOUNTING_DIR = path_for("accounting") or Path(".")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_SKIP = {"office", "retail", "bread", "md", "pt", "員工", "staff"}
_AL = re.compile(r"^AL(?:\s+([0-9]*\.?[0-9]+))?$", re.IGNORECASE)
_CACHE = {}


def holiday_record_path(year):
    override = os.environ.get("PAYROLL_HOLIDAY", "").strip()
    if override:
        path = Path(override)
        return path if path.exists() else None
    if os.environ.get("PAYROLL_HOME", "").strip():
        candidate = home() / "data" / f"{year} Staff Holiday Record.xlsx"
        return candidate if candidate.exists() else None
    path = ACCOUNTING_DIR / str(year) / f"{year} Staff Holiday Record.xlsx"
    return path if path.exists() else None


def _sheet_month(name, year):
    parts = " ".join(str(name).split()).split(" ")
    if len(parts) != 2 or parts[0] != str(year):
        return None
    return _MONTHS.get(parts[1].lower())


def _al_days(value):
    if value is None:
        return 0.0
    match = _AL.match(str(value).strip())
    if not match:
        return 0.0
    if not match.group(1):
        return 1.0
    return float(match.group(1))


def _english_key(text):
    return re.sub(r"[^a-z]", "", str(text or "").lower())


def _tokens(text):
    return set(re.findall(r"[a-z]+", str(text or "").lower()))


def _read_names(path, year, through_month):
    """Holiday-sheet name to days taken, for January through through_month."""
    book = load_workbook(path, read_only=True, data_only=True)
    totals = {}
    last_month = 0
    try:
        for sheet in book.sheetnames:
            month = _sheet_month(sheet, year)
            if month is None or month > through_month:
                continue
            last_month = max(last_month, month)
            for row in book[sheet].iter_rows(values_only=True):
                if not row or row[0] is None:
                    continue
                name = " ".join(str(row[0]).split())
                lowered = name.lower()
                if not name or lowered in _SKIP or "leave record" in lowered or lowered.startswith("name"):
                    continue
                if not re.search(r"[A-Za-z\u4e00-\u9fff]", name):
                    continue
                days = sum(_al_days(cell) for cell in row[1:32])
                totals[name] = totals.get(name, 0.0) + days
    finally:
        book.close()
    return totals, last_month


def _one_apart(left, right):
    """True when the two words are the same or one letter apart."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    if len(left) > len(right):
        left, right = right, left
    skipped = False
    index = 0
    for char in left:
        if index < len(right) and char != right[index]:
            if skipped:
                return False
            skipped = True
            index += 1
        if index >= len(right) or char != right[index]:
            return False
        index += 1
    return True


def _close_name(left_tokens, staff_tokens):
    if len(left_tokens) != len(staff_tokens) or len(left_tokens) < 2:
        return False
    spare = list(staff_tokens)
    misses = 0
    for token in left_tokens:
        if token in spare:
            spare.remove(token)
            continue
        close = [item for item in spare if _one_apart(token, item)]
        if len(close) != 1:
            return False
        spare.remove(close[0])
        misses += 1
        if misses > 1:
            return False
    return misses == 1


def _only(found):
    if found and len(found) == 1:
        return next(iter(found))
    return ""


def _match(name, by_english, by_chinese, by_tokens, by_hint):
    left, _, nick = name.partition("_")
    left = left.strip()
    nick = nick.strip()
    exact = _only(by_english.get(_english_key(left)))
    if exact:
        return exact
    if nick:
        hinted = _only(by_hint.get(nick.casefold())) or _only(by_hint.get(chinese(nick)))
        if hinted:
            return hinted
    zh = chinese(name)
    if len(zh) >= 2:
        found = _only(by_chinese.get(zh))
        if found:
            return found
    tokens = _tokens(left)
    if len(tokens) < 2:
        return ""
    hits = set()
    close = set()
    for staff_tokens, numbers in by_tokens:
        if staff_tokens == tokens or staff_tokens <= tokens or tokens <= staff_tokens:
            hits.update(numbers)
        elif _close_name(tokens, staff_tokens):
            close.update(numbers)
    if len(hits) == 1:
        return next(iter(hits))
    if not hits and len(close) == 1:
        return next(iter(close))
    return ""


def annual_leave_taken(staff, year, month):
    """Days of annual leave taken from January through this month.

    Returns (by employee number, last month actually in the workbook).
    A missing workbook returns ({}, 0).
    """
    path = holiday_record_path(year)
    if path is None:
        return {}, 0
    stamp = path.stat().st_mtime
    key = (str(path), stamp, int(year), int(month))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = _read_names(path, int(year), int(month))
    totals, last_month = _CACHE[key]
    return _assign(staff, totals), last_month


def _assign(staff, totals):
    by_english = {}
    by_chinese = {}
    by_tokens = []
    by_hint = {}
    for _, record in staff.iterrows():
        number = str(record.get("employee_no") or "").strip()
        if not number or number.lower() == "nan":
            continue
        english = _english_key(record.get("name_en"))
        if english:
            by_english.setdefault(english, set()).add(number)
        zh = chinese(str(record.get("name_zh") or ""))
        if len(zh) >= 2:
            by_chinese.setdefault(zh, set()).add(number)
        tokens = _tokens(record.get("name_en"))
        if len(tokens) >= 2:
            by_tokens.append((tokens, {number}))
        hint = str(record.get("roster_hint") or "").strip()
        if hint and hint.lower() != "nan":
            by_hint.setdefault(hint.casefold(), set()).add(number)
            hint_zh = chinese(hint)
            if hint_zh:
                by_hint.setdefault(hint_zh, set()).add(number)
    taken = {}
    for name, days in totals.items():
        number = _match(name, by_english, by_chinese, by_tokens, by_hint)
        if not number:
            continue
        taken[number] = taken.get(number, 0.0) + days
    return taken
