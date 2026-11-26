"""Turn attendance facts, the pay table and the adjustments sheet into a payroll draft."""

import math
import re
from datetime import date

import pandas as pd

from payroll.core.config import home, opening_balance_path, parse_month, book_info
from payroll.attendance.daka import load_daka
from payroll.core.holidays import holiday_count, holiday_known
from payroll.attendance.days import empty_summary, merge_days, problem_lines
from payroll.core.labels import (
    DUPLICATE, LEFT, MANUAL_PAY, NEW_JOINER, NOT_IN_STAFF, NO_ROSTER_NAME, NOT_LINKED, PART_TIME,
    VARYING_PAY, VARYING_PAY_NOTE, chinese_note,
)
from payroll.core.money import (
    BONUS_MONTHS,
    LATE_GRACE_MINUTES,
    attendance_bonus,
    annual_leave_pay,
    employee_mpf,
    employer_mpf,
    net_pay,
    overtime_pay,
    pay_detected_overtime,
    rent_amount,
    round_money,
    unpaid_amount,
    unused_rest,
)
from payroll.core.names import match_roster_name
from payroll.staff.staff import (
    _as_date, blank_adjustment, employed_in, employed_window, ensure_adjustments, ensure_pay_table,
    load_staff, paid_numbers, pay_table_path,
)


def _is_blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip() == ""


def _num(value, default=0.0):
    if _is_blank(value):
        return default
    return float(value)


def _text(value):
    if _is_blank(value):
        return ""
    return str(value).strip()


def _hour_text(hours):
    value = round(float(hours), 2)
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def suggest_ot(detected):
    """OT dates from DAKA, and early leave rounded up to the next half hour, as 已補."""
    if not detected:
        return ""
    ot_dates = list(detected.get("ot_dates") or [])
    early = []
    for part in _text(detected.get("early_dates")).split("、"):
        match = re.match(r"(\d{1,2}/\d{1,2})\s+(\d+)分鐘", part.strip())
        if not match:
            continue
        hours = math.ceil(int(match.group(2)) / 30) * 0.5
        if hours:
            early.append((match.group(1), hours))
    if not ot_dates and not early:
        return ""
    ot_total = sum(float(hours) for _label, hours in ot_dates)
    early_total = sum(hours for _label, hours in early)
    lines = [
        f"OT (Hours): {_hour_text(ot_total)} \u2013 {_hour_text(early_total)} = {_hour_text(ot_total - early_total)}"
    ]
    for label, hours in ot_dates:
        lines.append(f"{label} : {_hour_text(hours)}")
    for label, hours in early:
        lines.append(f"{label} 已補{_hour_text(hours)}")
    return "\n".join(lines)


def _worst_minutes(dates):
    """The longest single lateness. Five minutes every day is still five, not the month's total."""
    worst = 0
    for part in _text(dates).split("、"):
        match = re.search(r"(\d+)\s*分鐘", part)
        if match:
            worst = max(worst, int(match.group(1)))
    return worst


_ABSENCE = {
    "unpaid": "unpaid", "無薪假": "unpaid",
    "sick": "sick", "病假": "sick",
    "worked": "worked", "有上班": "worked", "有上班（忘記打卡）": "worked",
}
_EARNED = {}
_EARLIER_DRAFTS = {}
_BUILDING = set()


def parse_absence_choices(text):
    """`6/10:unpaid、8/10:sick` into {label: kind}."""
    found = {}
    for part in re.split(r"[、,;；\n]", _text(text)):
        part = part.strip()
        if ":" not in part and "：" not in part:
            continue
        label, kind = re.split(r"[:：]", part, maxsplit=1)
        mapped = _ABSENCE.get(kind.strip())
        if mapped and label.strip():
            found[label.strip()] = mapped
    return found


def _link_office(pay_table, facts):
    """Fill a blank office roster name. Never overwrite one that is already set."""
    if facts is None or facts.empty or "name" not in facts.columns:
        return pay_table
    names = sorted({_text(value) for value in facts["name"] if _text(value)})
    changed = False
    if "roster_name" not in pay_table.columns:
        pay_table["roster_name"] = ""
    pay_table["roster_name"] = pay_table["roster_name"].astype("object")
    for index, person in pay_table.iterrows():
        if _text(person.get("roster_name")):
            continue
        matched = match_roster_name(_text(person.get("slip_name")), "", "", names)
        if not matched:
            continue
        pay_table.at[index, "roster_name"] = matched
        changed = True
    if changed:
        pay_table.to_excel(pay_table_path("admin"), index=False)
    return pay_table


def _month_earned(info, month, staff_id, employee_no):
    """Bonus earned in an earlier month of this quarter. Missing history counts as 0."""
    book = info.get("book", "bg")
    key = (book, int(info["year"]), int(month), _text(staff_id))
    if key in _EARNED:
        return _EARNED[key]
    booked = book_info(parse_month(f"{info['year']}-{int(month):02d}"), book)
    suffix = booked.get("balance_suffix", "")
    path = home() / "data" / "balances" / f"{info['year']}_{int(month):02d}_close{suffix}.xlsx"
    amount = None
    if path.exists():
        frame = pd.read_excel(path)
        if "staff_id" in frame.columns and "bonus_earned" in frame.columns:
            frame["staff_id"] = frame["staff_id"].map(_text)
            rows = frame[frame["staff_id"] == _text(staff_id)]
            if rows.empty and "employee_no" in frame.columns:
                frame["employee_no"] = frame["employee_no"].map(_text)
                rows = frame[frame["employee_no"] == _text(employee_no)]
            if not rows.empty:
                amount = _num(rows.iloc[0]["bonus_earned"])
    draft_key = (book, int(info["year"]), int(month))
    if amount is None and draft_key not in _BUILDING and (booked["system"] / "daily_facts.xlsx").exists():
        if draft_key not in _EARLIER_DRAFTS:
            _EARLIER_DRAFTS[draft_key] = build_draft(booked)
        earlier = _EARLIER_DRAFTS[draft_key]
        rows = earlier[earlier["staff_id"].astype(str) == _text(staff_id)]
        amount = _num(rows.iloc[0]["bonus"]) if not rows.empty else 0
    amount = 0 if amount is None else amount
    _EARNED[key] = amount
    return amount


def quarter_history(info, staff_id, employee_no):
    """(month, earned) for the earlier months of this quarter."""
    month = int(info["month"])
    start = ((month - 1) // 3) * 3 + 1
    return [(earlier, _month_earned(info, earlier, staff_id, employee_no)) for earlier in range(start, month)]


def _absent_memo(adj, sick_hours):
    text = _text(adj.absent_text)
    if sick_hours:
        extra = f"病假 {sick_hours:g} 小時"
        text = f"{text}\n{extra}".strip() if text else extra
    return text


def _bonus_reason(bonus_ok, partial, worst_late, detected, unpaid_days, sick_days, pending):
    if not bonus_ok:
        return "不適用（內地勞工、寫字樓或兼職）"
    if partial:
        return "不是完整月份"
    if float(worst_late or 0) > LATE_GRACE_MINUTES:
        return f"遲到超過 {LATE_GRACE_MINUTES} 分鐘（{detected.get('late_dates', '')}）"
    if detected.get("early_mins"):
        return f"有早退（{detected.get('early_dates', '')}）"
    if float(unpaid_days or 0) > 0 or float(sick_days or 0) > 0:
        return "有無薪假或病假"
    if pending:
        return "有缺勤未確認（" + "、".join(pending) + "）"
    if detected.get("missing_days"):
        return "有缺卡"
    return ""


def _override(value):
    if _is_blank(value):
        return None
    return float(value)


def _picked_number(typed, roster_value):
    """A blank adjustment cell means: use the roster."""
    if _is_blank(typed):
        return _num(roster_value)
    return _num(typed)


def _picked_text(typed, roster_value):
    if _is_blank(typed):
        return _text(roster_value)
    return _text(typed)


def _hours_paid(adj, detected_hours):
    if adj is None or _is_blank(adj.get("ot_hours_paid")):
        return detected_hours
    return _num(adj.get("ot_hours_paid"))


def _annual_closing(opening_row, taken):
    labels = []
    openings = []
    for index in (1, 2):
        label = _text(opening_row.get(f"al_{index}_label"))
        days = opening_row.get(f"al_{index}_opening")
        if label:
            labels.append(label)
            openings.append(_num(days))
    remaining = float(taken or 0)
    closings = list(openings)
    for index in range(len(closings) - 1, -1, -1):
        used = min(closings[index], remaining)
        closings[index] -= used
        remaining -= used
    return labels, closings


def _empty_balance():
    return pd.Series({
        "opening_rest": 0,
        "al_1_label": "",
        "al_1_opening": "",
        "al_2_label": "",
        "al_2_opening": "",
    })


def _display_name(record, fallback):
    if record is None:
        return fallback
    english = _text(record.get("name_en"))
    chinese_name = _text(record.get("name_zh"))
    if english and chinese_name:
        return f"{english} {chinese_name}"
    return chinese_name or english or fallback


def _index_staff(staff, employed):
    """Prefer the row that is employed this month when an employee number is reused."""
    work = staff.copy()
    work["_employed"] = employed.reindex(staff.index).fillna(False).astype(bool).to_numpy()
    by_number = {}
    for _, record in work.sort_values("_employed").iterrows():
        by_number[record["employee_no"]] = record.drop(labels=["_employed"])
    return by_number


def _planned_last(info, employee_no):
    raw = (info.get("leave_until") or {}).get(employee_no)
    if raw is None:
        return None
    from payroll.staff.staff import _as_date
    return _as_date(raw)


def _window_until(record, info, last):
    """Employment window ending on a chosen last day, including a future last day."""
    start, end = _month_bounds(info)
    if last is None or last < start or last > end:
        return None
    from payroll.staff.staff import _as_date
    joined = _as_date(record.get("join_date")) if record is not None else None
    if joined is not None and joined > last:
        return None
    first = start if joined is None or joined < start else joined
    if first > last:
        return None
    return first, last


def _employment_window(record, info, employee_no):
    planned = _planned_last(info, employee_no)
    if planned is not None and record is not None:
        return _window_until(record, info, planned)
    if record is not None:
        return employed_window(record, info)
    return None


def _month_bounds(info):
    return date(info["year"], info["month"], 1), date(info["year"], info["month"], info["days"])


def _partial(window, info):
    return window is not None and window != _month_bounds(info)


def _partial_note(record, window, planned=False):
    first, last = window
    counted = (last - first).days + 1
    from payroll.staff.staff import _as_date
    left = _as_date(record.get("leave_date")) if record is not None else None
    title = "本月離職" if planned or (left is not None and left <= last) else "本月入職"
    return (
        f"{title}：只計 {first.day}/{first.month}\u2013{last.day}/{last.month} 基本薪金"
        f"（{counted} 天）。未用年假按日薪計入薪金。代通知金請在「其他調整」輸入。"
    )


def _period_text(info, window):
    if window is None or not _partial(window, info):
        return info["period_text"]
    first, last = window
    counted = (last - first).days + 1
    return (
        f"{first.day:02d}/{first.month:02d}/{first.year} \u2013 "
        f"{last.day:02d}/{last.month:02d}/{last.year} ({counted} Days)"
    )


def _varying_pay(record, slip_name):
    texts = [_text(slip_name)]
    if record is not None:
        texts.append(_text(record.get("name_zh")))
    return any(name in text for text in texts for name in VARYING_PAY)


def _roster_names_on_payroll():
    from payroll.staff.staff import pay_table_path
    names = set()
    for book_name in ("bg", "md", "admin"):
        path = pay_table_path(book_name)
        if not path.exists():
            continue
        table = pd.read_excel(path)
        if "roster_name" not in table.columns:
            continue
        names.update(_text(value) for value in table["roster_name"])
    names.discard("")
    return names


def _clip_facts(facts, windows):
    """Drop shifts outside a leaver's or new joiner's employed days."""
    if facts is None or len(facts) == 0 or not windows:
        return facts
    dates = pd.to_datetime(facts["date"], errors="coerce")
    names = facts["name"].map(_text)
    keep = pd.Series(True, index=facts.index)
    for name, window in windows.items():
        mask = names.eq(name)
        if not mask.any():
            continue
        keep.loc[mask] = (
            (dates.loc[mask] >= pd.Timestamp(window[0]))
            & (dates.loc[mask] <= pd.Timestamp(window[1]))
        )
    return facts.loc[keep].copy()


def _lookup_balance(opening, staff_id, employee_no):
    if opening is None or opening.empty:
        return None
    if staff_id and "staff_id" in opening.columns:
        hits = opening[opening["staff_id"].map(_text) == staff_id]
        if not hits.empty:
            return hits.iloc[0]
    if employee_no and "employee_no" in opening.columns:
        hits = opening[opening["employee_no"].map(_text) == employee_no]
        if not hits.empty:
            return hits.iloc[0]
    return None


def _blank_row(name, shops, problem, roster_name=""):
    return {
        "employee_no": "",
        "staff_id": "",
        "slip_name": name,
        "name_en": "",
        "name_zh": "",
        "roster_name": roster_name,
        "department": "",
        "position": "",
        "join_date": "",
        "shops": shops,
        "basic_salary": 0,
        "scheme": "",
        "rent": 0,
        "water": 0,
        "electricity": 0,
        "unpaid_days": 0,
        "unpaid_amount": 0,
        "other_income": 0,
        "stated_extra": 0,
        "ot_pay": 0,
        "manual_delta": 0,
        "subtotal": 0,
        "mpf_employee": 0,
        "mpf_employer": 0,
        "net": 0,
        "bonus": 0,
        "allowance_desc": "",
        "allowance_amount": 0,
        "allowance_section": "",
        "allowance_note": "",
        "opening_rest": 0,
        "rest_entitlement": 0,
        "statutory_days": 0,
        "roster_rest_days": 0,
        "taken_rest": 0,
        "taken_dates": "",
        "unused_rest": 0,
        "unused_rest_calc": 0,
        "sick_days": 0,
        "annual_taken": 0,
        "birthday_days": 0,
        "al_1_label": "",
        "al_1_days": "",
        "al_2_label": "",
        "al_2_days": "",
        "absent_days": 0,
        "absent_mins": 0,
        "absent_text": "",
        "late_mins_detected": 0,
        "early_mins_detected": 0,
        "ot_hours_detected": 0,
        "ot_text": "",
        "ot_suggest": "",
        "salary_reference": "",
        "ot_choice": "",
        "ot_hours_paid": "",
        "bonus_override": "",
        "note": "",
        "missing_days": 0,
        "roster_days": "",
        "days_worked": 0,
        "missing_text": "",
        "late_text": "",
        "early_text": "",
        "wrong_text": "",
        "day_off_text": "",
        "leave_text": "",
        "roster_unpaid": 0,
        "roster_sick": 0,
        "roster_annual": 0,
        "roster_birthday": 0,
        "roster_rest": 0,
        "roster_rest_dates": "",
        "wrong_site_days": 0,
        "review": problem,
        "approved": "",
        "pay_this": False,
        "show_on_review": False,
        "show_not_on_slip": True,
    }


def _shown_rent(person):
    if _text(person.get("scheme")) != "rent":
        return 0
    if not _is_blank(person.get("rent_amount")):
        return _num(person.get("rent_amount"))
    return rent_amount(person.get("basic_salary"), 0, person.get("rent_rate"), _text(person.get("rent_base")) or "basic")


def _shown_allowances(person):
    """Two typed amounts. An old single allowance stays as one total until it is split."""
    if not _is_blank(person.get("transport_amount")) or not _is_blank(person.get("health_amount")):
        return _num(person.get("transport_amount")), _num(person.get("health_amount"))
    desc = _text(person.get("allowance_desc"))
    amount = _num(person.get("allowance_amount"))
    health = "健康" in desc or "Health" in desc
    transport = "交通" in desc or "Transport" in desc
    if health and not transport:
        return 0, amount
    return amount, 0


def pay_sheet_rows(staff, pay_table, info=None):
    employed = employed_in(staff, info) if info is not None else staff["active"]
    by_number = _index_staff(staff, employed)
    rows = []
    paid = paid_numbers()
    for _, person in pay_table.iterrows():
        employee_no = _text(person.employee_no)
        paid.add(employee_no)
        record = by_number.get(employee_no)
        left = record is None or employed_window(record, info) is None if info is not None else (
            record is None or not bool(record["active"])
        )
        transport, health = _shown_allowances(person)
        rows.append({
            "employee_no": employee_no,
            "slip_name": _text(person.slip_name),
            "problem": LEFT if left else "",
            "roster_name": _text(person.roster_name),
            "basic_salary": person.basic_salary,
            "scheme": _text(person.scheme),
            "rent_amount": _shown_rent(person),
            "water": 0 if _text(person.scheme) != "rent" else person.water,
            "electricity": 0 if _text(person.scheme) != "rent" else person.get("electricity"),
            "bonus_eligible": person.bonus_eligible,
            "rest_days_month": person.rest_days_month,
            "allowance_desc": _text(person.allowance_desc),
            "transport_amount": transport,
            "health_amount": health,
            "allowance_section": _text(person.allowance_section),
            "allowance_note": _text(person.allowance_note),
        })
    for _, record in staff[employed & ~staff["part_time"]].iterrows():
        if record["employee_no"] in paid:
            continue
        rows.append({
            "employee_no": record["employee_no"],
            "slip_name": _display_name(record, record["employee_no"]),
            "problem": NEW_JOINER,
            "roster_name": "",
            "basic_salary": None,
            "scheme": "",
            "rent_amount": 0,
            "water": 0,
            "electricity": 0,
            "bonus_eligible": None,
            "rest_days_month": None,
            "allowance_desc": "",
            "transport_amount": 0,
            "health_amount": 0,
            "allowance_section": "",
            "allowance_note": "",
        })
    return pd.DataFrame(rows)


def build_draft(info, facts=None, write=True):
    del write
    book = info.get("book", "bg")
    token = (book, int(info["year"]), int(info["month"]))
    _BUILDING.add(token)
    try:
        return _build_draft(info, facts, book)
    finally:
        _BUILDING.discard(token)


def _build_draft(info, facts, book):
    staff = load_staff()
    pay_table = ensure_pay_table(staff, book=book)
    ensure_adjustments(info, pay_table)
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    opening_path = opening_balance_path(info)
    opening = pd.read_excel(opening_path) if opening_path else pd.DataFrame()
    if facts is None:
        facts = pd.read_excel(info["system"] / "daily_facts.xlsx")
    if book == "admin":
        pay_table = _link_office(pay_table, facts)
    employed = employed_in(staff, info)
    by_number = _index_staff(staff, employed)
    windows = {}
    assume = {}
    for _, person in pay_table.iterrows():
        number = _text(person.employee_no)
        record = by_number.get(number)
        roster_name = _text(person.roster_name)
        window = _employment_window(record, info, number)
        if roster_name and _partial(window, info):
            windows[roster_name] = window
        planned = _planned_last(info, number)
        if roster_name and planned is not None and planned >= date.today():
            assume[roster_name] = planned
    facts = _clip_facts(facts, windows)
    punches = load_daka(info["daka"]) if info["daka"].exists() else {"__names__": set()}
    summaries, day_rows = merge_days(facts, punches, assume_until=assume or None)
    line_by_id = {}
    for _, row in lines.iterrows():
        staff_id = _text(row.staff_id)
        if staff_id:
            line_by_id[staff_id] = row
    duplicate_ids = set(staff.loc[employed, "employee_no"].value_counts().loc[lambda counts: counts > 1].index)
    days = info["days"]
    from payroll.pay.early import EARLY_NOTE, early_keys, include_in_month_pay
    early_ids, early_numbers = early_keys(info)
    rows = []
    matched_names = set()

    for _, person in pay_table.iterrows():
        staff_id = _text(person.staff_id)
        employee_no = _text(person.employee_no)
        record = by_number.get(employee_no)
        window = _employment_window(record, info, employee_no)
        if window is None and record is None:
            window = _month_bounds(info)
        left = record is not None and window is None
        planned = _planned_last(info, employee_no)
        missing_record = record is None
        adj = line_by_id.get(staff_id)
        if adj is None:
            adj = pd.Series(blank_adjustment(person))
        bal = _lookup_balance(opening, staff_id, employee_no)
        if bal is None:
            bal = _empty_balance()
        roster_name = _text(person.roster_name)
        if roster_name:
            matched_names.add(roster_name)
        detected = summaries.get(roster_name, empty_summary()) if roster_name else empty_summary()
        manual_case = employee_no in MANUAL_PAY
        if manual_case:
            detected = empty_summary()
        full_basic = _num(person.basic_salary)
        partial = (not left) and _partial(window, info)
        basic = 0 if left else (full_basic if not partial else round_money(full_basic / days * ((window[1] - window[0]).days + 1)))
        scheme = _text(person.scheme) or "mpf"
        absence_labels = [part.strip() for part in _text(detected.get("absent_dates")).split("、") if part.strip()]
        absence = parse_absence_choices(adj.get("absence_choices"))
        pending_absence = [label for label in absence_labels if label not in absence]
        confirmed_unpaid = sum(1 for label in absence_labels if absence.get(label) == "unpaid")
        confirmed_sick = sum(1 for label in absence_labels if absence.get(label) == "sick")
        confirmed_worked = sum(1 for label in absence_labels if absence.get(label) == "worked")
        if not left and (confirmed_unpaid or confirmed_sick or confirmed_worked or pending_absence):
            detected = dict(detected)
            still = [
                part for part in _text(detected.get("missing_dates")).split("、")
                if part.strip() and part.strip() not in absence
            ]
            detected["missing_dates"] = "、".join(still)
            detected["missing_days"] = len([part for part in still if part])
            detected["unpaid_days"] = _num(detected.get("unpaid_days")) + confirmed_unpaid
            detected["sick_days"] = _num(detected.get("sick_days")) + confirmed_sick
            detected["days_worked"] = _num(detected.get("days_worked")) + confirmed_worked
        unpaid_days = 0 if left else _picked_number(adj.unpaid_days, detected["unpaid_days"])
        sick_days = 0 if left else _picked_number(adj.sick_days, detected["sick_days"])
        sick_hours = 0 if left else _num(adj.get("sick_hours"))
        charge_days = unpaid_days
        if not left and _is_blank(adj.unpaid_days):
            charge_days += sick_days
        unpaid = 0 if left else unpaid_amount(full_basic, days, charge_days) + overtime_pay(full_basic, days, sick_hours)
        salary_deduct_days = 0 if left else _num(adj.get("salary_deduct_days"))
        if salary_deduct_days:
            unpaid = round_money(unpaid + unpaid_amount(full_basic, days, salary_deduct_days))
        mainland = scheme == "rent"
        electricity = 0 if left or not mainland else _num(person.get("electricity"))
        water = 0 if left or not mainland else (
            _num(person.water) if _override(adj.water_override) is None else _override(adj.water_override)
        )
        if left or not mainland:
            rent = 0
        elif not _is_blank(person.get("rent_amount")):
            rent = _num(person.get("rent_amount"))
        else:
            rent = rent_amount(
                basic, unpaid, _num(person.rent_rate), _text(person.rent_base) or "basic"
            )
        mpf_income = basic
        if not left and book == "admin":
            mpf_income = round_money(max(0, basic - unpaid))
        mpf_ee = 0 if left else employee_mpf(mpf_income, scheme)
        mpf_er = 0 if left else employer_mpf(mpf_income, scheme)
        other_income = 0 if left else _num(adj.other_income)
        paid_hours = 0 if left else _hours_paid(adj, detected["ot_hours"])
        leaving = partial and record is not None and (
            _as_date(record.get("leave_date")) is not None or planned is not None
        )
        if left or not pay_detected_overtime(adj.get("ot_choice"), leaving, office=book == "admin"):
            ot_pay = 0
        else:
            ot_pay = overtime_pay(full_basic, days, paid_hours)
        manual = 0 if left else _num(adj.manual_delta)
        subtotal = round_money(basic + other_income + ot_pay - rent - unpaid - water - electricity) if not left else 0
        opening_rest = _num(bal.opening_rest) if not left else 0
        entitlement = _num(person.rest_days_month) if not left else 0
        joined = _as_date(record.get("join_date")) if record is not None else None
        month_start, month_end = _month_bounds(info)
        new_joiner = joined is not None and month_start <= joined <= month_end
        if not left and book != "admin" and new_joiner:
            entitlement = float(math.floor(_num(detected.get("days_worked")) / 5))
        fewer_rest = False
        if not left and book != "admin" and _num(bal.get("had_sick") if hasattr(bal, "get") else 0):
            entitlement = max(0, entitlement - 1)
            fewer_rest = True
        statutory = 0 if left else _picked_number(adj.statutory_days, holiday_count(info, book))
        taken = 0 if left else _picked_number(adj.taken_rest, detected["rest_days"])
        rest_extra = 0 if book == "admin" else statutory
        unused_calc = unused_rest(opening_rest, entitlement, rest_extra, taken) if not left else 0
        unused = unused_calc if left or _override(adj.rest_override) is None else _override(adj.rest_override)
        part_time = record is not None and bool(record.get("part_time"))
        bonus_ok = (
            bool(int(_num(person.bonus_eligible)))
            and scheme != "rent"
            and book != "admin"
            and not part_time
        )
        worst_late = _worst_minutes(detected["late_dates"])
        if not worst_late and detected["late_mins"]:
            worst_late = detected["late_mins"]
        if left or manual_case or (partial and _override(adj.bonus_override) is None):
            bonus = 0
        else:
            bonus = attendance_bonus(
                bonus_ok,
                worst_late,
                detected["early_mins"],
                unpaid_days + (sick_days if _is_blank(adj.unpaid_days) else 0),
                _num(adj.absent_days) + len(pending_absence),
                _override(adj.bonus_override),
            )
        history = []
        payout_month = int(info["month"]) in BONUS_MONTHS
        if not left and book != "admin" and (payout_month or leaving):
            history = quarter_history(info, staff_id, employee_no)
        prior_total = sum(amount for _month, amount in history)
        leaver_choice = _text(adj.get("bonus_leaver"))
        bonus_paid = 0
        if not left and leaving:
            bonus_paid = prior_total if leaver_choice == "pay" else 0
        elif not left and payout_month:
            bonus_paid = prior_total + bonus
        net = net_pay(basic, other_income, ot_pay, rent, unpaid, water, mpf_ee, manual, bonus_paid, electricity) if not left else 0
        labels, closings = _annual_closing(bal, 0 if left else _picked_number(adj.annual_taken, detected["annual_days"]))
        annual_taken = 0 if left else _picked_number(adj.annual_taken, detected["annual_days"])
        leave_days = 0.0
        for value in closings:
            try:
                leave_days += float(value or 0)
            except (TypeError, ValueError):
                continue
        leave_pay = 0.0 if left or not leaving else annual_leave_pay(full_basic, leave_days)
        if leave_pay:
            other_income = round_money(float(other_income or 0) + leave_pay)
            subtotal = round_money(basic + other_income + ot_pay - rent - unpaid - water - electricity)
            net = net_pay(basic, other_income, ot_pay, rent, unpaid, water, mpf_ee, manual, bonus_paid, electricity)
        birthday_days = 0 if left else _picked_number(adj.birthday_days, detected["birthday_days"])
        taken_dates = "" if left else _picked_text(adj.taken_dates, detected["rest_dates"])
        flags = []
        varying = _varying_pay(record, person.slip_name)
        if varying:
            flags.append(VARYING_PAY_NOTE)
        elif missing_record:
            flags.append(NOT_IN_STAFF)
        elif left:
            flags.append(LEFT)
        elif not roster_name:
            flags.append(NO_ROSTER_NAME)
        if partial:
            flags.append(_partial_note(record, window, planned=planned is not None))
        if planned is not None and planned >= date.today() and not left:
            flags.append("未到最後工作日的更表，先按更表計算，不當作缺卡。")
        if fewer_rest:
            flags.append("上月有病假，本月休假少一天")
        if pending_absence:
            flags.append("缺勤未確認：" + "、".join(pending_absence))
        if employee_no in duplicate_ids:
            flags.append(f"{DUPLICATE} {employee_no}")
        if manual_case:
            flags.append(MANUAL_PAY[employee_no])
        elif not left:
            flags.extend(problem_lines(detected))
            reason = _bonus_reason(
                bonus_ok, partial, worst_late, detected, unpaid_days, sick_days, pending_absence,
            )
            override = _override(adj.bonus_override)
            if override is not None and reason:
                flags.append(
                    f"舊糧單有勤工獎 ${override:g}，但按規則應為 $0（{reason}），已沿用舊糧單金額。"
                )
            elif reason and bonus_ok and override is None and not bonus:
                flags.append(f"本月沒有勤工獎：{reason}")
            if leaving and prior_total and leaver_choice not in {"pay", "skip"}:
                detail = "、".join(f"{month}月 ${amount:g}" for month, amount in history if amount)
                flags.append(f"{detail} 已累積，未發放。請選擇發放或不發放。")
        if not left and _text(adj.note):
            note = chinese_note(_text(adj.note))
            if note and not any("勤工獎" in flag for flag in flags):
                flags.append(note)
        suggestion = "" if left or manual_case else suggest_ot(detected)
        if _text(staff_id) in early_ids or (employee_no and employee_no in early_numbers):
            flags.append(EARLY_NOTE)
        rows.append({
            "book": book,
            "period": "" if left else _period_text(info, window),
            "employee_no": employee_no,
            "staff_id": staff_id,
            "slip_name": _display_name(record, _text(person.slip_name)),
            "name_en": _text(record.get("name_en")) if record is not None else "",
            "name_zh": _text(record.get("name_zh")) if record is not None else "",
            "roster_name": roster_name,
            "department": _text(record.get("department")) if record is not None else "",
            "position": _text(record.get("position")) if record is not None else "",
            "join_date": "" if record is None else record.get("join_date"),
            "shops": detected["shops"],
            "roster_days": detected["roster_days"],
            "days_worked": detected["days_worked"],
            "missing_text": detected["missing_dates"],
            "late_text": detected["late_text"],
            "early_text": detected["early_text"],
            "wrong_text": detected["wrong_dates"],
            "day_off_text": detected["day_off_dates"],
            "leave_text": detected["leave_text"],
            "basic_salary": 0 if left else basic,
            "full_salary": 0 if left else full_basic,
            "counted_days": 0 if window is None else (window[1] - window[0]).days + 1,
            "month_days": days,
            "scheme": scheme,
            "rent": rent,
            "water": water,
            "electricity": electricity,
            "unpaid_days": unpaid_days,
            "unpaid_amount": unpaid,
            "salary_deduct_days": 0 if left else salary_deduct_days,
            "other_income": other_income,
            "leave_pay": leave_pay,
            "stated_extra": 0 if left else _num(adj.stated_extra),
            "ot_pay": ot_pay,
            "manual_delta": manual,
            "subtotal": subtotal,
            "mpf_employee": mpf_ee,
            "mpf_employer": mpf_er,
            "net": net,
            "bonus": bonus,
            "bonus_paid": bonus_paid,
            "bonus_history": "、".join(f"{month}月 ${amount:g}" for month, amount in history),
            "absence_pending": "、".join(pending_absence),
            "sick_hours": sick_hours,
            "allowance_desc": "" if left else _text(person.allowance_desc),
            "allowance_amount": 0 if left else _num(person.allowance_amount),
            "allowance_section": "" if left else _text(person.allowance_section),
            "allowance_note": "" if left else _text(person.allowance_note),
            "opening_rest": opening_rest,
            "rest_entitlement": entitlement,
            "statutory_days": statutory,
            "roster_rest_days": detected["rest_days"],
            "taken_rest": taken,
            "taken_dates": taken_dates,
            "unused_rest": unused,
            "unused_rest_calc": unused_calc,
            "sick_days": sick_days,
            "annual_taken": annual_taken,
            "birthday_days": birthday_days,
            "al_1_label": labels[0] if len(labels) > 0 else "",
            "al_1_days": closings[0] if len(closings) > 0 else "",
            "al_2_label": labels[1] if len(labels) > 1 else "",
            "al_2_days": closings[1] if len(closings) > 1 else "",
            "absent_days": 0 if left else _num(adj.absent_days),
            "absent_mins": 0 if left else _num(adj.absent_mins),
            "absent_text": "" if left else _absent_memo(adj, sick_hours),
            "late_mins_detected": 0 if left else detected["late_mins"],
            "early_mins_detected": 0 if left else detected["early_mins"],
            "ot_hours_detected": 0 if left else detected["ot_hours"],
            "ot_text": "" if left else _text(adj.ot_text),
            "ot_suggest": suggestion,
            "salary_reference": "" if left else _text(adj.get("salary_reference")),
            "ot_choice": "" if left else _text(adj.get("ot_choice")),
            "ot_hours_paid": "" if left or _is_blank(adj.get("ot_hours_paid")) else _num(adj.get("ot_hours_paid")),
            "bonus_override": "" if left or _is_blank(adj.bonus_override) else _num(adj.bonus_override),
            "note": "" if left else _text(adj.note),
            "missing_days": 0 if left else detected["missing_days"],
            "wrong_site_days": 0 if left else detected["wrong_days"],
            "roster_unpaid": detected["unpaid_days"],
            "roster_sick": detected["sick_days"],
            "roster_annual": detected["annual_days"],
            "roster_birthday": detected["birthday_days"],
            "roster_rest": detected["rest_days"],
            "roster_rest_dates": detected["rest_dates"],
            "review": "；".join(dict.fromkeys(flags)),
            "approved": "" if left else _text(adj.approved),
            "pay_this": include_in_month_pay(not left, staff_id, employee_no, early_ids, early_numbers),
            "show_on_review": True,
            "show_not_on_slip": False,
        })

    already_paid = paid_numbers()
    if book == "bg":
        for _, record in staff[employed & ~staff["part_time"]].iterrows():
            if record["employee_no"] in already_paid or _as_date(record.get("leave_date")) is not None:
                continue
            problem = MANUAL_PAY.get(record["employee_no"], NEW_JOINER)
            if record["employee_no"] in duplicate_ids:
                problem += f"；{DUPLICATE} {record['employee_no']}"
            row = _blank_row(_display_name(record, record["employee_no"]), "", problem)
            row["employee_no"] = record["employee_no"]
            row["department"] = _text(record.get("department"))
            row["position"] = _text(record.get("position"))
            row["join_date"] = record.get("join_date")
            row["name_en"] = _text(record.get("name_en"))
            row["name_zh"] = _text(record.get("name_zh"))
            row["show_on_review"] = True
            row["show_not_on_slip"] = False
            rows.append(row)

    part_time_names = set()
    if book == "bg":
        employed_pt = staff[employed & staff["part_time"]]
        for _, record in employed_pt.iterrows():
            name = _display_name(record, record["employee_no"])
            part_time_names.add(name)
            part_time_names.add(_text(record.get("name_zh")))
            row = _blank_row(name, "", PART_TIME)
            row["employee_no"] = record["employee_no"]
            rows.append(row)
        if facts is not None and not getattr(facts, "empty", True) and len(employed_pt) and "name" in facts.columns:
            from payroll.pay.part_time import link_facts
            linked = link_facts(employed_pt.to_dict("records"), facts["name"].astype(str).unique())
            for names in linked.values():
                part_time_names.update(names)

    if book == "bg" and facts is not None and not facts.empty:
        known_rosters = _roster_names_on_payroll()
        for name in sorted(set(facts["name"].astype(str)) - matched_names):
            if name in part_time_names or name in known_rosters:
                continue
            detected = summaries.get(name, empty_summary())
            row = _blank_row(name, detected["shops"], NOT_LINKED, name)
            row["roster_days"] = detected["roster_days"]
            row["days_worked"] = detected["days_worked"]
            row["missing_text"] = detected["missing_dates"]
            row["late_text"] = detected["late_text"]
            row["review"] = "; ".join(
                part for part in [NOT_LINKED, *problem_lines(detected)] if part
            )
            row["late_mins_detected"] = detected["late_mins"]
            row["missing_days"] = detected["missing_days"]
            row["wrong_site_days"] = detected["wrong_days"]
            rows.append(row)

    draft = pd.DataFrame(rows)
    info["system"].mkdir(parents=True, exist_ok=True)
    day_rows.to_excel(info["system"] / "days.xlsx", index=False)
    meta.to_excel(info["system"] / "pay_meta.xlsx", index=False)
    return draft


def write_closing(info, draft):
    people = draft[draft["pay_this"].astype(bool)]
    rows = []
    for _, row in people.iterrows():
        rows.append({
            "staff_id": row.staff_id,
            "employee_no": row.employee_no,
            "slip_name": row.slip_name,
            "opening_rest": row.unused_rest,
            "had_sick": 0 if info.get("book") == "admin" else (1 if _num(row.sick_days) > 0 else 0),
            "bonus_earned": _num(row.bonus),
            "opening_ot_hours": 0,
            "al_1_label": row.al_1_label,
            "al_1_opening": row.al_1_days,
            "al_2_label": row.al_2_label,
            "al_2_opening": row.al_2_days,
        })
    suffix = info.get("balance_suffix", "")
    path = home() / "data" / "balances" / f"{info['key'].replace('-', '_')}_close{suffix}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(path, index=False)
    return path
