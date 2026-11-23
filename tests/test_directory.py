"""The staff page joins the staff file to salary and leave balances."""

from datetime import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("PAYROLL_HOME", None)

import pandas as pd

from payroll.core.config import parse_month, scratch_dir
from openpyxl import Workbook

from payroll.staff.directory import GROUPS, annual_entitlement, staff_directory, staff_group
from payroll.core.labels import BOOKS
from payroll.staff.leave_record import annual_leave_taken


def test_directory_lists_leavers_and_joins_pay():
    home = scratch_dir("directory")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        info = parse_month("2026-10")
        (home / "data").mkdir(parents=True)
        (home / "data" / "balances").mkdir()
        pd.DataFrame([
            {"employee_no": "B001", "staff_id": "243-1", "basic_salary": 20000},
        ]).to_excel(home / "data" / "pay_table.xlsx", index=False)
        pd.DataFrame([
            {"employee_no": "A002", "staff_id": "197-3", "basic_salary": 18000},
        ]).to_excel(home / "data" / "pay_table_admin.xlsx", index=False)
        pd.DataFrame([
            {"staff_id": "243-1", "al_1_label": "2025", "al_1_opening": 3, "al_2_label": "2026", "al_2_opening": 4, "opening_rest": 2},
        ]).to_excel(home / "data" / "balances" / "2026_10_close.xlsx", index=False)
        pd.DataFrame([
            {"staff_id": "197-3", "al_1_label": "2026", "al_1_opening": 8, "al_2_label": "", "al_2_opening": "", "opening_rest": 0},
        ]).to_excel(home / "data" / "balances" / "2026_10_close_admin.xlsx", index=False)
        staff = pd.DataFrame([
            {"employee_no": "A002", "name_zh": "甲會計", "name_en": "CHAN ADA", "status": "在職",
             "position": "Accounting Officer", "department": "Office - Administration", "employment": "全職",
             "join_date": datetime(2020, 7, 26), "leave_date": None},
            {"employee_no": "B001", "name_zh": "乙店員", "name_en": "CHEUNG ADA", "status": "在職",
             "position": "店員", "department": "Shop - Retail", "employment": "全職",
             "join_date": datetime(2024, 1, 1), "leave_date": None},
            {"employee_no": "A020", "name_zh": "丙文員", "name_en": "FUNG ADA", "status": "已離職",
             "position": "Clerk", "department": "Office - Administration", "employment": "全職",
             "join_date": datetime(2024, 5, 16), "leave_date": datetime(2025, 11, 14)},
        ])
        rows = {row["employee_no"]: row for row in staff_directory(info, staff)}
        if set(rows) != {"A002", "A020", "B001"}:
            raise SystemExit(f"missing people: {set(rows)}")
        if rows["A020"]["status"] != "已離職" or rows["A020"]["leave_date"] != "2025-11-14":
            raise SystemExit(f"leaver was dropped: {rows['A020']}")
        if rows["A020"]["salary"] is not None:
            raise SystemExit("a person off the pay table was given a salary")
        office = rows["A002"]
        if office["book"] != BOOKS["admin"] or office["salary"] != 18000 or office["annual"] != 8:
            raise SystemExit(f"office pay {office}")
        shop = rows["B001"]
        if shop["book"] != BOOKS["bg"] or shop["annual"] != 7 or shop["rest"] != 2:
            raise SystemExit(f"shop balance {shop}")
        if "2025 3" not in shop["annual_detail"] or shop["department"] != "Shop - Retail":
            raise SystemExit(f"shop detail {shop}")
        if office["position"] != "Accounting Officer" or office["join_date"] != "2020-07-26":
            raise SystemExit(f"staff file fields {office}")
        if office["group"] != "admin" or office["service"] != "6年3個月" or office["service_days"] != "6年3個月5日":
            raise SystemExit(f"office group {office['group']} {office['service']} {office['service_days']}")
        if shop["group"] != "bg_retail" or shop["service"] != "2年9個月" or shop["service_days"] != "2年9個月30日":
            raise SystemExit(f"shop group {shop['group']} {shop['service']} {shop['service_days']}")
        if rows["A020"]["group"] != "admin" or rows["A020"]["service"] != "1年5個月" or rows["A020"]["service_days"] != "1年5個月29日":
            raise SystemExit(f"leaver service {rows['A020']['group']} {rows['A020']['service']} {rows['A020']['service_days']}")
        if office["annual_entitled"] != 14 or shop["annual_entitled"] != 14 or rows["A020"]["annual_entitled"] != 12:
            raise SystemExit(
                f"entitlement office {office['annual_entitled']} shop {shop['annual_entitled']} leaver {rows['A020']['annual_entitled']}"
            )
    finally:
        os.environ.pop("PAYROLL_HOME", None)


def test_annual_leave_taken_from_holiday_record():
    home = scratch_dir("directory-leave")
    book = Workbook()
    january = book.active
    january.title = "2026 Jan"
    january.append(["January, 2026 Leave Record"])
    january.append([2026, "年", 1, "月"])
    january.append(["Name        Date", 1, 2])
    january.append(["員工"])
    january.append(["Office"])
    january.append(["Chan Ada_Ada", "AL", None])
    october = book.create_sheet("2026 Oct")
    october.append(["October, 2026 Leave Record"])
    october.append([2026, "年", 10, "月"])
    october.append(["Name        Date", 1])
    october.append(["Retail"])
    october.append(["Ada Two_Two", "AL 0.5"])
    october.append(["Someone Else_X", "AL"])
    october.append(["Other Person_Snow", "AL"])
    october.append(["甲錫", "AL 0.5"])
    path = home / "holiday.xlsx"
    book.save(path)
    os.environ["PAYROLL_HOME"] = str(home)
    os.environ["PAYROLL_HOLIDAY"] = str(path)
    try:
        staff = pd.DataFrame([
            {"employee_no": "A002", "name_zh": "甲會計", "name_en": "CHAN ADA"},
            {"employee_no": "B001", "name_zh": "乙店員", "name_en": "ADA TWO"},
            {"employee_no": "B090", "name_zh": "沒有假期", "name_en": "NO HOLIDAY"},
            {"employee_no": "R062", "name_zh": "丙小雪", "name_en": "OTHER PERSON", "roster_hint": "Snow"},
            {"employee_no": "ESL025", "name_zh": "甲鍚", "name_en": "JIA XI"},
        ])
        taken, through = annual_leave_taken(staff, 2026, 10)
        if through != 10 or taken["A002"] != 1 or taken["B001"] != 0.5 or taken.get("B090") is not None:
            raise SystemExit(f"leave taken {taken} through {through}")
        if taken["R062"] != 1 or taken["ESL025"] != 0.5:
            raise SystemExit(f"close names {taken}")
        taken, through = annual_leave_taken(staff, 2026, 1)
        if through != 1 or taken["A002"] != 1 or taken.get("B001") is not None:
            raise SystemExit(f"january only {taken} through {through}")
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        os.environ.pop("PAYROLL_HOLIDAY", None)


def test_annual_entitlement_steps():
    checks = [
        (datetime(2026, 3, 1), None, 2026, 10, 10),
        (datetime(2025, 11, 1), None, 2026, 10, 10),
        (datetime(2025, 1, 1), None, 2026, 10, 12),
        (datetime(2025, 10, 31), None, 2026, 10, 12),
        (datetime(2024, 11, 1), None, 2026, 10, 12),
        (datetime(2024, 10, 31), None, 2026, 10, 14),
        (datetime(2018, 1, 1), None, 2026, 10, 14),
        (datetime(2026, 11, 2), None, 2026, 10, 0),
        (None, None, 2026, 10, None),
    ]
    for joined, left, year, month, expected in checks:
        got = annual_entitlement(joined, left, year, month)
        if got != expected:
            raise SystemExit(f"entitlement {joined} -> {got}, expected {expected}")


def test_eight_groups_and_one_service_text():
    if len(GROUPS) != 8:
        raise SystemExit(f"expected eight groups, got {len(GROUPS)}")
    from payroll.core.settings import match_tokens
    second = (match_tokens() or ["Bakery B"])[0]
    retail = staff_group("S2 - Shop", "24個月", "售貨員", "內地勞工")
    pastry = staff_group(f"{second} shop", "12個月", "餅師", "內地勞工")
    shop = staff_group("Shop - Retail", "全職", "售貨員", "Both")
    if retail != "bg_esl" or pastry != "md_esl" or shop != "bg_retail":
        raise SystemExit(f"groups retail {retail} pastry {pastry} shop {shop}")
    home = scratch_dir("directory-groups")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        info = parse_month("2026-10")
        staff = pd.DataFrame([
            {"employee_no": "ESL030", "name_zh": "測試甲", "status": "在職", "sheet": "內地勞工",
             "department": "S2 - Shop", "employment": "24個月", "position": "售貨員",
             "join_date": datetime(2024, 6, 1)},
            {"employee_no": "ESL031", "name_zh": "測試乙", "status": "已離職", "sheet": "內地勞工",
             "department": f"{second} shop", "employment": "12個月", "position": "餅師",
             "join_date": datetime(2023, 1, 1), "leave_date": datetime(2026, 2, 1)},
        ])
        rows = {row["employee_no"]: row for row in staff_directory(info, staff)}
        counts = {}
        for key, _label in GROUPS:
            counts[key] = sum(row["group"] == key for row in rows.values())
        if counts["bg_esl"] != 1 or counts["md_esl"] != 1:
            raise SystemExit(f"group counts {counts}")
        if rows["ESL030"]["service_days"] != rows["ESL030"]["service"] and "日" not in rows["ESL030"]["service_days"]:
            raise SystemExit(f"service text {rows['ESL030']['service_days']}")
        if rows["ESL030"]["service"] == rows["ESL030"]["service_days"]:
            raise SystemExit("在職日數 should add the day count onto 年資")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


if __name__ == "__main__":
    test_directory_lists_leavers_and_joins_pay()
    test_annual_leave_taken_from_holiday_record()
    test_annual_entitlement_steps()
    test_eight_groups_and_one_service_text()
    print("directory ok")
