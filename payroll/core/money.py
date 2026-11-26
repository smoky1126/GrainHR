"""Pay figures used by the October 2026 full-time slips."""

import re

from payroll.core.config import ATTENDANCE_BONUS, MPF_MAX_INCOME, MPF_MIN_INCOME, MPF_RATE


def round_money(value):
    return round(float(value) + 0.0, 2)


def employee_mpf(basic, scheme):
    if scheme != "mpf":
        return 0.0
    basic = float(basic or 0)
    if basic < MPF_MIN_INCOME:
        return 0.0
    return round_money(min(basic, MPF_MAX_INCOME) * MPF_RATE)


def employer_mpf(basic, scheme):
    return employee_mpf(basic, scheme)


def unpaid_amount(basic, days_in_month, unpaid_days):
    days = float(unpaid_days or 0)
    if days == 0:
        return 0.0
    return round_money(float(basic) / float(days_in_month) * days)


def annual_leave_pay(monthly_basic, unused_days):
    """Unused annual leave on a last payment: full monthly salary × 12 / 365 × unused days."""
    days = float(unused_days or 0)
    if days == 0:
        return 0.0
    return round_money(float(monthly_basic or 0) * 12 / 365 * days)


def pay_detected_overtime(choice, leaving, office=False):
    """Pay detected overtime unless it was saved as time off.

    A last payment pays it unless it was saved as time off. Office staff are
    never paid overtime.
    """
    if office:
        return False
    text = str(choice or "").strip().lower()
    if text in {"exchange", "補鐘"}:
        return False
    if text in {"pay", "支薪"}:
        return True
    return bool(leaving)


def rent_amount(basic, unpaid, rate, rent_base):
    rate = float(rate or 0)
    if rate == 0:
        return 0.0
    base = float(basic) - float(unpaid or 0) if rent_base == "after_unpaid" else float(basic)
    return round_money(base * rate)


def overtime_pay(basic, days_in_month, hours):
    """Hours x basic salary / days in the month / 9.5."""
    hours = float(hours or 0)
    days = float(days_in_month or 0)
    if hours == 0 or days == 0:
        return 0.0
    from payroll.core.config import HOUR_STANDARD
    return round_money(float(basic or 0) * hours / (days * HOUR_STANDARD))


LATE_DEDUCT_MINUTES = 15
OFFICE_HALF_DAY_MINUTES = 240
BONUS_MONTHS = (3, 6, 9, 12)
LATE_GRACE_MINUTES = 5


def serious_late(text, limit=LATE_DEDUCT_MINUTES):
    """Days late by more than `limit` minutes. Text is like '3/11 23分鐘'."""
    found = []
    for match in re.finditer(r"(\d{1,2}/\d{1,2})\s*(\d+)\s*分鐘", str(text or "")):
        minutes = int(match.group(2))
        if minutes > limit:
            found.append((match.group(1), minutes))
    return found


def bonus_rule_text():
    """One sentence for the page and the Excel report."""
    months = "、".join(str(month) for month in BONUS_MONTHS)
    return (
        f"完整月份沒有遲到超過 {LATE_GRACE_MINUTES} 分鐘、沒有早退、沒有缺勤，就累積 ${int(ATTENDANCE_BONUS)}。"
        f"在 {months} 月一次發放該季三個月的總數，並計入淨薪金。"
        "內地勞工、寫字樓和兼職沒有。"
    )


def attendance_bonus(eligible, late_mins, early_mins, unpaid_days, absent_days, override, month=None):
    """$1,000 earned in a clean full month. Paid out only in a quarter-end month.

    Late by 5 minutes or less still qualifies. `month` is ignored here; the caller
    adds the quarter total in March, June, September and December.
    A value in the adjustments sheet replaces the earned amount.
    """
    del month
    if override is not None and override != "":
        return round_money(override)
    if not eligible:
        return 0.0
    if float(late_mins or 0) > LATE_GRACE_MINUTES or float(early_mins or 0) > 0:
        return 0.0
    if float(unpaid_days or 0) > 0 or float(absent_days or 0) > 0:
        return 0.0
    return float(ATTENDANCE_BONUS)


def net_pay(basic, other_income, ot_pay, rent, unpaid, water, mpf, manual_delta, bonus_paid=0, electricity=0):
    return round_money(
        float(basic or 0)
        + float(other_income or 0)
        + float(ot_pay or 0)
        - float(rent or 0)
        - float(unpaid or 0)
        - float(water or 0)
        - float(electricity or 0)
        - float(mpf or 0)
        + float(manual_delta or 0)
        + float(bonus_paid or 0)
    )


def unused_rest(opening, entitlement, statutory_days, taken):
    return float(opening or 0) + float(entitlement or 0) + float(statutory_days or 0) - float(taken or 0)
