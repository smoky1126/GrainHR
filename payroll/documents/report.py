"""A short Chinese workbook HR can read. It is not where numbers are edited."""

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from payroll.core.labels import BOOKS, VIEW_ONLY, YES, chinese_note, show
from payroll.core.money import LATE_GRACE_MINUTES

MONEY = ("基本薪金", "加班費", "無薪假扣款", "租金", "水費", "電費", "強積金", "本月勤工獎", "本季發放", "其他調整", "淨薪金", "津貼")
COLUMNS = (
    ("staff_id", "糧單編號"),
    ("slip_name", "姓名"),
    ("basic_salary", "基本薪金"),
    ("ot_pay", "加班費"),
    ("unpaid_amount", "無薪假扣款"),
    ("rent", "租金"),
    ("water", "水費"),
    ("electricity", "電費"),
    ("mpf_employee", "強積金"),
    ("bonus", "本月勤工獎"),
    ("bonus_paid", "本季發放"),
    ("manual_delta", "其他調整"),
    ("net", "淨薪金"),
    ("allowance_amount", "津貼"),
    ("ot_text", "加班備註"),
    ("review", "問題"),
    ("approved", "批准"),
)
DAY_HEADERS = ["姓名", "日期", "更表", "採用店鋪", "更表內容", "上班", "下班", "打卡地點", "情況"]
DAY_KEYS = ["Name", "Date", "Rosters", "Chosen shop", "Roster cell", "DAKA in", "DAKA out", "DAKA place", "Status"]
RED = Font(color="C00000", bold=True)
AMBER = Font(color="C65911", bold=True)
BLUE_FONT = Font(color="2F5496", bold=True)

HEADER = Font(bold=True)
GREY = PatternFill("solid", fgColor="D9D9D9")
BLUE = PatternFill("solid", fgColor="BDD7EE")
LOCKED = Protection(locked=True)


def _text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _number(value):
    text = _text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def write_report(info):
    """One sheet per payroll, plus people who are not on a slip and the daily record."""
    from payroll.core.config import book_info
    from payroll.pay.payroll import build_draft
    from payroll.staff.staff import pay_table_path

    drafts = {}
    days = None
    for book in ("md", "admin", "bg"):
        if not pay_table_path(book).exists():
            continue
        drafts[book] = build_draft(book_info(info, book), write=False)
        if book == "bg" or days is None:
            path = info["system"] / "days.xlsx"
            if path.exists():
                days = pd.read_excel(path)

    book = Workbook()
    _start(book.active, info, [name for name in ("bg", "md", "admin") if name in drafts])
    for key in ("bg", "md", "admin"):
        if key not in drafts:
            continue
        _people(book.create_sheet(BOOKS[key]), drafts[key])
    others = []
    for frame in drafts.values():
        if "show_not_on_slip" not in frame.columns:
            continue
        others.append(frame[frame["show_not_on_slip"].astype(bool)])
    outside = pd.concat(others, ignore_index=True) if others else pd.DataFrame()
    _outside(book.create_sheet("不在糧單"), outside)
    _days(book.create_sheet("每日紀錄"), days)
    path = info["output"] / "payroll_draft.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    from payroll.core.excel_io import guard_xlsx
    guard_xlsx(path)
    return path


def _start(sheet, info, books):
    from payroll.core.config import book_info
    from payroll.staff.staff import read_refs

    sheet.title = "開始"
    from payroll.core.money import bonus_rule_text

    lines = [
        VIEW_ONLY,
        "這份 Excel 只供查看。請在薪酬系統裡修改。",
        "每份糧單有自己的一頁。",
        bonus_rule_text(),
    ]
    for index, line in enumerate(lines, start=1):
        sheet.cell(index, 1, line)
    sheet.cell(4, 1).alignment = Alignment(wrap_text=True, vertical="center")
    sheet.merge_cells("A4:B4")
    sheet.row_dimensions[4].height = 48
    label = sheet.cell(5, 1, "出糧日期")
    label.font = HEADER
    label.fill = GREY
    pay_date = ""
    meta_path = info["adjustments"]
    if meta_path.exists():
        meta = pd.read_excel(meta_path, sheet_name="meta")
        if not meta.empty and "pay_date" in meta.columns:
            pay_date = _text(meta.iloc[0]["pay_date"])
    sheet.cell(5, 2, pay_date or None).fill = GREY
    row = 7
    for book in books:
        salary, allowance = read_refs(book_info(info, book))
        sheet.cell(row, 1, f"{BOOKS[book]}薪金交易編號").font = HEADER
        sheet.cell(row, 2, salary or None)
        row += 1
        sheet.cell(row, 1, f"{BOOKS[book]}津貼交易編號").font = HEADER
        sheet.cell(row, 2, allowance or None)
        row += 1
    sheet.column_dimensions["A"].width = 36
    sheet.column_dimensions["B"].width = 24
    sheet.sheet_view.showGridLines = False
    _protect(sheet)


def _people(sheet, draft):
    paid = draft[draft["pay_this"].astype(bool)] if "pay_this" in draft.columns else draft
    if "staff_id" in paid.columns:
        paid = paid.sort_values("staff_id", kind="stable")
    for col, (_key, heading) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(1, col, heading)
        cell.font = HEADER
        cell.fill = BLUE
        cell.protection = LOCKED
    totals = {heading: 0.0 for heading in MONEY}
    for row_index, (_, source) in enumerate(paid.iterrows(), start=2):
        for col, (key, heading) in enumerate(COLUMNS, start=1):
            raw = source.get(key) if hasattr(source, "get") else source[key] if key in source else None
            if key == "ot_text" and not _text(raw):
                raw = source.get("ot_suggest") if hasattr(source, "get") else None
            value = _cell(key, raw)
            if heading in MONEY:
                totals[heading] += _number(value)
                value = _number(source.get(key))
            cell = sheet.cell(row_index, col, value if value != "" else None)
            cell.fill = GREY
            cell.protection = LOCKED
            if key in {"ot_text", "review"}:
                cell.alignment = Alignment(wrap_text=True)
    total_row = len(paid) + 2
    sheet.cell(total_row, 2, "合計").font = HEADER
    for col, (_key, heading) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(total_row, col)
        cell.fill = BLUE
        cell.protection = LOCKED
        if heading in MONEY:
            cell.value = round(totals[heading], 2)
            cell.font = HEADER
        elif heading == "姓名":
            cell.value = "合計"
            cell.font = HEADER
    widths = {"糧單編號": 14, "姓名": 28, "加班備註": 36, "問題": 36, "批准": 10}
    for col, (_key, heading) in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(col)].width = widths.get(heading, 14)
    last_col = get_column_letter(len(COLUMNS))
    last_data = max(1, total_row - 1)
    sheet.auto_filter.ref = f"A1:{last_col}{last_data}"
    sheet.freeze_panes = "C2"
    _protect(sheet)


def _cell(key, value):
    if key == "approved":
        return show(YES, _text(value))
    if key == "review":
        return chinese_note(value)
    if key in {"ot_text", "staff_id", "slip_name"}:
        return _text(value)
    return value


def _outside(sheet, rows):
    headers = ["姓名", "店鋪", "問題"]
    for col, heading in enumerate(headers, start=1):
        cell = sheet.cell(1, col, heading)
        cell.font = HEADER
        cell.fill = GREY
    if rows is not None and len(rows):
        for row_index, (_, source) in enumerate(rows.iterrows(), start=2):
            sheet.cell(row_index, 1, _text(source.get("slip_name"))).fill = GREY
            sheet.cell(row_index, 2, _text(source.get("shops"))).fill = GREY
            sheet.cell(row_index, 3, chinese_note(source.get("review"))).fill = GREY
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["C"].width = 42
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:C{max(1, sheet.max_row)}"
    _protect(sheet)


def _days(sheet, days):
    for col, heading in enumerate(DAY_HEADERS, start=1):
        cell = sheet.cell(1, col, heading)
        cell.font = HEADER
        cell.fill = GREY
    if days is not None and len(days):
        for row_index, (_, source) in enumerate(days.iterrows(), start=2):
            late = _number(source["Late"]) if "Late" in source else 0
            early = _number(source["Early"]) if "Early" in source else 0
            overtime = _number(source["OT"]) if "OT" in source else 0
            for col, key in enumerate(DAY_KEYS, start=1):
                value = source[key] if key in source else None
                cell = sheet.cell(row_index, col, None if not _text(value) else value)
                cell.fill = GREY
                cell.protection = LOCKED
                if key == "DAKA in" and late > LATE_GRACE_MINUTES:
                    cell.font = RED
                elif key == "DAKA in" and late > 0:
                    cell.font = AMBER
                elif key == "DAKA out" and early > 0:
                    cell.font = RED
                elif key == "DAKA out" and overtime > 0:
                    cell.font = BLUE_FONT
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["C"].width = 42
    sheet.column_dimensions["E"].width = 22
    sheet.freeze_panes = "A2"
    last_col = get_column_letter(len(DAY_HEADERS))
    sheet.auto_filter.ref = f"A1:{last_col}{max(1, sheet.max_row)}"
    _protect(sheet)


def _protect(sheet):
    sheet.protection.sheet = True
    sheet.protection.autoFilter = False
    sheet.protection.sort = False
    sheet.protection.selectLockedCells = False
    sheet.protection.selectUnlockedCells = False
