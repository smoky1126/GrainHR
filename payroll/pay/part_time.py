"""Part-time pay. Hours come from the roster shift, not the full-time salary.

The two part-time companies are paid separately. Each has its own transaction number.
Employer MPF is 5% of pay when the person is on MPF, including pay under $7,100
and the first 60 days. Employee MPF starts once 60 days are complete, and only
when pay is at least $7,100. Overtime is not added. A day of 休假 is not a shift.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import os
import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from payroll.core.config import MPF_MAX_INCOME, MPF_MIN_INCOME, MPF_RATE
from payroll.core.labels import SCHEME_STORED
from payroll.core.settings import match_tokens, part_time_books
from payroll.core.names import chinese
from payroll.staff.staff import _as_date, _text, employed_in

PT_BOOKS = part_time_books()
PT_COLUMNS = [
    "employee_no", "rate", "scheme", "extra_hours", "extra_note",
    "bank", "account", "pay_this",
]
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
_PT_TAIL = re.compile(r"\s*[\(（]\s*PT\s*[\)）]\s*$", re.I)
_PT_SAME = str.maketrans({"鈴": "玲"})
_CENT = Decimal("0.01")


def pt_path(info):
    return info["system"] / "pay_table_pt.xlsx"


def pt_company(record):
    text = f"{_text(record.get('department'))} {_text(record.get('position'))}"
    if any(token and token in text for token in match_tokens()) or re.search(r"(^|[^A-Za-z])MD([^A-Za-z]|$)", text):
        return "md"
    return "bg"


def excel_money(value):
    return float(Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))


def shift_hours(roster):
    text = _text(roster)
    total = Decimal("0")
    for match in _TIME.finditer(text):
        start = int(match.group(1)) * 60 + int(match.group(2))
        end = int(match.group(3)) * 60 + int(match.group(4))
        if end <= start:
            end += 24 * 60
        total += Decimal(end - start) / Decimal(60)
    return total


def _zh(text):
    return chinese(text).translate(_PT_SAME)


def _strip_pt(name):
    return _PT_TAIL.sub("", _text(name)).strip()


def link_facts(people, fact_names):
    """Which roster names belong to each part-time employee."""
    assigned = {_text(person.get("employee_no")): [] for person in people}
    for fact in fact_names:
        key = _strip_pt(fact)
        if not key:
            continue
        zh_hits = [person for person in people if _zh(person.get("name_zh")) and _zh(person.get("name_zh")) == _zh(key)]
        if len(zh_hits) == 1:
            assigned[_text(zh_hits[0].get("employee_no"))].append(str(fact))
            continue
        if len(zh_hits) > 1:
            continue
        hint_hits = []
        for person in people:
            hint = _text(person.get("roster_hint"))
            if hint and hint.lower() == key.lower():
                hint_hits.append(person)
        chosen = hint_hits
        if len(hint_hits) > 1:
            named = [person for person in hint_hits if _text(person.get("department"))]
            chosen = named if len(named) == 1 else []
        if len(chosen) == 1:
            assigned[_text(chosen[0].get("employee_no"))].append(str(fact))
    return assigned


def _blank_store():
    lines = pd.DataFrame(columns=PT_COLUMNS)
    meta = pd.DataFrame([{"bg_reference": "", "md_reference": ""}])
    return lines, meta


def load_pt(info):
    path = pt_path(info)
    if not path.exists():
        return _blank_store()
    try:
        lines = pd.read_excel(path, sheet_name="lines", engine="openpyxl")
    except ValueError:
        lines = pd.DataFrame(columns=PT_COLUMNS)
    try:
        meta = pd.read_excel(path, sheet_name="meta", engine="openpyxl")
    except ValueError:
        meta = pd.DataFrame([{"bg_reference": "", "md_reference": ""}])
    for column in PT_COLUMNS:
        if column not in lines.columns:
            lines[column] = "" if column in {"employee_no", "scheme", "extra_note", "bank", "account", "pay_this"} else 0
    if meta.empty:
        meta = pd.DataFrame([{"bg_reference": "", "md_reference": ""}])
    for column in ("bg_reference", "md_reference"):
        if column not in meta.columns:
            meta[column] = ""
    return lines, meta


def _write_pt(info, lines, meta):
    path = pt_path(info)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.stem + "._new.xlsx")
    with pd.ExcelWriter(temp, engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)
    try:
        os.replace(temp, path)
    except PermissionError as error:
        raise SystemExit(f"請先關閉 Excel 中的 {path.name}，然後再儲存。") from error


def save_pt_lines(info, records):
    lines, meta = load_pt(info)
    stored = {_text(row.get("employee_no")): row for row in lines.to_dict("records")}
    for record in records:
        number = _text(record.get("employee_no"))
        if not number:
            continue
        scheme = SCHEME_STORED.get(_text(record.get("scheme")), _text(record.get("scheme")) or "mpf")
        if scheme not in {"mpf", "none"}:
            scheme = "mpf"
        pay_this = _text(record.get("pay_this"))
        stored[number] = {
            "employee_no": number,
            "rate": _num(record.get("rate"), 60),
            "scheme": scheme,
            "extra_hours": _num(record.get("extra_hours"), 0),
            "extra_note": _text(record.get("extra_note")),
            "bank": _text(record.get("bank")),
            "account": _text(record.get("account")),
            "pay_this": "N" if pay_this in {"N", "否"} else "Y",
        }
    _write_pt(info, pd.DataFrame(list(stored.values()), columns=PT_COLUMNS), meta)


def pt_reference(info, company):
    _lines, meta = load_pt(info)
    value = meta.iloc[0].get(f"{company}_reference")
    return _text(value)


def set_pt_reference(info, company, value):
    lines, meta = load_pt(info)
    column = f"{company}_reference"
    meta[column] = meta[column].astype(object)
    meta.loc[0, column] = _text(value)
    _write_pt(info, lines, meta)


def _num(value, default):
    text = _text(value)
    if text == "":
        return float(default)
    try:
        return float(text)
    except ValueError:
        return float(default)


def _load_facts(info, facts):
    if facts is not None:
        return facts
    path = info["system"] / "daily_facts.xlsx"
    if not path.exists():
        return pd.DataFrame(columns=["name", "date", "roster"])
    return pd.read_excel(path, engine="openpyxl")


def _hours_by_day(facts, names, year, month):
    days = {}
    if facts is None or facts.empty or not names or "name" not in facts.columns:
        return days
    wanted = set(names)
    subset = facts[facts["name"].astype(str).isin(wanted)]
    for _, row in subset.iterrows():
        when = _as_date(row.get("date"))
        if when is None or when.year != year or when.month != month:
            continue
        amount = shift_hours(row.get("roster"))
        if amount == 0:
            continue
        days[when.day] = days.get(when.day, Decimal("0")) + amount
    return days


def _employee_due(join_date, info):
    joined = _as_date(join_date)
    if joined is None:
        return True
    end = date(info["year"], info["month"], info["days"])
    return (end - joined).days + 1 >= 60


def _mpf(salary, scheme, employee_due):
    if scheme != "mpf" or salary <= 0:
        return 0.0, 0.0
    capped = min(Decimal(str(salary)), Decimal(str(MPF_MAX_INCOME)))
    employer = excel_money(capped * Decimal(str(MPF_RATE)))
    if not employee_due or salary < MPF_MIN_INCOME:
        return employer, 0.0
    return employer, excel_money(capped * Decimal(str(MPF_RATE)))


def _shop_label(department, company):
    if company == "md":
        return "SPK_MD"
    text = _text(department)
    if not text:
        return ""
    return text.split("-")[0].strip().split()[0]


def build_pt(info, staff, facts=None, lines=None):
    """One row per part-time person employed this month."""
    facts = _load_facts(info, facts)
    if lines is None:
        lines, _meta = load_pt(info)
    saved = {_text(row.get("employee_no")): row for row in lines.to_dict("records")}
    people = staff[employed_in(staff, info) & staff["part_time"]].to_dict("records")
    fact_names = [] if facts is None or facts.empty or "name" not in facts.columns else facts["name"].astype(str).unique()
    linked = link_facts(people, fact_names)
    rows = []
    for person in people:
        number = _text(person.get("employee_no"))
        company = pt_company(person)
        stored = saved.get(number, {})
        scheme = SCHEME_STORED.get(_text(stored.get("scheme")), _text(stored.get("scheme")) or "mpf")
        if scheme not in {"mpf", "none"}:
            scheme = "mpf"
        rate = Decimal(str(_num(stored.get("rate"), 60)))
        extra = Decimal(str(_num(stored.get("extra_hours"), 0)))
        pay = _text(stored.get("pay_this")) != "N"
        days = _hours_by_day(facts, linked.get(number, []), info["year"], info["month"])
        hours = sum(days.values(), Decimal("0"))
        total_hours = hours + extra
        if total_hours < 0:
            total_hours = Decimal("0")
        salary = excel_money(total_hours * rate) if pay else 0.0
        employer, employee = _mpf(salary, scheme, _employee_due(person.get("join_date"), info)) if pay else (0.0, 0.0)
        transfer = excel_money(Decimal(str(salary)) - Decimal(str(employee)))
        rows.append({
            "employee_no": number,
            "company": company,
            "name_zh": _text(person.get("name_zh")),
            "name_en": _text(person.get("name_en")),
            "hint": _text(person.get("roster_hint")),
            "department": _text(person.get("department")),
            "shop": _shop_label(person.get("department"), company),
            "join_date": _as_date(person.get("join_date")),
            "hours": float(hours),
            "total_hours": float(total_hours),
            "extra_hours": float(extra),
            "extra_note": _text(stored.get("extra_note")),
            "rate": float(rate),
            "scheme": scheme,
            "pay_this": "Y" if pay else "N",
            "salary": salary,
            "employer_mpf": employer,
            "employee_mpf": employee,
            "transfer": transfer,
            "bank": _text(stored.get("bank")),
            "account": _text(stored.get("account")),
            "days": {day: float(amount) for day, amount in days.items()},
        })
    rows.sort(key=lambda row: (row["company"], row["name_en"] or row["name_zh"], row["employee_no"]))
    return rows


def _header(row):
    en = row["name_en"] or row["name_zh"]
    nick = row["hint"]
    shop = row["shop"]
    zh = row["name_zh"]
    first = en
    if zh and zh not in first:
        first = f"{first}\n{zh}"
    if nick and nick.lower() not in first.lower():
        first = f"{first}\n{nick}"
    if shop:
        first = f"{first} ({shop})"
    joined = row["join_date"]
    if joined is not None:
        first += f"\n入職日期:{joined.day}/{joined.month}/{joined.year}"
    if row["pay_this"] != "Y":
        first += "\n不出糧"
    return first


def summary_book(info, company, rows, reference):
    """The same shape as the October #244 summary: one column per person."""
    book = Workbook()
    sheet = book.active
    sheet.title = "PT"
    title = "BG Part-time" if company == "bg" else "MD Part-time"
    people = [row for row in rows if row["company"] == company]
    sheet["A1"] = title
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"] = f"交易編號：{reference}" if reference else "交易編號："
    sheet.cell(3, 3, f"{info['month']}月份/{info['year']}")
    for index, row in enumerate(people):
        cell = sheet.cell(3, 4 + index, _header(row))
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        for day in range(1, 32):
            sheet.cell(3 + day, 3, day)
            amount = row["days"].get(day)
            if amount:
                sheet.cell(3 + day, 4 + index, amount)
        sheet.cell(35, 4 + index, row["extra_hours"] or None)
        sheet.cell(36, 4 + index, row["extra_note"] or None)
        sheet.cell(37, 4 + index, row["total_hours"])
        sheet.cell(38, 4 + index, row["rate"])
        sheet.cell(39, 4 + index, row["salary"])
        sheet.cell(40, 4 + index, row["employer_mpf"])
        sheet.cell(41, 4 + index, row["employee_mpf"])
        sheet.cell(42, 4 + index, row["transfer"])
        sheet.cell(43, 4 + index, row["bank"] or None)
        sheet.cell(44, 4 + index, row["account"] or None)
    labels = {
        35: "其他時數", 36: "備註", 37: "總時數", 38: "時薪", 39: "薪金",
        40: "僱主強積金(5%)", 41: "僱員強積金(5%)", 42: "過數金額", 43: "銀行", 44: "戶口",
    }
    for excel_row, label in labels.items():
        sheet.cell(excel_row, 3, label)
    sheet.column_dimensions["C"].width = 18
    for index in range(len(people)):
        sheet.column_dimensions[sheet.cell(3, 4 + index).column_letter].width = 22
    sheet.row_dimensions[3].height = 48
    sheet.freeze_panes = "D4"
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def summary_name(info, company):
    token = info.get("month_token") or str(info["month"])
    prefix = "BG" if company == "bg" else "MD"
    return f"{prefix} PT Summary_{token}_{info['year']}.xlsx"
