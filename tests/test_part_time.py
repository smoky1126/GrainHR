"""Part-time pay is hours x rate, and the two companies stay apart."""

from datetime import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("PAYROLL_HOME", None)
os.environ.pop("PAYROLL_DEMO", None)

import pandas as pd
from openpyxl import load_workbook

from payroll.core.config import parse_month, scratch_dir
from payroll.pay.part_time import (
    build_pt, pt_reference, save_pt_lines, set_pt_reference, summary_book,
)


def _staff_row(number, zh, en, hint, department, form, joined, status="在職"):
    return {
        "employee_no": number,
        "name_zh": zh,
        "name_en": en,
        "roster_hint": hint,
        "department": department,
        "position": "",
        "join_date": joined,
        "leave_date": None,
        "status": status,
        "employment": form,
        "part_time": form == "兼職",
    }


def _facts(rows):
    return pd.DataFrame(rows, columns=["name", "date", "roster"])


def _by_number(rows):
    return {row["employee_no"]: row for row in rows}


def test_hours_rate_and_mpf():
    from payroll.core.settings import match_tokens
    second = (match_tokens() or ["Bakery B"])[0]
    info = parse_month("2026-10")
    staff = pd.DataFrame([
        _staff_row("R1", "甲", "PERSON A", "Kelly", "Shop - Retail", "兼職", datetime(2020, 1, 5)),
        _staff_row("R2", "乙", "PERSON B", "乙", f"{second} shop", "兼職", datetime(2026, 9, 7)),
        _staff_row("R3", "丙", "PERSON C", "Tiffany", "Shop - Retail", "兼職", datetime(2025, 12, 29)),
        _staff_row("R4", "丁", "PERSON D", "KK", "Make - Bread", "兼職", datetime(2025, 4, 29)),
        _staff_row("R5", "全職", "FULL", "Full", "Shop - Retail", "全職", datetime(2020, 1, 1)),
        _staff_row("R6", "戊", "PERSON E", "Kelly", "", "兼職", datetime(2020, 1, 1)),
    ])
    days = []
    for day in (1, 3, 4, 10, 11, 17, 18, 19, 25):
        days.append({"name": "Kelly (PT)", "date": datetime(2026, 10, day), "roster": "07:30-17:00"})
    days.append({"name": "Kelly (PT)", "date": datetime(2026, 10, 2), "roster": "休假"})
    for day in range(1, 22):
        days.append({"name": "乙 (PT)", "date": datetime(2026, 10, day), "roster": "09:00-17:00"})
    days.append({"name": "Tiffany (PT)", "date": datetime(2026, 10, 8), "roster": "08:30-14:00"})
    days.append({"name": "全職", "date": datetime(2026, 10, 1), "roster": "09:00-18:30"})
    lines = pd.DataFrame([
        {"employee_no": "R1", "rate": 65, "scheme": "mpf", "extra_hours": 0, "pay_this": "Y"},
        {"employee_no": "R2", "rate": 60, "scheme": "mpf", "extra_hours": 0, "pay_this": "Y"},
        {"employee_no": "R3", "rate": 65, "scheme": "mpf", "extra_hours": -0.5, "extra_note": "無薪休息", "pay_this": "Y"},
        {"employee_no": "R4", "rate": 65, "scheme": "none", "extra_hours": 0, "pay_this": "Y"},
        {"employee_no": "R6", "rate": 60, "scheme": "mpf", "extra_hours": 0, "pay_this": "N"},
    ])
    # Give KK one shift so scheme none is visible, and Tiffany only the short day plus the adjustment.
    days.append({"name": "KK (PT)", "date": datetime(2026, 10, 4), "roster": "09:00-18:30"})
    rows = _by_number(build_pt(info, staff, _facts(days), lines))
    if "R5" in rows:
        raise SystemExit("full-time staff was included in part-time pay")
    kelly = rows["R1"]
    if kelly["company"] != "bg" or abs(kelly["hours"] - 85.5) > 0.001:
        raise SystemExit(f"Kelly hours {kelly['hours']} company {kelly['company']}")
    if abs(kelly["salary"] - 5557.5) > 0.001 or abs(kelly["employer_mpf"] - 277.88) > 0.001:
        raise SystemExit(f"Kelly pay {kelly['salary']} employer {kelly['employer_mpf']}")
    if kelly["employee_mpf"] != 0 or abs(kelly["transfer"] - 5557.5) > 0.001:
        raise SystemExit(f"Kelly employee MPF {kelly['employee_mpf']} transfer {kelly['transfer']}")
    qin = rows["R2"]
    if qin["company"] != "md" or abs(qin["hours"] - 168) > 0.001:
        raise SystemExit(f"person B hours {qin['hours']} company {qin['company']}")
    if abs(qin["salary"] - 10080) > 0.001 or abs(qin["employer_mpf"] - 504) > 0.001 or qin["employee_mpf"] != 0:
        raise SystemExit(f"person B MPF employer {qin['employer_mpf']} employee {qin['employee_mpf']}")
    tiffany = rows["R3"]
    if abs(tiffany["total_hours"] - 5) > 0.001 or abs(tiffany["salary"] - 325) > 0.001:
        raise SystemExit(f"extra hours became {tiffany['total_hours']} salary {tiffany['salary']}")
    kk = rows["R4"]
    if kk["employer_mpf"] != 0 or kk["employee_mpf"] != 0 or abs(kk["salary"] - 617.5) > 0.001:
        raise SystemExit(f"scheme none still charged MPF {kk}")
    if rows["R6"]["hours"] != 0 or rows["R6"]["transfer"] != 0:
        raise SystemExit("the second Kelly took the hours, or 不出糧 still paid")
    if 2 in kelly["days"]:
        raise SystemExit("a rest day was counted")


def test_summary_keeps_the_companies_apart():
    info = parse_month("2026-10")
    rows = [
        {"company": "bg", "name_en": "PERSON A", "name_zh": "甲", "hint": "Kelly", "shop": "S2",
         "join_date": datetime(2020, 1, 5).date(), "pay_this": "Y", "days": {1: 9.5}, "extra_hours": 0,
         "extra_note": "", "hours": 9.5, "total_hours": 9.5, "rate": 65, "salary": 617.5,
         "employer_mpf": 30.88, "employee_mpf": 0, "transfer": 617.5, "bank": "HSBC", "account": "1"},
        {"company": "md", "name_en": "PERSON B", "name_zh": "乙", "hint": "", "shop": "B2",
         "join_date": None, "pay_this": "Y", "days": {2: 8}, "extra_hours": 0, "extra_note": "",
         "hours": 8, "total_hours": 8, "rate": 65, "salary": 520, "employer_mpf": 26,
         "employee_mpf": 26, "transfer": 494, "bank": "BOC", "account": "2"},
    ]
    bg = summary_book(info, "bg", rows, "NB-BG")
    md = summary_book(info, "md", rows, "NB-MD")
    bg_book = load_workbook(pd.io.common.BytesIO(bg))
    md_book = load_workbook(pd.io.common.BytesIO(md))
    bg_text = " ".join(str(cell.value) for row in bg_book.active.iter_rows() for cell in row if cell.value)
    md_text = " ".join(str(cell.value) for row in md_book.active.iter_rows() for cell in row if cell.value)
    if "NB-BG" not in bg_text or "PERSON A" not in bg_text or "乙" in bg_text:
        raise SystemExit("BG summary mixed the companies or dropped the transaction number")
    if "NB-MD" not in md_text or "乙" not in md_text or "PERSON A" in md_text:
        raise SystemExit("MD summary mixed the companies or dropped the transaction number")
    bg_book.close()
    md_book.close()


def test_saved_rate_is_kept():
    home = scratch_dir("pt-save")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        info = parse_month("2026-11")
        info["system"].mkdir(parents=True, exist_ok=True)
        save_pt_lines(info, [{
            "employee_no": "R1", "rate": 65, "scheme": "不扣強積金", "extra_hours": -0.5,
            "extra_note": "休息", "bank": "HSBC", "account": "006", "pay_this": "否",
        }])
        set_pt_reference(info, "bg", "NB-BG-PT")
        set_pt_reference(info, "md", "NB-MD-PT")
        if pt_reference(info, "bg") != "NB-BG-PT" or pt_reference(info, "md") != "NB-MD-PT":
            raise SystemExit("the two transaction numbers were not stored apart")
        staff = pd.DataFrame([
            _staff_row("R1", "甲", "PERSON A", "Kelly", "Shop - Retail", "兼職", datetime(2020, 1, 5)),
        ])
        row = build_pt(info, staff, _facts([]))[0]
        if row["rate"] != 65 or row["scheme"] != "none" or row["pay_this"] != "N" or row["extra_hours"] != -0.5:
            raise SystemExit(f"saved part-time row was not read back: {row}")
        if pt_reference(info, "bg") != "NB-BG-PT":
            raise SystemExit("saving a person wiped the transaction number")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


if __name__ == "__main__":
    test_hours_rate_and_mpf()
    test_summary_keeps_the_companies_apart()
    test_saved_rate_is_kept()
    print("part-time ok")
