"""Staff-file writes go through Excel and keep the dropdowns."""

import os
import subprocess
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
import pandas as pd

from payroll.core.config import parse_month, scratch_dir
from payroll.pay.part_time import load_pt
from payroll.staff.staff import (
    grey_but_employed, load_staff, next_employee_no, pick_staff_file, staff_file_day,
    staff_options, staff_version_path,
)
from payroll.staff.staff_write import add_staff, edit_staff, resign_staff, salary_history_path, set_hourly_rate, set_monthly_salary


def _excel_ready():
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "try { $excel = New-Object -ComObject Excel.Application; $excel.Quit(); 'yes' } catch { 'no' }"],
        capture_output=True, text=True, timeout=60,
    )
    return "yes" in (done.stdout or "")


def _workbook(path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BG & MD"
    headers = [
        "員工編號", "中文姓名", "英文姓名", "職位", "部門", "僱傭狀況", "就業形式",
        "入職日期", "離職日期", "性別", "銀行賬號", "身份證號碼",
    ]
    for column, name in enumerate(headers, start=1):
        sheet.cell(5, column, name)
    sheet.cell(6, 1, "B001")
    sheet.cell(6, 2, "張三")
    sheet.cell(6, 4, "店員")
    sheet.cell(6, 5, "WC - Retail")
    sheet.cell(6, 6, "在職")
    sheet.cell(6, 7, "全職")
    mainland = book.create_sheet("內地勞工")
    for column, name in enumerate(
        ["員工編號", "中文姓名", "職位", "部門", "僱傭狀況", "就業形式", "到職日期", "性別"], start=1,
    ):
        mainland.cell(5, column, name)
    mainland.cell(6, 1, "ESL001")
    mainland.cell(6, 2, "李四")
    mainland.cell(6, 4, "WC - Retail")
    mainland.cell(6, 5, "在職")
    mainland.cell(6, 6, "24個月")
    lists = book.create_sheet("Sheet2")
    lists.cell(2, 1, "男")
    lists.cell(3, 1, "女")
    lists.cell(2, 6, "全職")
    lists.cell(2, 7, "在職")
    rule = DataValidation(type="list", formula1="=Sheet2!$A$2:$A$3", allow_blank=True)
    rule.add("J6:J30")
    sheet.add_data_validation(rule)
    book.save(path)


def test_numbers_options_and_salary():
    home = scratch_dir("staff-salary")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        (home / "data").mkdir(parents=True)
        pd.DataFrame([{
            "employee_no": "B001", "staff_id": "243-1", "slip_name": "張三",
            "roster_name": "", "basic_salary": 1000,
        }]).to_excel(home / "data" / "pay_table.xlsx", index=False)
        info = parse_month("2026-10")
        (info["folder"]).mkdir(parents=True, exist_ok=True)
        set_monthly_salary("bg", "B001", 2500)
        saved = pd.read_excel(home / "data" / "pay_table.xlsx")
        if float(saved.iloc[0]["basic_salary"]) != 2500:
            raise SystemExit(f"salary not saved: {saved.iloc[0]['basic_salary']}")
        set_hourly_rate(info, "RPT009", 65)
        lines, _meta = load_pt(info)
        rate = lines[lines["employee_no"].map(str) == "RPT009"]["rate"]
        if rate.empty or float(rate.iloc[0]) != 65:
            raise SystemExit(f"hourly rate {list(rate)}")
        history = pd.read_excel(salary_history_path())
        if len(history) != 2:
            raise SystemExit(f"salary history {len(history)}")
        staff = pd.DataFrame({"employee_no": ["A001", "A003", "RPT002", "ESL010"]})
        if next_employee_no(staff, "A") != "A004" or next_employee_no(staff, "ESL") != "ESL011":
            raise SystemExit("next employee number")
        book = home / "lists.xlsx"
        _workbook(book)
        options = staff_options(book)
        if options["性別"] != ["男", "女"] or "全職" not in options["就業形式"]:
            raise SystemExit(f"options {options}")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


def test_version_name_beats_a_newer_old_file():
    home = scratch_dir("staff-version")
    older = home / "Staff_info_202502.xlsx"
    newer = home / "Staff_info_20261119.xlsx"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")
    now = time.time()
    os.utime(older, (now, now))
    os.utime(newer, (now - 10000, now - 10000))
    if pick_staff_file([older, newer]) != newer:
        raise SystemExit("舊檔名不應因為較新的修改時間而勝出")
    if staff_file_day(home / "notes.xlsx") is not None:
        raise SystemExit("沒有日期的檔名不應有版本日")
    if staff_version_path(home, date(2026, 11, 20)).name != "Staff_info_20261120.xlsx":
        raise SystemExit("今天的版本檔名不對")


def test_excel_add_edit_resign():
    if not _excel_ready():
        print("Excel COM 不在這部電腦，員工檔寫入測試已跳過。")
        return
    home = scratch_dir("staff-write")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        path = home / "Staff_info_202502.xlsx"
        _workbook(path)
        add_staff("BG & MD", "B002", "王五", {"職位": "麵包師", "部門": "WC - Bread", "僱傭狀況": "在職", "性別": "男"}, path)
        edit_staff("BG & MD", "B001", "張三", {"職位": "店長", "身份證號碼": "Z123456(7)"}, path)
        resign_staff("內地勞工", "ESL001", "李四", "2026-10-14", path)
        current = staff_version_path(home)
        if not current.exists() or path.exists():
            raise SystemExit(f"員工檔沒有改成 {current.name}")
        staff = load_staff(current)
        added = staff[staff["employee_no"].map(str) == "B002"]
        if added.empty or str(added.iloc[0]["position"]) != "麵包師":
            raise SystemExit("新增的員工沒有讀回來")
        edited = staff[(staff["employee_no"].map(str) == "B001")]
        if str(edited.iloc[0]["position"]) != "店長" or str(edited.iloc[0]["hkid"]) != "Z123456(7)":
            raise SystemExit("修改沒有讀回來")
        left = staff[staff["employee_no"].map(str) == "ESL001"].iloc[0]
        if str(left["status"]) != "已離職" or str(left["leave_date"])[:10] != "2026-10-14":
            raise SystemExit(f"離職沒有讀回來 {left['status']} {left['leave_date']}")
        with zipfile.ZipFile(current) as packed:
            xml = packed.read("xl/worksheets/sheet1.xml").decode("utf-8")
        if "dataValidation" not in xml or "Sheet2" not in xml:
            raise SystemExit("下拉選單被刪掉了")
        book = load_workbook(current)
        row = None
        for cells in book["內地勞工"].iter_rows(min_row=6, max_row=10):
            if str(cells[0].value) == "ESL001":
                row = cells
                break
        if row is None:
            raise SystemExit("找不到離職列")
        for cell in row[1:12]:
            color = cell.fill.fgColor
            if color is None or color.theme != 6 or abs(float(color.tint or 0) - 0.4) > 0.05:
                raise SystemExit(f"離職列顏色不對 {color.theme if color else None} {getattr(color, 'tint', None)}")
        if grey_but_employed(current):
            raise SystemExit(f"在職列被當成灰色 {grey_but_employed(current)}")
        backups = list((home / "_備份").glob("Staff_info_*.xlsx"))
        if len(backups) < 3 or not any(item.name.startswith("Staff_info_202502_") for item in backups):
            raise SystemExit(f"備份不對 {[item.name for item in backups]}")
        log = pd.read_excel(home / "data" / "staff_changes.xlsx")
        secret = log[log["field"].map(str) == "身份證號碼"]
        if secret.empty or str(secret.iloc[0]["new"]) != "已更改" or "Z123" in str(secret.iloc[0]["new"]):
            raise SystemExit("身份證號碼不應寫進修改紀錄")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


if __name__ == "__main__":
    test_numbers_options_and_salary()
    test_version_name_beats_a_newer_old_file()
    test_excel_add_edit_resign()
    print("staff write ok")
