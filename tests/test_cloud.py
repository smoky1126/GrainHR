"""Linux paths, office-pay hiding, and staff-cell edits that keep dropdowns."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from payroll.core.access import can_see_pay, hide_office_file, scrub_office_row, visible_audit, visible_books
from payroll.core.settings import map_server_path, role_for
from payroll.staff.sheet_edit import edit_staff_sheet


def _fail(message):
    raise SystemExit(message)


def test_paths_keep_the_folder_boundary():
    root = r"G:\Company files\HR"
    mount = "/srv/grainhr/hr"
    staff = map_server_path(r"G:\Company files\HR\Records\Staff", root, mount)
    if staff != "/srv/grainhr/hr/Records/Staff":
        _fail(staff)
    other = map_server_path(r"G:\Company files\HR System\GrainHR", root, mount)
    if other != r"G:\Company files\HR System\GrainHR":
        _fail(other)
    sheets = map_server_path(r"G:\Other disk\Rosters\Sheets", root, mount)
    if sheets != r"G:\Other disk\Rosters\Sheets":
        _fail(sheets)


def test_hr_cannot_see_office_pay():
    books = {"bg": "Shop", "md": "Bakery B", "admin": "Office"}
    if "admin" in visible_books(books, "hr"):
        _fail("hr still has the office book")
    if set(visible_books(books, "admin")) != set(books):
        _fail("admin lost a book")
    if can_see_pay("bg_retail", "hr") is not True or can_see_pay("admin", "hr") is not False:
        _fail("group check")
    hidden = scrub_office_row({"group": "admin", "salary": 18000, "bank_account": "123", "name_zh": "甲"}, "hr")
    if hidden["salary"] is not None or hidden["bank_account"] is not None or hidden["name_zh"] != "甲":
        _fail(hidden)
    shop = scrub_office_row({"group": "bg_retail", "salary": 15000, "name_zh": "乙"}, "hr")
    if shop["salary"] != 15000:
        _fail(shop)
    if not hide_office_file("payslips_admin.xlsx", "hr") or not hide_office_file("payroll_draft.xlsx", "hr"):
        _fail("office files stayed visible")
    if hide_office_file("payslips.docx", "hr") or hide_office_file("payslips_admin.xlsx", "admin"):
        _fail("shop files or admin files were hidden")
    import pandas as pd
    audit = pd.DataFrame([
        {"staff_id": "A-1", "field": "manual_delta", "new": "500"},
        {"staff_id": "B-1", "field": "manual_delta", "new": "20"},
    ])
    shown = visible_audit(audit, "hr", {"A-1"})
    if list(shown["staff_id"]) != ["B-1"] or "500" in " ".join(shown.astype(str).values.ravel()):
        _fail(shown.to_dict("records"))


def test_unknown_role_is_hr_and_viewer_is_not_a_role():
    if role_for("not-a-real-user") not in {"hr", "admin"}:
        _fail(role_for("not-a-real-user"))


def test_staff_edit_keeps_dropdowns_and_other_cells():
    folder = ROOT / "_tmp" / "cloud-sheet"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "staff.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "BG & MD"
    sheet.append(["員工編號", "中文姓名", "職位"])
    sheet.append(["B001", "甲", "店員"])
    sheet.append(["B002", "乙", "師傅"])
    rule = DataValidation(type="list", formula1='"店員,師傅"', allow_blank=True)
    sheet.add_data_validation(rule)
    rule.add("C2:C10")
    book.save(path)
    before = load_workbook(path)
    validations = len(before["BG & MD"].data_validations.dataValidation)
    other = before["BG & MD"]["A3"].value
    before.close()
    edit_staff_sheet(path, "BG & MD", "B001", "甲", {"職位": "店長"}, "edit")
    after = load_workbook(path)
    if len(after["BG & MD"].data_validations.dataValidation) != validations:
        _fail("dropdowns were dropped")
    if after["BG & MD"]["C2"].value != "店長":
        _fail(after["BG & MD"]["C2"].value)
    if after["BG & MD"]["A3"].value != other or after["BG & MD"]["C3"].value != "師傅":
        _fail("another person changed")
    after.close()


def test_resign_adds_the_leave_date_column_when_the_sheet_has_none():
    folder = ROOT / "_tmp" / "cloud-sheet-leave"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "staff.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "內地勞工"
    sheet["C5"] = "員工編號"
    sheet["E5"] = "中文姓名"
    sheet["L5"] = "僱傭狀況"
    sheet["C8"] = "ESL009"
    sheet["E8"] = "甲"
    sheet["L8"] = "在職"
    sheet["V28"] = "note"
    book.save(path)
    book.close()
    edit_staff_sheet(
        path, "內地勞工", "ESL009", "甲",
        {"僱傭狀況": "已離職", "離職日期": "2026-11-27"}, "resign",
    )
    from payroll.staff.staff import _as_date, _read_sheet
    frame = _read_sheet(path, "內地勞工")
    row = frame[frame["員工編號"].map(lambda value: str(value).strip()) == "ESL009"].iloc[0]
    found = _as_date(row["離職日期"])
    if str(row["僱傭狀況"]).strip() != "已離職" or found is None or found.isoformat() != "2026-11-27":
        _fail((row["僱傭狀況"], row["離職日期"]))
    after = load_workbook(path)
    headers = [after["內地勞工"].cell(5, col).value for col in range(1, 30)]
    if "離職日期" not in headers or headers.index("離職日期") + 1 <= 22:
        _fail(headers)
    if after["內地勞工"]["V28"].value != "note":
        _fail(after["內地勞工"]["V28"].value)
    after.close()


def test_a_blank_first_column_can_still_be_edited():
    folder = ROOT / "_tmp" / "cloud-sheet-blank"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "staff.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "BG & MD"
    sheet["B5"] = "員工編號"
    sheet["C5"] = "中文姓名"
    sheet["D5"] = "僱傭狀況"
    sheet["E5"] = "離職日期"
    sheet["B16"] = "B094"
    sheet["C16"] = "甲"
    sheet["D16"] = "在職"
    book.save(path)
    book.close()
    edit_staff_sheet(path, "BG & MD", "B094", "甲", {"僱傭狀況": "已離職", "離職日期": "2026-11-21"}, "resign")
    after = load_workbook(path)
    if after["BG & MD"]["D16"].value != "已離職" or after["BG & MD"]["E16"].value != "2026-11-21":
        _fail((after["BG & MD"]["D16"].value, after["BG & MD"]["E16"].value))
    after.close()


if __name__ == "__main__":
    test_paths_keep_the_folder_boundary()
    test_hr_cannot_see_office_pay()
    test_unknown_role_is_hr_and_viewer_is_not_a_role()
    test_staff_edit_keeps_dropdowns_and_other_cells()
    test_resign_adds_the_leave_date_column_when_the_sheet_has_none()
    test_a_blank_first_column_can_still_be_edited()
    print("cloud ok")
