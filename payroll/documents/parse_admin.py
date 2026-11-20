"""Read the office payroll workbook. One block per person, found by its labels."""

import re
from datetime import datetime

from openpyxl import load_workbook


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _number(value):
    if isinstance(value, (int, float)) and value == value:
        return float(value)
    text = _text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _blocks(sheet):
    starts = []
    for row in range(1, sheet.max_row + 1):
        label = _text(sheet.cell(row, 2).value)
        if label.startswith("Employee") and "MPF" not in label and "強積金" not in label:
            starts.append(row)
    starts.append(sheet.max_row + 1)
    return list(zip(starts, starts[1:]))


def _cells(sheet, start, end):
    found = []
    for row in range(start, end):
        for col in range(1, 16):
            value = sheet.cell(row, col).value
            if value not in (None, ""):
                found.append((row, col, value))
    return found


def _find(cells, predicate):
    for row, col, value in cells:
        if isinstance(value, str) and predicate(value):
            return row, col, value
    return None


def _money_cell(sheet, row):
    """The amount sits in the cell after HKD$."""
    for col in range(1, 16):
        if "HKD" in _text(sheet.cell(row, col).value).upper():
            return col + 1
    return None


def _amount(sheet, row):
    """The money on a row. A 5% rate is ignored."""
    cell = _money_cell(sheet, row)
    if cell:
        number = _number(sheet.cell(row, cell).value)
        if number is not None:
            return cell, abs(number)
    found = []
    for col in range(1, 16):
        number = _number(sheet.cell(row, col).value)
        if number is not None and abs(number) >= 1:
            found.append((col, abs(number)))
    if not found:
        return _money_cell(sheet, row), None
    return found[-1]


def _days_after(sheet, row, col):
    """The day count to the right of a label, followed by Day(s)."""
    for scan in range(col + 1, 16):
        value = sheet.cell(row, scan).value
        if isinstance(value, str) or _number(value) is None:
            continue
        neighbour = _text(sheet.cell(row, scan + 1).value)
        if "Day" in neighbour:
            return _number(value)
    return 0


def _parse_block(sheet, start, end):
    cells = _cells(sheet, start, end)
    name = ""
    employee = _find(cells, lambda text: text.startswith("Employee"))
    if employee:
        for col in range(employee[1] + 1, 8):
            text = _text(sheet.cell(employee[0], col).value)
            if text and "部門" not in text and not text.startswith("Department"):
                name = text
                break
        if not name:
            name = _text(employee[2]).split("：", 1)[-1].split(":", 1)[-1].strip()

    staff_id = ""
    for row, col, value in cells:
        match = re.search(r"#\s*(\d+)\s*-\s*(\d+)", _text(value))
        if match:
            staff_id = f"{match.group(1)}-{match.group(2)}"
            break
        if re.fullmatch(r"#\s*\d+\s*-", _text(value)):
            number = _number(sheet.cell(row, col + 1).value)
            prefix = re.search(r"(\d+)", _text(value))
            if prefix and number is not None:
                staff_id = f"{prefix.group(1)}-{int(number)}"
                break

    def beside(predicate):
        found = _find(cells, predicate)
        if not found:
            return ""
        return _text(sheet.cell(found[0], found[1] + 1).value)

    department = beside(lambda text: "部門" in text)
    position = beside(lambda text: "職位" in text)
    join_date = beside(lambda text: "入職日期" in text)

    basic_at = _find(cells, lambda text: text.startswith("Basic Salary"))
    basic = 0.0
    basic_cell = None
    if basic_at:
        col, amount = _amount(sheet, basic_at[0])
        basic = amount or 0.0
        basic_cell = (basic_at[0], col) if col else None

    unpaid_days = 0
    unpaid_amount = 0.0
    unpaid_cell = None
    npl = _find(cells, lambda text: text.startswith("NPL") or "無薪假" in text and "Day" not in text and "天" not in text)
    if npl:
        for col in range(npl[1] + 1, 10):
            value = sheet.cell(npl[0], col).value
            number = _number(value)
            if number is not None and not isinstance(value, str):
                unpaid_days = number
                break
    for row, col, value in cells:
        text = _text(value)
        if "無薪" in text and "天" in text:
            match = re.search(r"(\d+(?:\.\d+)?)\s*天", text)
            if match:
                unpaid_days = max(unpaid_days, float(match.group(1)))
            money_col, money = _amount(sheet, row)
            if money:
                unpaid_amount = money
                unpaid_cell = (row, money_col)
    if unpaid_amount == 0 and unpaid_days and basic:
        unpaid_amount = round(basic / 31 * unpaid_days, 2)

    def money_row(predicate):
        found = _find(cells, predicate)
        if not found:
            return 0.0, None
        col, amount = _amount(sheet, found[0])
        return (amount or 0.0), ((found[0], col) if col else None)

    allowance_at = _find(cells, lambda text: text.strip() == "Allowance")
    allowance_row = allowance_at[0] if allowance_at else end

    def before_allowance(predicate):
        found = None
        for row, col, value in cells:
            if row >= allowance_row:
                break
            if isinstance(value, str) and predicate(value):
                found = (row, col, value)
        return found

    subtotal, subtotal_cell = (0.0, None)
    sub = before_allowance(lambda text: "小計" in text)
    if sub:
        col, amount = _amount(sheet, sub[0])
        subtotal, subtotal_cell = amount or 0.0, ((sub[0], col) if col else None)

    mpf_ee, mpf_ee_cell = (0.0, None)
    mpf_er, mpf_er_cell = (0.0, None)
    for row, col, value in cells:
        if row >= allowance_row:
            break
        text = _text(value)
        if "強積金" not in text and "MPF" not in text:
            continue
        money_col, amount = _amount(sheet, row)
        if "僱主" in text or "Employer" in text:
            mpf_er = amount or 0.0
            mpf_er_cell = (row, money_col) if money_col else None
        elif "僱員" in text or "Employee" in text:
            mpf_ee = amount or 0.0
            mpf_ee_cell = (row, money_col) if money_col else None

    total, total_cell = (None, None)
    total_at = before_allowance(lambda text: text.startswith("Total"))
    if total_at:
        col, amount = _amount(sheet, total_at[0])
        total, total_cell = amount, ((total_at[0], col) if col else None)

    allowances = []
    if allowance_at:
        for row in range(allowance_at[0] + 1, end):
            label = _text(sheet.cell(row, 2).value)
            if not label or label.startswith("Total") or label.startswith("By Auto") or label.startswith("For salary"):
                if label.startswith("Total"):
                    break
                continue
            col, amount = _amount(sheet, row)
            if amount:
                allowances.append({"description": label, "amount": amount, "cell": (row, col)})

    def leave(predicate):
        found = _find(cells, predicate)
        if not found:
            return 0, ""
        dates = ""
        for col in range(found[1] + 1, 16):
            text = _text(sheet.cell(found[0], col).value)
            if text and "Day" not in text and _number(text) is None:
                dates = text
                break
        return _days_after(sheet, found[0], found[1]), dates

    sick, _sick_dates = leave(lambda text: text.startswith("Sick Leave") or text.startswith("病假"))
    annual, annual_dates = leave(lambda text: text.startswith("Annual Leave") or text.startswith("年假"))
    birthday, _birthday_dates = leave(lambda text: text.startswith("Birthday") or text.startswith("生日假"))
    al_lines = []
    for row, col, value in cells:
        text = _text(value)
        if "未使用年假" not in text:
            continue
        al_lines.append({"label": text, "days": _days_after(sheet, row, col), "row": row})

    scheme = "mpf" if mpf_ee else "none"
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", name))
    english = re.sub(r"[\u4e00-\u9fff]", " ", name)
    english = re.sub(r"\s+", " ", english).strip()
    formula = basic - unpaid_amount - mpf_ee
    manual = round((total or 0) - formula, 2) if total is not None else 0.0
    if abs(manual) < 0.05:
        manual = 0.0
    return {
        "staff_id": staff_id,
        "slip_name": name,
        "name_en": english,
        "name_zh": chinese,
        "department": department,
        "position": position,
        "join_date": join_date if not isinstance(join_date, datetime) else join_date,
        "basic_salary": basic,
        "scheme": scheme,
        "rent": 0.0,
        "rent_base": "",
        "water": 0.0,
        "unpaid_days": unpaid_days,
        "unpaid_amount": unpaid_amount,
        "other_income": 0.0,
        "stated_extra": 0.0,
        "manual_delta": manual,
        "mpf_employee": mpf_ee,
        "mpf_employer": mpf_er,
        "subtotal": subtotal,
        "net": total,
        "bonus": None,
        "bonus_eligible": False,
        "allowance_desc": " + ".join(item["description"] for item in allowances),
        "allowance_amount": sum(item["amount"] for item in allowances),
        "allowances": allowances,
        "opening_rest": 0,
        "rest_entitlement": 0,
        "taken_rest": 0,
        "taken_dates": "",
        "unused_rest": 0,
        "statutory_days": 0,
        "sick_days": sick,
        "annual_taken": annual,
        "annual_dates": annual_dates,
        "birthday_days": birthday,
        "al_lines": [{"label": line["label"], "days": line["days"]} for line in al_lines],
        "absent_days": 0,
        "absent_mins": 0,
        "absent_lines": [],
        "ot_lines": [],
        "anchors": {
            "basic": basic_cell,
            "subtotal": subtotal_cell,
            "mpf_ee": mpf_ee_cell,
            "mpf_er": mpf_er_cell,
            "total": total_cell,
            "unpaid": unpaid_cell,
            "name": (employee[0], employee[1] + 1) if employee else None,
            "start": start,
            "end": end,
        },
    }


def parse_admin(path):
    book = load_workbook(path, data_only=True)
    sheet = book.worksheets[0]
    slips = [_parse_block(sheet, start, end) for start, end in _blocks(sheet)]
    book.close()
    return slips
