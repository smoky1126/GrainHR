"""Cache, safe Excel writes, aliases, the month checklist, and the pay audit."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = ROOT / "_tmp" / "improvements"
if HOME.exists():
    shutil.rmtree(HOME)
HOME.mkdir(parents=True)
COMPANY = HOME / "company.toml"
example = (ROOT / "company.example.toml").read_text(encoding="utf-8")
COMPANY.write_text(example.replace("private = false", "private = true"), encoding="utf-8")
os.environ["PAYROLL_HOME"] = str(HOME)
os.environ["PAYROLL_COMPANY"] = str(COMPANY)
os.environ.pop("PAYROLL_STAFF", None)
os.environ.pop("PAYROLL_DEMO", None)

import pandas as pd
from openpyxl import Workbook

from payroll.attendance.lateness import link_groups
from payroll.attendance.matching import unmatched_names
from payroll.attendance.today import _alias_punches
from payroll.core.aliases import set_name_alias
from payroll.core.config import parse_month
from payroll.core.excel_io import read_excel, save_excel
from payroll.core.settings import app_version, group_label, load, name_aliases, role_for, shop_label
from payroll.pay.review import apply_review
from payroll.staff.staff import clear_staff_cache, load_staff
from app.state import mark_late_checked, month_progress


def _fail(message):
    raise SystemExit(message)


def test_labels_and_roles():
    load.cache_clear()
    if shop_label("S5_Shop") != "Shop 5 retail":
        _fail(shop_label("S5_Shop"))
    if shop_label("not-a-shop") != "not-a-shop":
        _fail("unknown shop should stay unchanged")
    if group_label("bg_prod") != "Bakery A production":
        _fail(group_label("bg_prod"))
    if role_for("user") != "admin":
        _fail("named admin should stay admin")
    if role_for("someone-else") != "hr":
        _fail("a private company should treat an unknown person as hr")
    if app_version() != (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip():
        _fail(app_version())


def test_alias_links_a_roster_name():
    load.cache_clear()
    set_name_alias("甲", "B001")
    load.cache_clear()
    if name_aliases().get("甲") != "B001":
        _fail(name_aliases())
    set_name_alias("甲", "B002")
    if name_aliases().get("甲") != "B002":
        _fail("alias should replace the previous employee")
    staff = [{
        "employee_no": "B002", "name_zh": "甲", "name_en": "", "roster_hint": "",
        "department": "Bread", "employment": "全職", "position": "Baker", "sheet": "", "active": True,
    }]
    linked = link_groups(["甲"], staff, None, None)
    if linked["甲"]["employee_no"] != "B002":
        _fail(linked)
    roster_left, daka_left = unmatched_names(["甲", "乙"], ["甲", "丙"], linked)
    if roster_left != ["乙"] or daka_left != ["丙"]:
        _fail((roster_left, daka_left))
    punches = {("丙", "2026-10-01"): {"in": "09:12"}, "__names__": {"丙"}}
    set_name_alias("丙", "乙")
    copied = _alias_punches(punches, ["乙"])
    if copied.get(("乙", "2026-10-01"), {}).get("in") != "09:12":
        _fail(copied)


def test_excel_cache_and_replace():
    path = HOME / "book.xlsx"
    frame = pd.DataFrame([{"employee_no": "B001"}])
    save_excel(path, frame)
    if path.with_name(f".{path.name}.tmp").exists():
        _fail("temp workbook was left behind")
    first = read_excel(path)
    second = read_excel(path)
    if list(first["employee_no"]) != ["B001"] or list(second["employee_no"]) != ["B001"]:
        _fail("cached read changed the rows")
    save_excel(path, pd.DataFrame([{"employee_no": "B009"}]))
    third = read_excel(path)
    if list(third["employee_no"]) != ["B009"]:
        _fail("a new save should be read back")


def _staff_book(path, number):
    book = Workbook()
    first = book.active
    first.title = "BG & MD"
    second = book.create_sheet("內地勞工")
    for sheet in (first, second):
        sheet.append(["員工編號", "中文姓名", "僱傭狀況"])
    first.append([number, "甲", "在職"])
    book.save(path)


def test_staff_cache_follows_the_file():
    path = HOME / "Staff_info_test.xlsx"
    _staff_book(path, "B001")
    os.environ["PAYROLL_STAFF"] = str(path)
    clear_staff_cache()
    first = load_staff(path)
    second = load_staff(path)
    if list(first["employee_no"]) != ["B001"] or list(second["employee_no"]) != ["B001"]:
        _fail("staff cache returned the wrong person")
    if second.attrs.get("source") != str(path):
        _fail("staff cache dropped the source path")
    _staff_book(path, "B007")
    third = load_staff(path)
    if list(third["employee_no"]) != ["B007"]:
        _fail("staff cache kept the old file")


def test_month_checklist_and_audit():
    info = parse_month("2026-10")
    info["daka"].parent.mkdir(parents=True, exist_ok=True)
    info["daka"].write_text("name,date\n", encoding="utf-8")
    rows = dict(month_progress(info))
    if rows.get("DAKA 已上傳") is not True or rows.get("遲到已核對") is not False:
        _fail(rows)
    mark_late_checked(info)
    rows = dict(month_progress(info))
    if rows.get("遲到已核對") is not True:
        _fail(rows)
    adjustments = HOME / "adjustments.xlsx"
    save_excel(adjustments, sheets={
        "lines": pd.DataFrame([{"staff_id": "S1", "manual_delta": 0, "note": ""}]),
        "meta": pd.DataFrame([{"pay_date": ""}]),
    })
    apply_review({"key": "2026-10", "adjustments": adjustments}, [{
        "staff_id": "S1", "manual_delta": 12, "slip_name": "甲",
    }])
    audit = pd.read_excel(HOME / "data" / "payroll_audit.xlsx")
    hit = audit[audit["field"].astype(str).eq("manual_delta")]
    if len(hit) != 1 or str(hit.iloc[0]["new"]) not in {"12", "12.0"}:
        _fail(audit.to_dict("records"))
    if str(hit.iloc[0]["old"]) not in {"0", "0.0"}:
        _fail(hit.iloc[0].to_dict())
    apply_review({"key": "2026-10", "adjustments": adjustments}, [{
        "staff_id": "S1", "manual_delta": 12,
    }])
    again = pd.read_excel(HOME / "data" / "payroll_audit.xlsx")
    if len(again) != 1:
        _fail("the same adjustment was logged twice")


def test_log_file():
    from app.errors import log_path, write_log
    write_log("improvement check")
    text = log_path().read_text(encoding="utf-8")
    if "improvement check" not in text or log_path().name != "grainhr.log":
        _fail(text)


if __name__ == "__main__":
    test_labels_and_roles()
    test_alias_links_a_roster_name()
    test_excel_cache_and_replace()
    test_staff_cache_follows_the_file()
    test_month_checklist_and_audit()
    test_log_file()
    print("improvements ok")
