"""Detail lines printed on every salary slip."""

import re

from payroll.core.money import (
    LATE_DEDUCT_MINUTES,
    OFFICE_HALF_DAY_MINUTES,
    serious_late,
    unpaid_amount,
)


def _num(row, key):
    try:
        value = row.get(key)
    except (AttributeError, TypeError):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _text(row, key):
    try:
        value = row.get(key)
    except (AttributeError, TypeError):
        return ""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _whole(value):
    number = float(value)
    if abs(number - round(number)) < 0.001:
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _days(value):
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


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


def breakdown_lines(row, month=None):
    """One line per figure that needs a reason: leave taken this month, the pay formula, lateness."""
    if row is None:
        return []
    lines = []
    full = _num(row, "full_salary") or _num(row, "basic_salary")
    basic = _num(row, "basic_salary")
    month_days = int(_num(row, "month_days") or 0)
    counted = int(_num(row, "counted_days") or 0)
    partial = bool(month_days and counted and counted < month_days and abs(full - basic) > 0.009)
    taken = dates_in_month(_text(row, "annual_dates"), month)
    annual_days = _num(row, "annual_taken")
    if taken:
        lines.append(f"本月年假 Annual leave taken: {taken}（{_days(annual_days)} 日）")
    elif annual_days:
        lines.append(f"本月年假 Annual leave taken: {_days(annual_days)} 日")
    else:
        lines.append("本月年假 Annual leave taken: 無")
    if partial and full and month_days:
        lines.append(f"基本薪金 Basic salary: ${_whole(full)}/{month_days}×{counted} = HKD${basic:,.2f}")
    leave_pay = _num(row, "leave_pay")
    leave_days = _num(row, "unused_annual_days")
    if leave_pay > 0.009 and full and leave_days:
        lines.append(
            f"未用年假 Unused annual leave: {_days(leave_days)} 日 × ${_whole(full)} × 12 / 365 = HKD${leave_pay:,.2f}"
        )
    late = dates_in_month(_text(row, "late_text") or _text(row, "late_dates"), month)
    if late:
        lines.append(f"遲到 Lateness: {late}")
    early = _text(row, "early_text") or _text(row, "early_dates")
    early = dates_in_month(early, month) or ""
    if early:
        lines.append(f"早退 Early leave: {early}")
    book = _text(row, "book")
    limit = OFFICE_HALF_DAY_MINUTES if book == "admin" else LATE_DEDUCT_MINUTES
    deduct_days = _num(row, "salary_deduct_days")
    if deduct_days > 0.009 and full and month_days:
        amount = unpaid_amount(full, month_days, deduct_days)
        marked = serious_late(late, limit)
        why = "、".join(f"{day} {minutes}分鐘" for day, minutes in marked) or late or f"{_days(deduct_days)} 日"
        lines.append(
            f"扣薪 Salary deduction: {_days(deduct_days)} 日（{why}）${_whole(full)}/{month_days}×{_days(deduct_days)} = HKD${amount:,.2f}"
        )
    unpaid_days = _num(row, "unpaid_days")
    unpaid_dates = dates_in_month(_text(row, "unpaid_dates"), month)
    if unpaid_days > 0.009:
        when = f"（{unpaid_dates}）" if unpaid_dates else ""
        lines.append(f"無薪假 NPL: {_days(unpaid_days)} 日{when}")
    sick_dates = dates_in_month(_text(row, "sick_dates"), month)
    if sick_dates:
        lines.append(f"病假 Sick leave: {sick_dates}")
    return lines
