"""A read-only staff master: employment, pay, leave, and the staff-file record.

Salary comes from the pay tables. Annual leave still to take, and unused rest,
come from the month's closing balance, or the opening balance when the slips
are not made yet. Annual leave already taken this year comes from the Staff
Holiday Record in the accounting folder.
"""

import calendar
import re
from datetime import date, timedelta

import pandas as pd

from payroll.core.config import book_info, home, opening_balance_path
from payroll.core.labels import BOOKS
from payroll.core.settings import groups as group_rows
from payroll.staff.leave_record import annual_leave_taken
from payroll.staff.staff import _as_date, _text, pay_table_path

GROUPS = group_rows()
GROUP_LABEL = dict(GROUPS)


def _optional_number(value):
    text = _text(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date_text(value):
    found = _as_date(value)
    if found is None:
        return ""
    return f"{found.year}-{found.month:02d}-{found.day:02d}"


def _balance_path(info, book):
    suffix = "" if book == "bg" else f"_{book}"
    key = str(info["key"]).replace("-", "_")
    close = home() / "data" / "balances" / f"{key}_close{suffix}.xlsx"
    if close.exists():
        return close
    return opening_balance_path(book_info(info, book))


def _blank_pay():
    return {"salary": None, "book": "", "book_key": "", "annual": None, "annual_detail": "", "rest": None}


def _short_leave_label(label):
    text = _text(label).rstrip(":：").strip()
    if not text:
        return ""
    if "合約" in text:
        return re.sub(r"未使用年假", "", text).strip()
    year = re.search(r"20\d{2}", text)
    return year.group(0) if year else text


def _annual(row):
    parts = []
    total = None
    for index in (1, 2):
        days = _optional_number(row.get(f"al_{index}_opening"))
        label = _short_leave_label(row.get(f"al_{index}_label"))
        if days is None and not label:
            continue
        if days is not None:
            total = days if total is None else total + days
        shown = "" if days is None else f"{days:g}"
        parts.append(f"{label} {shown}".strip() if label else shown)
    return total, "、".join(part for part in parts if part)


def _pay_and_leave(info):
    """Join each payroll's pay table to that same payroll's balance file."""
    found = {}
    for book, label in BOOKS.items():
        path = pay_table_path(book)
        if not path.exists():
            continue
        table = pd.read_excel(path, engine="openpyxl")
        numbers = {}
        for _, row in table.iterrows():
            number = _text(row.get("employee_no"))
            if not number or number.lower() == "nan" or number in found:
                continue
            numbers[_text(row.get("staff_id"))] = number
            found[number] = _blank_pay()
            found[number]["salary"] = _optional_number(row.get("basic_salary"))
            found[number]["book"] = label
            found[number]["book_key"] = book
        balance_path = _balance_path(info, book)
        if balance_path is None or not balance_path.exists():
            continue
        frame = pd.read_excel(balance_path, engine="openpyxl")
        for _, row in frame.iterrows():
            number = numbers.get(_text(row.get("staff_id")))
            if not number:
                continue
            annual, detail = _annual(row)
            found[number]["annual"] = annual
            found[number]["annual_detail"] = detail
            found[number]["rest"] = _optional_number(row.get("opening_rest"))
    return found


def staff_group(department, employment, position, sheet=""):
    """Which staff list this person belongs to. Mainland workers are split by company."""
    from payroll.core.settings import match_tokens

    dept = _text(department)
    job = _text(position)
    part_time = "兼職" in _text(employment)
    second = any(token and token in dept for token in match_tokens())
    if _text(sheet) == "內地勞工":
        return "md_esl" if second else "bg_esl"
    if part_time:
        return "md_pt" if second else "bg_pt"
    if "Office" in dept or "Administration" in dept:
        return "admin"
    if second:
        return "md_ft"
    if "Retail" in dept:
        return "bg_retail"
    if "Bread" in dept or "Baker" in job or "麵包" in job:
        return "bg_prod"
    return ""


def service_until(join_value, leave_value, year, month):
    """Years, months, and days from the join date to this month, or to the leave date."""
    joined = _as_date(join_value)
    if joined is None:
        return "", None
    left = _as_date(leave_value)
    month_end = calendar.monthrange(int(year), int(month))[1]
    end = date(int(year), int(month), month_end)
    if left is not None and left < end:
        end = left
    if end < joined:
        return "0年0個月", "0年0個月0日"
    years = end.year - joined.year
    months = end.month - joined.month
    day_part = end.day - joined.day
    if day_part < 0:
        months -= 1
        previous = end.replace(day=1) - timedelta(days=1)
        day_part += previous.day
    if months < 0:
        years -= 1
        months += 12
    return f"{years}年{months}個月", f"{years}年{months}個月{day_part}日"


def annual_entitlement(join_value, leave_value, year, month):
    """Annual leave for the year of service they are in. First year 10, second 12, then 14."""
    joined = _as_date(join_value)
    if joined is None:
        return None
    left = _as_date(leave_value)
    month_end = calendar.monthrange(int(year), int(month))[1]
    end = date(int(year), int(month), month_end)
    if left is not None and left < end:
        end = left
    if end < joined:
        return 0
    completed = end.year - joined.year
    if (end.month, end.day) < (joined.month, joined.day):
        completed -= 1
    if completed >= 2:
        return 14
    if completed == 1:
        return 12
    return 10


def _status(record):
    status = _text(record.get("status"))
    if status == "已離職":
        return "已離職"
    if status in {"", "在職"}:
        return "在職"
    return status or "在職"


def _person_text(record, key):
    return _text(record.get(key)) if hasattr(record, "get") else ""


def _hourly_rates(info):
    from payroll.pay.part_time import load_pt
    lines, _meta = load_pt(info)
    rates = {}
    for _, row in lines.iterrows():
        number = _text(row.get("employee_no"))
        if number and number.lower() != "nan":
            rates[number] = _optional_number(row.get("rate"))
    return rates


def staff_directory(info, staff):
    """One row per staff-file record, including people who have left."""
    pay = _pay_and_leave(info)
    rates = _hourly_rates(info)
    taken, leave_through = annual_leave_taken(staff, info["year"], info["month"])
    rows = []
    for _, record in staff.iterrows():
        number = _text(record.get("employee_no"))
        if not number or number.lower() == "nan":
            continue
        paid = pay.get(number, _blank_pay())
        chinese_name = _text(record.get("name_zh"))
        english_name = _text(record.get("name_en"))
        name = " ".join(part for part in (chinese_name, english_name) if part)
        group = staff_group(
            record.get("department"), record.get("employment"), record.get("position"), record.get("sheet"),
        )
        years, days = service_until(record.get("join_date"), record.get("leave_date"), info["year"], info["month"])
        hourly = "兼職" in _text(record.get("employment"))
        salary = paid.get("salary")
        if salary is None and hourly:
            salary = rates.get(number)
        rows.append({
            "employee_no": number,
            "name": name or number,
            "name_zh": chinese_name,
            "name_en": english_name,
            "roster_hint": _text(record.get("roster_hint")),
            "status": _status(record),
            "group": group,
            "group_label": GROUP_LABEL.get(group, "未分類"),
            "sheet": _text(record.get("sheet")),
            "position": _text(record.get("position")),
            "department": _text(record.get("department")),
            "employment": _text(record.get("employment")),
            "join_date": _date_text(record.get("join_date")),
            "leave_date": _date_text(record.get("leave_date")),
            "service": years,
            "service_days": days,
            "book": paid.get("book", ""),
            "book_key": paid.get("book_key", ""),
            "salary": salary,
            "pay_basis": "時薪" if hourly else "月薪",
            "annual_entitled": annual_entitlement(
                record.get("join_date"), record.get("leave_date"), info["year"], info["month"],
            ),
            "annual": paid.get("annual"),
            "annual_detail": paid.get("annual_detail", ""),
            "annual_taken": taken.get(number),
            "leave_through": leave_through,
            "rest": paid.get("rest"),
            "gender": _person_text(record, "gender"),
            "birth_date": _date_text(record.get("birth_date")),
            "marital": _person_text(record, "marital"),
            "phone": _person_text(record, "phone"),
            "address": _person_text(record, "address"),
            "hkid": _person_text(record, "hkid"),
            "bank_name": _person_text(record, "bank_name"),
            "bank_account": _person_text(record, "bank_account"),
            "emergency_name": _person_text(record, "emergency_name"),
            "emergency_relation": _person_text(record, "emergency_relation"),
            "emergency_phone": _person_text(record, "emergency_phone"),
            "emergency_name_2": _person_text(record, "emergency_name_2"),
            "emergency_relation_2": _person_text(record, "emergency_relation_2"),
            "emergency_phone_2": _person_text(record, "emergency_phone_2"),
            "contract_end": _date_text(record.get("contract_end")),
            "contract_no": _person_text(record, "contract_no"),
            "permit_address": _person_text(record, "permit_address"),
        })
    rows.sort(key=lambda row: (row["status"] != "在職", row["group_label"], row["employee_no"]))
    return rows
