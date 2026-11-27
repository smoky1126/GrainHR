"""Detail lines printed on every salary slip.

Figures already printed on the slip itself, such as annual leave, NPL,
lateness and early leave, are not repeated here.
"""

import re


def _text(row, key):
    try:
        value = row.get(key)
    except (AttributeError, TypeError):
        return ""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def dates_in_month(text, month):
    """Keep only dates in this pay month. 12/10 is October and must not stay on a November slip."""
    kept = []
    for part in re.split(r"[、,，;；]", str(text or "")):
        part = part.strip()
        match = re.search(r"(\d{1,2})/(\d{1,2})", part)
        if not match:
            continue
        if month and int(match.group(2)) != int(month):
            continue
        kept.append(part)
    return "、".join(kept)


def missing_punch_marks(text, month=None):
    """Forgot to clock in, clock out, or both. Dates outside this pay month are left out."""
    marks = []
    source = dates_in_month(text, month) if month else str(text or "")
    for part in re.split(r"[、,，;；]", source):
        part = part.strip()
        if not part:
            continue
        if part.endswith("上班"):
            marks.append(f"{part[:-2]} 上班缺卡")
        elif part.endswith("下班"):
            marks.append(f"{part[:-2]} 下班缺卡")
        else:
            marks.append(f"{part} 全天缺卡")
    return marks


def breakdown_lines(row, month=None, year=None):
    """Only what the rest of the slip does not already show."""
    if row is None:
        return []
    lines = []
    book = _text(row, "book")
    if year and month and book:
        from payroll.core.holidays import holiday_dates
        holidays = holiday_dates(year, month, book)
        if holidays:
            title = "公眾假期 Public holiday" if book == "admin" else "法定假期 Statutory holiday"
            lines.append(f"{title}: {holidays}")
    sick_dates = dates_in_month(_text(row, "sick_dates"), month)
    if sick_dates:
        lines.append(f"病假 Sick leave: {sick_dates}")
    return lines
