"""Fill the office payroll workbook. One block of rows per person."""

import re
import shutil
from copy import copy
from pathlib import Path

from openpyxl import Workbook, load_workbook

from payroll.documents.parse_admin import parse_admin


def _text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _clone_block(sheet, start, end, dest):
    offset = dest - start
    for row in range(start, end):
        for col in range(1, sheet.max_column + 1):
            source = sheet.cell(row, col)
            target = sheet.cell(row + offset, col)
            target.value = source.value
            if source.has_style:
                target.font = copy(source.font)
                target.border = copy(source.border)
                target.fill = copy(source.fill)
                target.number_format = source.number_format
                target.alignment = copy(source.alignment)
        sheet.row_dimensions[row + offset].height = sheet.row_dimensions[row].height
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row >= start and merged.max_row < end:
            sheet.merge_cells(
                start_row=merged.min_row + offset,
                start_column=merged.min_col,
                end_row=merged.max_row + offset,
                end_column=merged.max_col,
            )
    return offset


def _donor(slips):
    for slip in slips:
        if not slip["unpaid_amount"] and not slip["allowance_amount"] and slip["scheme"] == "mpf":
            return slip
    return slips[0] if slips else None


def _write(sheet, cell, value):
    if not cell:
        return
    row, col = cell
    sheet.cell(row, col).value = value


def _fill_block(sheet, slip, row):
    anchors = slip["anchors"]
    leave_pay = float(getattr(row, "leave_pay", 0) or 0)
    _write(sheet, anchors.get("basic"), float(row.basic_salary or 0))
    _write_leave_line(sheet, anchors.get("basic"), leave_pay)
    subtotal = round(float(row.basic_salary or 0) - float(row.unpaid_amount or 0) + leave_pay, 2)
    _write(sheet, anchors.get("subtotal"), subtotal)
    _write(sheet, anchors.get("mpf_ee"), float(row.mpf_employee or 0))
    _write(sheet, anchors.get("mpf_er"), float(row.mpf_employer or 0))
    _write(sheet, anchors.get("total"), float(row.net or 0))
    if anchors.get("unpaid"):
        _write(sheet, anchors["unpaid"], float(row.unpaid_amount or 0))
    if anchors.get("name"):
        _write(sheet, anchors["name"], _text(row.slip_name))


def _write_leave_line(sheet, basic_cell, leave_pay):
    """Put unused annual leave on the next Payment row so the slip shows the addition."""
    if not basic_cell or leave_pay <= 0:
        return
    basic_row, basic_col = basic_cell
    target = basic_row + 1
    label = _text(sheet.cell(target, 2).value)
    if label.startswith("Subtotal") or "小計" in label:
        return
    sheet.cell(target, 2).value = "Unused Annual Leave 未使用年假"
    currency = sheet.cell(basic_row, basic_col - 1).value
    if currency:
        sheet.cell(target, basic_col - 1).value = currency
    sheet.cell(target, basic_col).value = leave_pay


def _stamp(sheet, start, end, staff_id, name):
    for row in range(start, end):
        for col in range(1, 14):
            text = _text(sheet.cell(row, col).value)
            if text.startswith("Employee") and "MPF" not in text and "強積金" not in text:
                sheet.cell(row, col + 1).value = name
            if re.fullmatch(r"#\s*\d+\s*-", text) and "-" in staff_id:
                sheet.cell(row, col).value = f"#{staff_id.split('-')[0]}-"
                sheet.cell(row, col + 1).value = int(staff_id.split("-", 1)[1])


def _apply_identity(sheet, slip, row, info):
    from payroll.documents.slips import autopay_line
    from payroll.staff.staff import read_batch, read_refs
    salary_ref, allowance_ref = read_refs(info)
    own = _text(row.get("salary_reference"))
    if own.lower() == "nan":
        own = ""
    pay_date = _pay_date(info)
    section = "salary"
    shown = _text(row.staff_id)
    batch = read_batch(info)
    if batch and "-" in shown:
        shown = f"{batch}-{shown.split('-', 1)[1]}"
    start, end = slip["anchors"]["start"], slip["anchors"]["end"]
    for excel_row in range(start, end):
        for col in range(1, 14):
            value = sheet.cell(excel_row, col).value
            text = _text(value)
            if text.startswith("Employee") and "MPF" not in text and "強積金" not in text:
                sheet.cell(excel_row, col + 1).value = _text(row.slip_name)
            if "Confidential File" in text or re.fullmatch(r"#\s*\d+\s*-", text):
                if "-" not in shown:
                    continue
                number_col = 10 if "Confidential File" in text else col
                sheet.cell(excel_row, number_col).value = f"#{shown.split('-')[0]}-"
                sheet.cell(excel_row, number_col + 1).value = int(shown.split("-", 1)[1])
            if isinstance(value, str) and ("計薪周期" in text or "Payment Period" in text):
                period = _text(row.get("period")) or info["period_text"]
                sheet.cell(excel_row, col + 1).value = period
            if text == "Allowance" or text.startswith("Allowance "):
                section = "allowance"
            if text.startswith("Salary Slip") or text.startswith("Basic Salary"):
                section = "salary"
            if isinstance(value, str) and value.startswith("By Auto Pay"):
                reference = allowance_ref if section == "allowance" else (own or salary_ref)
                sheet.cell(excel_row, col).value = autopay_line(value, pay_date, reference)
            if isinstance(value, str) and value.startswith("Annual Leave"):
                _write_days(sheet, excel_row, col, row.annual_taken)
                _write_leave_dates(sheet, excel_row, col, _text(getattr(row, "annual_dates", "")))
            if isinstance(value, str) and value.startswith("Sick Leave"):
                _write_days(sheet, excel_row, col, row.sick_days)
                _write_leave_dates(sheet, excel_row, col, _text(getattr(row, "sick_dates", "")))
            if isinstance(value, str) and "未使用年假" in value:
                typed = getattr(row, "unused_annual_days", None)
                if typed is not None and str(typed).strip().lower() not in {"", "nan"}:
                    _write_days(sheet, excel_row, col, typed)
                    continue
                index = sum(
                    1 for earlier in range(start, excel_row)
                    if "未使用年假" in _text(sheet.cell(earlier, col).value)
                )
                lines = list(row.get("al_lines") or [])
                if index < len(lines):
                    days = lines[index].get("days", 0) if isinstance(lines[index], dict) else 0
                    _write_days(sheet, excel_row, col, days)


def _write_leave_dates(sheet, row, col, dates):
    """Replace last month's date, such as 12/10(AM), with this month's dates."""
    day_col = None
    for scan in range(col + 1, 16):
        if "Day" in _text(sheet.cell(row, scan).value):
            day_col = scan
            break
    if day_col is None:
        return
    written = False
    for scan in range(col + 1, day_col):
        value = sheet.cell(row, scan).value
        if isinstance(value, str) and value.strip() and "Day" not in value:
            sheet.cell(row, scan).value = dates if not written else None
            written = True
    if dates and not written:
        sheet.cell(row, max(col + 1, day_col - 2)).value = dates


def _write_days(sheet, row, col, days):
    for scan in range(col + 1, 16):
        neighbour = _text(sheet.cell(row, scan + 1).value)
        if "Day" in neighbour:
            sheet.cell(row, scan).value = float(days or 0)
            return


def _pay_date(info):
    import pandas as pd
    override = _text(info.get("pay_date_override")) if isinstance(info, dict) else ""
    if override:
        return override
    path = info["adjustments"]
    if not path.exists():
        return ""
    meta = pd.read_excel(path, sheet_name="meta")
    if meta.empty or "pay_date" not in meta.columns:
        return ""
    return _text(meta.iloc[0]["pay_date"])


def _write_allowances(sheet, slip, row):
    descriptions = [part.strip() for part in _text(row.allowance_desc).split("+") if part.strip()]
    amount = float(row.allowance_amount or 0)
    slots = slip.get("allowances") or []
    if not slots and not descriptions:
        return
    if slots and len(descriptions) == len(slots):
        for slot, description in zip(slots, descriptions):
            label_row = slot["cell"][0]
            sheet.cell(label_row, 2).value = description
    health = float(getattr(row, "final_health", 0) or 0)
    transport = float(getattr(row, "final_transport", 0) or 0)
    if slots and abs(amount - (health + transport)) < 0.02:
        written = 0.0
        for slot in slots:
            label = _text(sheet.cell(slot["cell"][0], 2).value).lower()
            if "health" in label or "健康" in label:
                piece = health
            elif "transport" in label or "交通" in label:
                piece = transport
            else:
                continue
            _write(sheet, slot["cell"], piece)
            written += piece
        for excel_row in range(slots[0]["cell"][0], slots[-1]["cell"][0] + 6):
            if _text(sheet.cell(excel_row, 2).value).startswith("Total"):
                _write(sheet, (excel_row, slots[0]["cell"][1]), round(written, 2))
                break
        return
    if len(slots) == 1:
        _write(sheet, slots[0]["cell"], amount)
    elif len(slots) > 1 and descriptions:
        # The slip stores one combined amount. Split is already on the template cells.
        return


def fill_admin(info, draft):
    template = info["slip_template"]
    output = info["slip_output"]
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, output)
    book = load_workbook(output)
    sheet = book.worksheets[0]
    slips = parse_admin(output)
    present = {slip["staff_id"] for slip in slips}
    missing = []
    for _, row in draft[draft["pay_this"].astype(bool)].iterrows():
        staff_id = _text(row.staff_id)
        if staff_id and staff_id not in present:
            missing.append(row)
    donor = _donor(slips)
    if donor and missing:
        dest = max(slip["anchors"]["end"] for slip in slips)
        for row in missing:
            start = donor["anchors"]["start"]
            end = donor["anchors"]["end"]
            offset = _clone_block(sheet, start, end, dest)
            _stamp(sheet, dest, dest + (end - start), _text(row.staff_id), _text(row.slip_name))
            dest = dest + (end - start)
        book.save(output)
        slips = parse_admin(output)
        book = load_workbook(output)
        sheet = book.worksheets[0]
    by_id = {slip["staff_id"]: slip for slip in slips}
    for _, row in draft[draft["pay_this"].astype(bool)].iterrows():
        slip = by_id.get(_text(row.staff_id))
        if slip is None:
            continue
        _fill_block(sheet, slip, row)
        _apply_identity(sheet, slip, row, info)
        _write_allowances(sheet, slip, row)
    book.save(output)
    from payroll.core.excel_io import guard_xlsx
    guard_xlsx(output)
    return output


def _copy_person(path, start, end):
    """Keep one person's rows. Deleting rows drops merged cells, so copy the range instead."""
    source_book = load_workbook(path)
    sheet = source_book.worksheets[0]
    book = Workbook()
    dest = book.active
    dest.title = sheet.title
    for col in range(1, sheet.max_column + 1):
        letter = sheet.cell(1, col).column_letter
        dest.column_dimensions[letter].width = sheet.column_dimensions[letter].width
    for offset, row in enumerate(range(start, end)):
        dest.row_dimensions[offset + 1].height = sheet.row_dimensions[row].height
        for col in range(1, sheet.max_column + 1):
            cell = sheet.cell(row, col)
            target = dest.cell(offset + 1, col, cell.value)
            if cell.has_style:
                target.font = copy(cell.font)
                target.border = copy(cell.border)
                target.fill = copy(cell.fill)
                target.number_format = cell.number_format
                target.alignment = copy(cell.alignment)
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row >= start and merged.max_row < end:
            dest.merge_cells(
                start_row=merged.min_row - start + 1,
                start_column=merged.min_col,
                end_row=merged.max_row - start + 1,
                end_column=merged.max_col,
            )
    source_book.close()
    book.save(path)
    from payroll.core.excel_io import guard_xlsx
    guard_xlsx(path)


def refresh_leave_dates(path, row):
    """Drop a leave date that belongs to another month, such as 12/10 on a November slip."""
    file = Path(path)
    if not file.is_file():
        return
    book = load_workbook(file)
    sheet = book.worksheets[0]
    for excel_row in range(1, sheet.max_row + 1):
        for col in range(1, 14):
            value = sheet.cell(excel_row, col).value
            if not isinstance(value, str):
                continue
            if value.startswith("Annual Leave"):
                _write_days(sheet, excel_row, col, getattr(row, "annual_taken", 0))
                _write_leave_dates(sheet, excel_row, col, _text(getattr(row, "annual_dates", "")))
            elif value.startswith("Sick Leave"):
                _write_days(sheet, excel_row, col, getattr(row, "sick_days", 0))
                _write_leave_dates(sheet, excel_row, col, _text(getattr(row, "sick_dates", "")))
    book.save(file)
    from payroll.core.excel_io import guard_xlsx
    guard_xlsx(file)


def write_person_slip(info, draft, staff_id):
    """One office person's PDF slip. The spreadsheet copy is kept beside it."""
    person = draft[draft["staff_id"].astype(str) == str(staff_id)]
    if person.empty:
        raise SystemExit(f"找不到 {staff_id}")
    name = _text(person.iloc[0].get("slip_name")).split()[0] or staff_id
    safe = re.sub(r"[<>:\"/\\|?*']", "", name).strip() or staff_id
    from payroll.staff.staff import read_batch
    batch = read_batch(info) or str(staff_id).split("-")[0]
    suffix = str(staff_id).split("-")[-1]
    folder = info["output"] / "個別"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"#{batch}_{suffix}_{safe}.xlsx"
    booked = dict(info)
    booked["slip_output"] = target
    fill_admin(booked, draft)
    slips = parse_admin(target)
    chosen = next((slip for slip in slips if slip["staff_id"] == str(staff_id)), None)
    if chosen is not None:
        _copy_person(target, chosen["anchors"]["start"], chosen["anchors"]["end"])
    pdf = target.with_suffix(".pdf")
    from payroll.documents.slip_pdf import write_office_pdf
    write_office_pdf(pdf, person.iloc[0], info)
    return pdf
