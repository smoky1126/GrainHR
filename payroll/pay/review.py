"""The Review workbook HR staff edit, and the read-back into adjustments."""

import pandas as pd
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.filters import CustomFilter, CustomFilters, FilterColumn

from payroll.core.labels import (
    DAY_HEADINGS, OT, OT_STORED, PAY_HEADINGS, RENT_BASE, RENT_BASE_STORED,
    REVIEW_HEADINGS, SCHEME, SCHEME_STORED, SECTION, SECTION_STORED, VIEW_ONLY,
    YES, YES_STORED, column_key, show, store,
)

# key, heading, editable, note shown on the heading
REVIEW_COLUMNS = [
    ("employee_no", "Staff no", False, ""),
    ("slip_name", "Name", False, ""),
    ("roster_days", "Rosters", False, "Days the roster assigns this person, per shop."),
    ("days_worked", "Days worked", False, "Days DAKA shows a clock-in and a clock-out on a shift."),
    ("missing_text", "Missing punches", False, "Shift on the roster, and DAKA has no matching punch."),
    ("late_text", "Late", False, ""),
    ("early_text", "Early leave", False, ""),
    ("wrong_text", "Wrong shop", False, "DAKA place is not the roster shop."),
    ("day_off_text", "Worked on day off", False, "Roster says leave, but DAKA shows a punch."),
    ("leave_text", "Leave from roster", False, ""),
    ("ot_hours_detected", "Overtime hours", False, "From DAKA compared with the roster end time."),
    ("review", "Problem", False, ""),
    ("basic_salary", "Basic salary", False, ""),
    ("net", "Net pay", False, ""),
    ("mpf_employee", "MPF", False, ""),
    ("bonus", "Attendance bonus", False, ""),
    ("unused_rest", "Unused rest days", False, ""),
    ("approved", "Approve", True, "Y pays this person. N holds them back."),
    ("ot_choice", "Overtime", True, "Pay adds hours x basic / days / 9.5. Exchange only shows the hours."),
    ("ot_hours_paid", "Overtime hours paid", True, "Blank means all of the overtime hours."),
    ("unpaid_days", "Unpaid days", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("sick_days", "Sick days", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("annual_taken", "Annual leave days", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("birthday_days", "Birthday leave", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("taken_rest", "Rest days taken", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("taken_dates", "Rest dates", True, "Filled from the roster. Change it only when the roster is wrong."),
    ("statutory_days", "Statutory days", True, "Official holiday count for this month. A typed number replaces it. Shop and production add it to unused rest days."),
    ("ot_text", "Overtime note", True, "Prints on the slip."),
    ("bonus_override", "Bonus override", True, "Blank means the $1,000 rule."),
    ("manual_delta", "Extra adjustment", True, "Plus or minus when the total needs a manual fix."),
    ("note", "Note", True, ""),
    ("roster_unpaid", "Roster unpaid", False, ""),
    ("roster_sick", "Roster sick", False, ""),
    ("roster_annual", "Roster annual", False, ""),
    ("roster_birthday", "Roster birthday", False, ""),
    ("roster_rest", "Roster rest", False, ""),
    ("roster_rest_dates", "Roster rest dates", False, ""),
    ("staff_id", "Staff id", False, ""),
]

EDITABLE = {
    "approved", "ot_choice", "ot_hours_paid", "unpaid_days", "sick_days",
    "statutory_days", "annual_taken", "birthday_days", "taken_rest", "taken_dates",
    "ot_text", "bonus_override", "manual_delta", "note", "salary_reference",
    "absence_choices", "sick_hours", "bonus_leaver",
}
NUMBER_FIELDS = {
    "unpaid_days", "sick_days", "statutory_days", "annual_taken",
    "birthday_days", "taken_rest", "manual_delta",
}
BLANK_NUMBER_FIELDS = {"ot_hours_paid", "bonus_override"}
ROSTER_FIELDS = {
    "unpaid_days": "roster_unpaid",
    "sick_days": "roster_sick",
    "annual_taken": "roster_annual",
    "birthday_days": "roster_birthday",
    "taken_rest": "roster_rest",
    "taken_dates": "roster_rest_dates",
}
HIDDEN = set(ROSTER_FIELDS.values()) | {"staff_id"}
WRAP = {
    "roster_days", "missing_text", "late_text", "early_text", "wrong_text",
    "day_off_text", "leave_text", "review", "taken_dates", "ot_text", "note",
}

GREY = PatternFill("solid", fgColor="D9D9D9")
BLUE = PatternFill("solid", fgColor="BDD7EE")
HEADER = Font(bold=True)
UNLOCKED = Protection(locked=False)
LOCKED = Protection(locked=True)


def _blank(value):
    if isinstance(value, bool):
        return False
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip() == ""


def _cell_value(key, value):
    if _blank(value):
        return None
    if key in NUMBER_FIELDS or key in BLANK_NUMBER_FIELDS or key in {
        "basic_salary", "late_mins_detected", "missing_days", "wrong_site_days",
        "net", "mpf_employee", "bonus", "unused_rest",
    }:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        if number == int(number) and key not in {"net", "mpf_employee", "basic_salary", "bonus"}:
            return int(number)
        return number
    if key == "approved":
        return show(YES, value)
    if key == "ot_choice":
        return show(OT, value)
    return value


PAY_SHEET_COLUMNS = [
    ("employee_no", "Staff no", False, ""),
    ("slip_name", "Name", False, ""),
    ("problem", "Problem", False, ""),
    ("roster_name", "Roster name", True, "The name on the shop roster."),
    ("basic_salary", "Basic salary", True, ""),
    ("scheme", "Scheme", True, "mpf, rent, or none."),
    ("rent_amount", "Rent", True, "Exact rent for mainland staff. Blank keeps the old percentage."),
    ("water", "Water", True, "Mainland staff only."),
    ("electricity", "Electricity", True, "Mainland staff only."),
    ("bonus_eligible", "Attendance bonus", True, "Y can receive the $1,000 bonus. N cannot."),
    ("rest_days_month", "Rest days per month", True, ""),
    ("allowance_desc", "Allowance description", True, ""),
    ("transport_amount", "Transport", True, ""),
    ("health_amount", "Health", True, ""),
    ("allowance_section", "Allowance section", True, "shop or office."),
    ("allowance_note", "Allowance note", True, ""),
]
PAY_EDITABLE = {key for key, heading, editable, note in PAY_SHEET_COLUMNS if editable}
PAY_DATE_CELL = "B7"


def write_workbook(path, draft, days=None, pay_date="", pay_rows=None):
    book = Workbook()
    _start_here(book.active, pay_date)
    review = book.create_sheet("審核")
    pay = book.create_sheet("薪金")
    other = book.create_sheet("不在糧單")
    evidence = book.create_sheet("每日紀錄")
    figures = book.create_sheet("全部數字")
    _write_review(review, draft[draft["show_on_review"]])
    _write_pay(pay, pay_rows if pay_rows is not None else draft.iloc[0:0])
    _write_not_on_slip(other, draft[draft["show_not_on_slip"]])
    _write_days(evidence, days)
    _write_figures(figures, draft)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def _start_here(sheet, pay_date):
    sheet.title = "開始"
    lines = [
        VIEW_ONLY,
        "這份 Excel 只供查看。請在薪酬系統裡修改。",
        "出糧日期會印在糧單上。",
        "審核頁是出勤報告。薪金頁是薪金同津貼。",
        "每日紀錄是每一日的更表同打卡。",
    ]
    for index, line in enumerate(lines, start=1):
        sheet.cell(index, 1, line)
    label = sheet.cell(7, 1, "出糧日期")
    label.font = HEADER
    label.fill = GREY
    label.protection = LOCKED
    cell = sheet.cell(7, 2, pay_date or None)
    cell.fill = GREY
    cell.protection = LOCKED
    cell.number_format = "@"
    sheet.column_dimensions["A"].width = 120
    sheet.column_dimensions["B"].width = 22
    sheet.sheet_view.showGridLines = False
    _protect(sheet)


def _write_review(sheet, rows):
    for col, (key, heading, editable, note) in enumerate(REVIEW_COLUMNS, start=1):
        cell = sheet.cell(1, col, REVIEW_HEADINGS.get(key, heading))
        cell.font = HEADER
        cell.fill = BLUE if editable else GREY
        cell.protection = LOCKED
        if note:
            cell.comment = Comment(note, "payroll")
        sheet.column_dimensions[get_column_letter(col)].width = 18 if key in WRAP else max(14, len(heading) + 2)
    sheet.column_dimensions["B"].width = 28
    for key in WRAP:
        letter = get_column_letter(next(index for index, column in enumerate(REVIEW_COLUMNS) if column[0] == key) + 1)
        sheet.column_dimensions[letter].width = 36
    for row_index in range(2, len(rows) + 2):
        source = rows.iloc[row_index - 2]
        for col, (key, heading, editable, note) in enumerate(REVIEW_COLUMNS, start=1):
            cell = sheet.cell(row_index, col, _cell_value(key, source[key] if key in source else None))
            cell.fill = GREY
            cell.protection = LOCKED
            cell.alignment = Alignment(wrap_text=key in WRAP)
    last_row = max(2, sheet.max_row)
    last_col = get_column_letter(len(REVIEW_COLUMNS))
    sheet.auto_filter.ref = f"A1:{last_col}{last_row}"
    sheet.freeze_panes = "C2"
    problem_col = next(index for index, column in enumerate(REVIEW_COLUMNS) if column[0] == "review")
    sheet.auto_filter.filterColumn.append(
        FilterColumn(
            colId=problem_col,
            customFilters=CustomFilters(customFilter=[CustomFilter(operator="notEqual", val="")]),
        )
    )
    for index, (key, heading, editable, note) in enumerate(REVIEW_COLUMNS):
        if key in HIDDEN:
            sheet.column_dimensions[get_column_letter(index + 1)].hidden = True
    _protect(sheet)


def _list_validation(sheet, key, formula, title, error, last_row, columns=None):
    columns = columns or REVIEW_COLUMNS
    column = get_column_letter(next(index for index, item in enumerate(columns) if item[0] == key) + 1)
    check = DataValidation(type="list", formula1=formula, allow_blank=True)
    check.error = error
    check.errorTitle = title
    check.add(f"{column}2:{column}{last_row}")
    sheet.add_data_validation(check)


def _write_pay(sheet, rows):
    for col, (key, heading, editable, note) in enumerate(PAY_SHEET_COLUMNS, start=1):
        cell = sheet.cell(1, col, PAY_HEADINGS.get(key, heading))
        cell.font = HEADER
        cell.fill = GREY
        cell.protection = LOCKED
        if note:
            cell.comment = Comment(note, "payroll")
        sheet.column_dimensions[get_column_letter(col)].width = 24 if editable else 18
    sheet.column_dimensions["B"].width = 32
    if rows is not None and len(rows):
        for row_index, (_, source) in enumerate(rows.iterrows(), start=2):
            for col, (key, heading, editable, note) in enumerate(PAY_SHEET_COLUMNS, start=1):
                cell = sheet.cell(row_index, col, _pay_cell(key, source.get(key)))
                cell.fill = GREY
                cell.protection = LOCKED
    last_row = max(2, sheet.max_row)
    last_col = get_column_letter(len(PAY_SHEET_COLUMNS))
    sheet.auto_filter.ref = f"A1:{last_col}{last_row}"
    sheet.freeze_panes = "D2"
    _protect(sheet)


def _pay_cell(key, value):
    if _blank(value):
        return None
    if key == "bonus_eligible":
        text = str(value).strip().upper()
        if text in YES or text in YES_STORED:
            return show(YES, store(YES_STORED, text))
        try:
            return "是" if float(value) else "否"
        except (TypeError, ValueError):
            return None
    if key == "scheme":
        return show(SCHEME, value)
    if key == "rent_base":
        return show(RENT_BASE, value)
    if key == "allowance_section":
        return show(SECTION, value)
    if key in {"basic_salary", "rent_rate", "water", "rest_days_month", "allowance_amount"}:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        if number == int(number) and key != "rent_rate":
            return int(number)
        return number
    return value


def _write_not_on_slip(sheet, rows):
    headers = ["姓名", "店鋪", "問題"]
    for col, heading in enumerate(headers, start=1):
        cell = sheet.cell(1, col, heading)
        cell.font = HEADER
        cell.fill = GREY
    for row_index, (_, source) in enumerate(rows.iterrows(), start=2):
        sheet.cell(row_index, 1, source["slip_name"]).fill = GREY
        sheet.cell(row_index, 2, source["shops"]).fill = GREY
        sheet.cell(row_index, 3, source["review"]).fill = GREY
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["C"].width = 42
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:C{max(1, sheet.max_row)}"
    _protect(sheet)


def _write_days(sheet, days):
    headers = [
        "Name", "Date", "Rosters", "Chosen shop", "Roster cell",
        "DAKA in", "DAKA out", "DAKA place", "Status",
    ]
    for col, heading in enumerate(headers, start=1):
        cell = sheet.cell(1, col, DAY_HEADINGS.get(heading, heading))
        cell.font = HEADER
        cell.fill = GREY
    if days is not None and len(days):
        for row_index, (_, source) in enumerate(days.iterrows(), start=2):
            for col, heading in enumerate(headers, start=1):
                value = source[heading] if heading in source else None
                cell = sheet.cell(row_index, col, None if _blank(value) else value)
                cell.fill = GREY
                cell.protection = LOCKED
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["C"].width = 42
    sheet.column_dimensions["E"].width = 22
    sheet.freeze_panes = "A2"
    last_col = get_column_letter(len(headers))
    sheet.auto_filter.ref = f"A1:{last_col}{max(1, sheet.max_row)}"
    _protect(sheet)


def _write_figures(sheet, draft):
    columns = list(draft.columns)
    for col, name in enumerate(columns, start=1):
        cell = sheet.cell(1, col, REVIEW_HEADINGS.get(name) or PAY_HEADINGS.get(name) or name)
        cell.font = HEADER
        cell.fill = GREY
    for row_index, (_, source) in enumerate(draft.iterrows(), start=2):
        for col, name in enumerate(columns, start=1):
            value = source[name]
            if _blank(value):
                value = None
            elif hasattr(value, "item"):
                try:
                    value = value.item()
                except ValueError:
                    value = str(value)
            if name in {"approved", "ot_choice"}:
                value = _cell_value(name, value)
            cell = sheet.cell(row_index, col, value if not isinstance(value, bool) else value)
            cell.protection = LOCKED
            cell.fill = GREY
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(1, sheet.max_row)}"
    _protect(sheet)


def _protect(sheet):
    """Lock the sheet with no password. Filtering stays available."""
    sheet.protection.sheet = True
    sheet.protection.autoFilter = False
    sheet.protection.sort = False
    sheet.protection.selectLockedCells = False
    sheet.protection.selectUnlockedCells = False


def _sheet_name(path, *names):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True)
    try:
        found = set(book.sheetnames)
    finally:
        book.close()
    for name in names:
        if name in found:
            return name
    return names[0]


def read_review(path):
    sheet_name = _sheet_name(path, "審核", "Review")
    book_rows = pd.read_excel(path, sheet_name=sheet_name, dtype={"糧單編號": str, "Staff id": str, "員工編號": str, "Staff no": str})
    renamed = book_rows.rename(columns=lambda name: column_key(name, REVIEW_HEADINGS))
    return review_edits_from_frame(renamed)


def review_edits_from_frame(frame):
    edits = []
    for _, row in frame.iterrows():
        staff_id = "" if _blank(row.get("staff_id")) else str(row["staff_id"]).strip()
        if not staff_id or staff_id.lower() == "nan":
            continue
        item = {"staff_id": staff_id}
        for key in EDITABLE:
            value = _stored(key, row.get(key))
            roster_key = ROSTER_FIELDS.get(key)
            if roster_key and roster_key in row and _same(key, value, row.get(roster_key)):
                value = ""
            item[key] = value
        edits.append(item)
    return edits


def _same(key, value, roster_value):
    if key == "taken_dates":
        return _blank(value) and _blank(roster_value) or str(value).strip() == str(roster_value).strip()
    if _blank(value) and _blank(roster_value):
        return True
    try:
        return abs(float(value or 0) - float(0 if _blank(roster_value) else roster_value)) < 0.001
    except (TypeError, ValueError):
        return False


def _stored(key, value):
    if _blank(value):
        if key in NUMBER_FIELDS:
            return 0
        return ""
    if key in NUMBER_FIELDS or key in BLANK_NUMBER_FIELDS:
        return float(value)
    text = str(value).strip()
    if key == "approved":
        return store(YES_STORED, text)
    if key == "ot_choice":
        return store(OT_STORED, text)
    return text


def read_pay_date(path):
    from openpyxl import load_workbook
    book = load_workbook(path, data_only=True)
    try:
        sheet_name = "開始" if "開始" in book.sheetnames else "Start here"
        value = book[sheet_name][PAY_DATE_CELL].value
    finally:
        book.close()
    if _blank(value):
        return ""
    return str(value).strip()


def apply_pay_date(info, pay_date):
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    if "pay_date" not in meta.columns:
        meta["pay_date"] = ""
    meta.loc[0, "pay_date"] = "" if _blank(pay_date) else str(pay_date).strip()
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)


def read_pay(path):
    sheet_name = _sheet_name(path, "薪金", "Pay")
    book_rows = pd.read_excel(path, sheet_name=sheet_name, dtype={"員工編號": str, "Staff no": str})
    renamed = book_rows.rename(columns=lambda name: column_key(name, PAY_HEADINGS))
    rows = []
    for _, row in renamed.iterrows():
        employee_no = "" if _blank(row.get("employee_no")) else str(row["employee_no"]).strip()
        if not employee_no or employee_no.lower() == "nan":
            continue
        item = {"employee_no": employee_no, "slip_name": "" if _blank(row.get("slip_name")) else str(row["slip_name"]).strip()}
        for key in PAY_EDITABLE:
            item[key] = row.get(key)
        rows.append(item)
    return rows


def _allowance_desc(desc, transport, health):
    text = desc or ""
    has_health = "健康" in text or "Health" in text
    has_transport = "交通" in text or "Transport" in text
    if transport and health:
        return text if has_health and has_transport else "健康津貼 + 交通津貼"
    if transport:
        return text if has_transport else "交通津貼"
    if health:
        return text if has_health else "健康津貼"
    return ""


def set_allowances(info, book, employee_no, transport, health):
    """Change one person's transport and health allowances without rewriting the rest of the pay table."""
    from app.lock import ensure_owner
    ensure_owner(info)
    from payroll.core.excel_io import save_excel
    from payroll.staff.staff import _text, ensure_pay_table, pay_table_path

    table = ensure_pay_table(book=book)
    number = _text(employee_no)
    matches = [index for index, value in table["employee_no"].items() if _text(value) == number]
    if not matches:
        raise SystemExit("這個人不在薪金表。")
    index = matches[0]
    old_desc = "" if _blank(table.at[index, "allowance_desc"]) else str(table.at[index, "allowance_desc"]).strip()
    desc = _allowance_desc(old_desc, transport, health)
    staff_id = _cell_text(table.at[index, "staff_id"]) or number
    updated = {
        "transport_amount": float(transport),
        "health_amount": float(health),
        "allowance_amount": float(transport) + float(health),
        "allowance_desc": desc,
    }
    pairs = []
    for key, value in updated.items():
        old = table.at[index, key] if key in table.columns else ""
        table.at[index, key] = value
        pairs.append((key, old, value))
    save_excel(pay_table_path(book), table)
    log_changes(info.get("key", "") if isinstance(info, dict) else "", staff_id, pairs)


def apply_pay(rows, book="bg", info=None):
    from app.lock import ensure_owner
    ensure_owner(info)
    from payroll.staff.staff import PAY_COLUMNS, ensure_pay_table, pay_table_path
    table = ensure_pay_table(book=book)
    table["employee_no"] = table["employee_no"].map(lambda value: "" if _blank(value) else str(value).strip())
    table["staff_id"] = table["staff_id"].map(lambda value: "" if _blank(value) else str(value).strip())
    index_by_no = {employee_no: index for index, employee_no in table["employee_no"].items()}
    problems = []
    additions = []
    audit = []
    for row in rows:
        name = row["slip_name"] or row["employee_no"]
        existing = row["employee_no"] in index_by_no
        if _blank(row.get("basic_salary")) and not existing:
            continue
        salary = _positive(row.get("basic_salary"))
        if salary is None:
            problems.append(f"{name}：基本薪金必須是大於 0 的數字")
            continue
        scheme = store(SCHEME_STORED, "" if _blank(row.get("scheme")) else row.get("scheme"))
        if scheme not in {"mpf", "rent", "none"}:
            problems.append(f"{name}：計薪方式必須是本地員工、內地勞工或不扣強積金")
            continue
        rent_base = store(RENT_BASE_STORED, "" if _blank(row.get("rent_base")) else row.get("rent_base"))
        if rent_base and rent_base not in {"basic", "after_unpaid"}:
            problems.append(f"{name}：租金基準必須是基本薪金或扣無薪後")
            continue
        if not rent_base:
            if existing and not _blank(table.at[index_by_no[row["employee_no"]], "rent_base"]):
                rent_base = str(table.at[index_by_no[row["employee_no"]], "rent_base"]).strip()
            else:
                rent_base = "basic"
        bonus = _yes_stored(row.get("bonus_eligible"))
        if bonus not in {"Y", "N"}:
            problems.append(f"{name}：勤工獎必須是是或否")
            continue
        section = store(SECTION_STORED, "" if _blank(row.get("allowance_section")) else row.get("allowance_section"))
        if section not in {"", "shop", "office"}:
            problems.append(f"{name}：津貼分類必須是店舖或寫字樓")
            continue
        try:
            from payroll.core.money import rent_amount as rent_formula
            index = index_by_no.get(row["employee_no"])
            if "transport_amount" in row or "health_amount" in row:
                transport = 0.0 if _blank(row.get("transport_amount")) else float(row["transport_amount"])
                health = 0.0 if _blank(row.get("health_amount")) else float(row["health_amount"])
                allowance_amount = transport + health
            else:
                transport = None
                health = None
                allowance_amount = 0.0 if _blank(row.get("allowance_amount")) else float(row["allowance_amount"])
            desc = "" if _blank(row.get("allowance_desc")) else str(row["allowance_desc"]).strip()
            if transport is not None:
                old_desc = ""
                old_amount = 0.0
                if index is not None:
                    old_desc = "" if _blank(table.at[index, "allowance_desc"]) else str(table.at[index, "allowance_desc"]).strip()
                    if not _blank(table.at[index, "allowance_amount"]):
                        old_amount = float(table.at[index, "allowance_amount"])
                if abs(allowance_amount - old_amount) <= 0.02 and desc == old_desc:
                    desc = old_desc
                else:
                    desc = _allowance_desc(desc, transport, health)
            if not _blank(row.get("rent_rate")):
                rate = float(row["rent_rate"])
            elif index is not None and not _blank(table.at[index, "rent_rate"]):
                rate = float(table.at[index, "rent_rate"])
            else:
                rate = 0.1 if scheme == "rent" else 0.0
            updated = {
                "roster_name": "" if _blank(row.get("roster_name")) else str(row["roster_name"]).strip(),
                "basic_salary": salary,
                "scheme": scheme,
                "rent_base": rent_base,
                "water": 0.0,
                "bonus_eligible": 1 if bonus == "Y" else 0,
                "rest_days_month": 0.0 if _blank(row.get("rest_days_month")) else float(row["rest_days_month"]),
                "allowance_desc": desc,
                "allowance_amount": allowance_amount,
                "allowance_note": "" if _blank(row.get("allowance_note")) else str(row["allowance_note"]).strip(),
                "allowance_section": section,
            }
            if transport is not None:
                updated["transport_amount"] = transport
                updated["health_amount"] = health
            if not _blank(row.get("rent_rate")):
                updated["rent_rate"] = rate
            if scheme == "rent":
                updated["water"] = 0.0 if _blank(row.get("water")) else float(row["water"])
                typed_rent = None if _blank(row.get("rent_amount")) else float(row["rent_amount"])
                formula = rent_formula(salary, 0, rate, rent_base)
                if typed_rent is not None and abs(typed_rent - formula) > 0.02:
                    updated["rent_amount"] = typed_rent
                typed_power = 0.0 if _blank(row.get("electricity")) else float(row["electricity"])
                if typed_power:
                    updated["electricity"] = typed_power
            elif index is not None:
                if "rent_amount" in table.columns and not _blank(table.at[index, "rent_amount"]):
                    updated["rent_amount"] = 0
                if "electricity" in table.columns and not _blank(table.at[index, "electricity"]):
                    updated["electricity"] = 0
        except (TypeError, ValueError):
            problems.append(f"{name}：有一個薪金格不是數字")
            continue
        if existing:
            index = index_by_no[row["employee_no"]]
            staff_id = _cell_text(table.at[index, "staff_id"]) or row["employee_no"]
            for key, value in updated.items():
                old = table.at[index, key] if key in table.columns else ""
                audit.append((staff_id, key, old, value))
                table.at[index, key] = value
        else:
            additions.append({
                "employee_no": row["employee_no"],
                "staff_id": "",
                "slip_name": row["slip_name"],
                **updated,
            })
            for key, value in updated.items():
                audit.append((row["employee_no"], key, "", value))
    if problems:
        raise SystemExit("薪金資料：\n" + "\n".join(problems))
    if additions:
        table = pd.concat([table, pd.DataFrame(additions)], ignore_index=True)
    table = table.reindex(columns=PAY_COLUMNS)
    path = pay_table_path(book)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_excel(path, index=False)
    grouped = {}
    for staff_id, key, old, new in audit:
        grouped.setdefault(staff_id, []).append((key, old, new))
    for staff_id, pairs in grouped.items():
        log_changes("", staff_id, pairs)


def _yes_stored(value):
    if _blank(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    mapped = store(YES_STORED, text)
    if mapped in {"Y", "N"}:
        return mapped
    if text in {"1", "True", "true"}:
        return "Y"
    if text in {"0", "False", "false"}:
        return "N"
    return mapped


def _positive(value):
    if _blank(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _put_cell(lines, index, key, value):
    """Write one cell. Pandas 3 will not put text such as Y into a float column."""
    stored = pd.NA if value == "" else value
    if key not in lines.columns:
        lines[key] = pd.Series([pd.NA] * len(lines), dtype="object")
    elif isinstance(stored, str) and not pd.api.types.is_object_dtype(lines[key].dtype):
        lines[key] = lines[key].astype("object")
    lines.at[index, key] = stored


def _cell_text(value):
    if _blank(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        text = text[:-2]
    return "" if text.lower() == "nan" else text


def log_changes(month, staff_id, pairs):
    """Record who changed a pay field. pairs is (field, old, new)."""
    from datetime import datetime

    from payroll.core.settings import actor
    if not pairs:
        return
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    who = actor()
    rows = []
    for field, old, new in pairs:
        old_text = _cell_text(old)
        new_text = _cell_text(new)
        if old_text == new_text:
            continue
        rows.append({
            "time": when,
            "user": who,
            "month": month or "",
            "staff_id": staff_id,
            "field": field,
            "old": old_text,
            "new": new_text,
        })
    _record_audit({"key": month or ""}, rows)


def _record_audit(info, rows):
    if not rows:
        return
    from payroll.core.config import home
    from payroll.core.excel_io import save_excel
    path = home() / "data" / "payroll_audit.xlsx"
    frame = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_excel(path, engine="openpyxl")
        frame = pd.concat([old, frame], ignore_index=True)
    save_excel(path, frame)


def apply_review(info, edits):
    """Save review edits. A staff id with no line yet gets one, so a new joiner can be approved."""
    from app.lock import ensure_owner
    ensure_owner(info)
    from datetime import datetime

    from payroll.core.excel_io import save_excel
    from payroll.core.settings import actor
    from payroll.staff.staff import blank_adjustment
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    lines["staff_id"] = lines["staff_id"].map(lambda value: "" if _blank(value) else str(value).strip())
    for key in ("ot_choice", "ot_hours_paid"):
        if key not in lines.columns:
            lines[key] = ""
    index_by_id = {staff_id: index for index, staff_id in lines["staff_id"].items() if staff_id}
    original = {
        staff_id: lines.loc[index].to_dict()
        for staff_id, index in index_by_id.items()
    }
    audit = []
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    who = actor()
    for edit in edits:
        staff_id = "" if _blank(edit.get("staff_id")) else str(edit["staff_id"]).strip()
        if not staff_id or staff_id.lower() == "nan":
            continue
        if staff_id not in index_by_id:
            row = blank_adjustment({"staff_id": staff_id, "slip_name": edit.get("slip_name", "")})
            lines = pd.concat([lines, pd.DataFrame([row])], ignore_index=True)
            index_by_id[staff_id] = lines.index[-1]
            original[staff_id] = {}
        index = index_by_id[staff_id]
        previous = original.get(staff_id) or {}
        for key in EDITABLE:
            if key not in edit:
                continue
            old = _cell_text(previous.get(key))
            new = _cell_text(edit.get(key))
            _put_cell(lines, index, key, edit[key])
            if old != new:
                audit.append({
                    "time": when,
                    "user": who,
                    "month": info.get("key", ""),
                    "staff_id": staff_id,
                    "field": key,
                    "old": old,
                    "new": new,
                })
    save_excel(info["adjustments"], sheets={"lines": lines, "meta": meta})
    _record_audit(info, audit)


def approve_all(info, staff_ids):
    apply_review(info, [{"staff_id": staff_id, "approved": "Y"} for staff_id in staff_ids])


def save_one(info, staff_id, changes):
    item = {"staff_id": staff_id}
    for key, value in changes.items():
        if key == "approved":
            item[key] = store(YES_STORED, value)
        elif key == "ot_choice":
            item[key] = store(OT_STORED, value)
        else:
            item[key] = value
    apply_review(info, [item])
