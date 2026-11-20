"""The second book, the office payroll, a mid-month leaver, and grey staff rows."""

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_packages"))
os.chdir(ROOT)
os.environ.pop("PAYROLL_HOME", None)
os.environ.pop("PAYROLL_DEMO", None)
os.environ.pop("PAYROLL_STAFF", None)

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import Color

from payroll.core.config import book_info, parse_month, scratch_dir
from payroll.documents.parse_admin import parse_admin
from payroll.documents.parse_slips import parse_slips
from payroll.pay.payroll import build_draft
from payroll.setup.regression import pay_differences
from payroll.documents.slips import fill_document
from payroll.documents.slips_admin import fill_admin
from payroll.staff.staff import employed_in, grey_but_employed, load_staff
from payroll.core.labels import BOOKS
from payroll.core.settings import varying_pay
BG, MD, OFFICE = BOOKS['bg'], BOOKS['md'], BOOKS['admin']


def _hold_slip_bonus(info, draft, slips):
    """The October slips printed a bonus every month. Hold that amount, then the caller restores the file."""
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    lines["staff_id"] = lines["staff_id"].map(lambda value: "" if pd.isna(value) else str(value).strip())
    changed = False
    for slip in slips:
        if slip.get("bonus") is None:
            continue
        rows = draft[draft["staff_id"].astype(str) == slip["staff_id"]]
        if rows.empty:
            continue
        if abs(float(rows.iloc[0].bonus or 0) - float(slip["bonus"])) <= 0.02:
            continue
        lines.loc[lines["staff_id"] == slip["staff_id"], "bonus_override"] = slip["bonus"]
        changed = True
    if not changed:
        return
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)


def _october():
    info = parse_month("2026-10")
    md_info = book_info(info, "md")
    saved = md_info["adjustments"].read_bytes()
    try:
        md = build_draft(md_info, write=False)
        md_slips = parse_slips(next((ROOT / "Oct_2026" / "MD").glob("*#243*.docx")))
        _hold_slip_bonus(md_info, md, md_slips)
        md = build_draft(md_info, write=False)
        problems = pay_differences(md, md_slips)
        if problems:
            raise SystemExit(MD + " draft:\n" + "\n".join(problems))
        filled = fill_document(md_info, md)
        again = pay_differences(md, parse_slips(filled))
        if again:
            raise SystemExit(MD + " slips:\n" + "\n".join(again))
    finally:
        md_info["adjustments"].write_bytes(saved)

    admin_info = book_info(info, "admin")
    admin = build_draft(admin_info, write=False)
    admin_slips = parse_admin(ROOT / "Oct_2026" / "Admin" / "#197_0_office.xlsx")
    problems = pay_differences(admin, admin_slips)
    if problems:
        raise SystemExit("admin draft:\n" + "\n".join(problems))
    filled = fill_admin(admin_info, admin)
    again = pay_differences(admin, parse_admin(filled))
    if again:
        raise SystemExit("admin slips:\n" + "\n".join(again))
    from payroll.staff.staff import pay_table_path
    office = pd.read_excel(pay_table_path("admin"))
    linked = {
        "Chan Ka Lok 陳家樂": "James Chan",
        "Yeung Yuen Ting 楊宛婷": "Alice Yeung",
        "Lee Ka Chun 李嘉俊": "Sam Lee",
        "Leung Hiu Man 梁曉雯": "Carmen Leung",
        "Leung Wing Yee 梁穎儀": "Milly Leung",
        "Tung Wai Lam 童瑋琳": "Shirley Tung",
    }
    for slip_name, roster_name in linked.items():
        rows = office[office["slip_name"].astype(str) == slip_name]
        if rows.empty or str(rows.iloc[0]["roster_name"]).strip() != roster_name:
            raise SystemExit(f"{slip_name} should link to {roster_name}, got {rows.to_dict('records')}")
    for boss in varying_pay():
        rows = office[office["slip_name"].astype(str).str.contains(boss)]
        if rows.empty or str(rows.iloc[0]["roster_name"]).strip() not in {"", "nan"}:
            raise SystemExit(f"{boss} should stay unlinked: {rows.to_dict('records')}")
    print("october books ok")


def _staff_book(path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BG & MD"
    headers = ["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"]
    sheet.append(headers)
    sheet.append(["T001", "測試員", "Tester", "", "", datetime(2020, 1, 1), datetime(2026, 10, 14), "已離職", "全職"])
    sheet.append(["T002", "下月入職", "Later", "", "", datetime(2026, 11, 2), None, "在職", "全職"])
    other = book.create_sheet("內地勞工")
    other.append(headers)
    book.save(path)


def _leaver():
    home = scratch_dir("leaver")
    os.environ["PAYROLL_HOME"] = str(home)
    os.environ["PAYROLL_STAFF"] = str(home / "staff.xlsx")
    try:
        _staff_book(home / "staff.xlsx")
        data = home / "data"
        data.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{
            "employee_no": "T001",
            "staff_id": "243-1",
            "slip_name": "測試員",
            "roster_name": "測試員",
            "basic_salary": 20000,
            "scheme": "mpf",
            "rent_rate": 0,
            "rent_base": "basic",
            "water": 0,
            "bonus_eligible": 1,
            "rest_days_month": 0,
            "allowance_desc": "",
            "allowance_amount": 0,
            "allowance_note": "",
            "allowance_section": "",
        }]).to_excel(data / "pay_table.xlsx", index=False)
        info = parse_month("2026-10")
        info["folder"].mkdir(parents=True, exist_ok=True)
        info["system"].mkdir(parents=True, exist_ok=True)
        rows = []
        punches = ["姓名,日期,上班,下班"]
        for day in range(1, 32):
            rows.append({
                "name": "測試員", "date": datetime(2026, 10, day),
                "roster": "09:00-18:30", "shop": "TW_Bread", "wrong_site": 0,
            })
            if day <= 14:
                punches.append(f"測試員,2026-10-{day:02d},09:00,18:30")
        pd.DataFrame(rows).to_excel(info["system"] / "daily_facts.xlsx", index=False)
        info["daka"].write_text("\n".join(punches), encoding="utf-8")
        draft = build_draft(info, write=False)
        row = draft[draft["staff_id"].astype(str) == "243-1"].iloc[0]
        expected = {"basic_salary": 9032.26, "mpf_employee": 451.61, "net": 8580.65, "bonus": 0}
        for key, value in expected.items():
            if abs(float(row[key]) - value) > 0.001:
                raise SystemExit(f"leaver {key} is {row[key]}, expected {value}")
        missing = str(row["missing_text"])
        if "15/10" in missing or "31/10" in missing:
            raise SystemExit(f"days after leaving were still checked: {missing}")
        staff = load_staff()
        flags = employed_in(staff, info)
        later = staff[staff["employee_no"].astype(str) == "T002"].index[0]
        if bool(flags.loc[later]):
            raise SystemExit("a person joining next month was treated as employed")
        print("leaver ok")
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        os.environ.pop("PAYROLL_STAFF", None)


def _grey():
    folder = scratch_dir("grey")
    path = folder / "staff.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "BG & MD"
    sheet.append(["員工編號", "中文姓名", "僱傭狀況"])
    sheet.append(["G1", "灰色在職", "在職"])
    sheet.append(["W1", "白色在職", "在職"])
    sheet.append(["G2", "灰色已離職", "已離職"])
    sheet.append(["P1", "淺色在職", "在職"])
    grey = PatternFill(fill_type="solid", fgColor=Color(theme=6, tint=0.4))
    pale = PatternFill(fill_type="solid", fgColor=Color(theme=6, tint=0))
    for col in range(1, 4):
        sheet.cell(2, col).fill = grey
        sheet.cell(4, col).fill = grey
        sheet.cell(5, col).fill = pale
    book.save(path)
    found = grey_but_employed(path)
    numbers = [item["employee_no"] for item in found]
    if numbers != ["G1"]:
        raise SystemExit(f"grey rows: {found}")
    print("grey ok")


def _autopay_by_id(path):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from payroll.documents.parse_slips import FILE_NO

    document = Document(path)
    current = ""
    found = {}
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            blob = "".join(node.text or "" for node in child.iter(qn("w:t")))
            match = FILE_NO.search(blob)
            if match:
                current = f"{match.group(1)}-{match.group(2)}"
            continue
        if child.tag != qn("w:p"):
            continue
        text = Paragraph(child, document).text
        if "自動轉" in text and current:
            found.setdefault(current, text)
    return found


def _admin_autopay(path):
    from openpyxl import load_workbook

    slips = parse_admin(path)
    book = load_workbook(path)
    sheet = book.active
    salary, allowance = [], []
    for slip in slips:
        start, end = slip["anchors"]["start"], slip["anchors"]["end"]
        section = "salary"
        for excel_row in range(start, end):
            for col in range(1, 14):
                value = sheet.cell(excel_row, col).value
                text = "" if value is None else str(value).strip()
                if text == "Allowance" or text.startswith("Allowance "):
                    section = "allowance"
                if text.startswith("Salary Slip") or text.startswith("Basic Salary"):
                    section = "salary"
                if isinstance(value, str) and value.startswith("By Auto Pay"):
                    (allowance if section == "allowance" else salary).append(value)
    book.close()
    return salary, allowance


def _person_ref(path, staff_id, reference):
    lines = pd.read_excel(path, sheet_name="lines", dtype={"staff_id": str})
    meta = pd.read_excel(path, sheet_name="meta")
    lines["staff_id"] = lines["staff_id"].map(lambda value: "" if pd.isna(value) else str(value).strip())
    if "salary_reference" not in lines.columns:
        lines["salary_reference"] = ""
    lines.loc[lines["staff_id"] == staff_id, "salary_reference"] = reference
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)


def _references():
    from payroll.pay.review import apply_pay_date
    from payroll.documents.slips_admin import fill_admin
    from payroll.staff.staff import set_refs

    info = parse_month("2026-10")
    saved = {}
    books = {
        "bg": info,
        "md": book_info(info, "md"),
        "admin": book_info(info, "admin"),
    }
    for booked in books.values():
        saved[booked["book"]] = booked["adjustments"].read_bytes()
    try:
        for booked in books.values():
            apply_pay_date(booked, "5 Dec 2026")
            set_refs(booked, "NB-TEST-SAL", "NB-TEST-ALL")
        md_lines = pd.read_excel(books["md"]["adjustments"], sheet_name="lines", dtype={"staff_id": str})
        personal = str(md_lines.iloc[0]["staff_id"]).strip()
        _person_ref(books["md"]["adjustments"], personal, "NB-PERSON")
        md = build_draft(books["md"], write=False)
        filled = fill_document(books["md"], md)
        by_id = _autopay_by_id(filled)
        own = by_id.get(personal, "")
        if "NB-PERSON" not in own or "05 DEC 26" not in own:
            raise SystemExit(f"{MD} personal line: {own!r}")
        others = [text for staff_id, text in by_id.items() if staff_id != personal]
        if not others or any("NB-TEST-SAL" not in text or "05 DEC 26" not in text for text in others):
            raise SystemExit(f"{MD} shared lines: {others[:2]!r}")
        if any("NB039" in text or "HC126" in text for text in by_id.values()):
            raise SystemExit(MD + " kept an old 交易編號")
        bg = build_draft(info, write=False)
        bg_doc = fill_document(info, bg)
        bg_lines = list(_autopay_by_id(bg_doc).values())
        if not bg_lines or any("NB-TEST-SAL" not in text or "5 Dec 2026" not in text for text in bg_lines):
            raise SystemExit(f"{BG} autopay: {bg_lines[:1]!r}")
        admin = build_draft(books["admin"], write=False)
        admin_doc = fill_admin(books["admin"], admin)
        salary_lines, allowance_lines = _admin_autopay(admin_doc)
        if not salary_lines or any("NB-TEST-SAL" not in text or "5 Dec 2026" not in text for text in salary_lines):
            raise SystemExit(f"寫字樓 salary line: {salary_lines[:1]!r}")
        if not allowance_lines or any("NB-TEST-ALL" not in text for text in allowance_lines):
            raise SystemExit(f"寫字樓 allowance line: {allowance_lines[:1]!r}")
        if any("NB049" in text for text in salary_lines + allowance_lines):
            raise SystemExit("寫字樓 kept an old 交易編號")
        print("references ok")
    finally:
        for key, booked in books.items():
            booked["adjustments"].write_bytes(saved[key])


def _ot_memo():
    from payroll.pay.payroll import suggest_ot

    sample = suggest_ot({"ot_dates": [], "early_dates": "1/10 31分鐘"})
    if sample != "OT (Hours): 0 \u2013 1 = -1\n1/10 已補1":
        raise SystemExit(f"31 minutes should round up to 1 hour: {sample!r}")
    home = scratch_dir("otmemo")
    os.environ["PAYROLL_HOME"] = str(home)
    os.environ["PAYROLL_STAFF"] = str(home / "staff.xlsx")
    try:
        book = Workbook()
        sheet = book.active
        sheet.title = "BG & MD"
        sheet.append(["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"])
        sheet.append(["T100", "甲", "A", "", "", datetime(2020, 1, 1), None, "在職", "全職"])
        sheet.append(["B026", "乙", "B", "", "", datetime(2020, 1, 1), None, "在職", "全職"])
        book.create_sheet("內地勞工").append(["員工編號"])
        book.save(home / "staff.xlsx")
        data = home / "data"
        data.mkdir(parents=True, exist_ok=True)
        people = []
        for employee_no, name in (("T100", "甲"), ("B026", "乙")):
            people.append({
                "employee_no": employee_no, "staff_id": f"243-{employee_no}", "slip_name": name,
                "roster_name": name, "basic_salary": 20000, "scheme": "mpf", "rent_rate": 0,
                "rent_base": "basic", "water": 0, "bonus_eligible": 1, "rest_days_month": 0,
                "allowance_desc": "", "allowance_amount": 0, "allowance_note": "", "allowance_section": "",
            })
        pd.DataFrame(people).to_excel(data / "pay_table.xlsx", index=False)
        info = parse_month("2026-10")
        info["folder"].mkdir(parents=True, exist_ok=True)
        info["system"].mkdir(parents=True, exist_ok=True)
        facts = []
        punches = ["姓名,日期,上班,下班"]
        for name in ("甲", "乙"):
            for day, end in ((8, "17:36"), (12, "18:30")):
                facts.append({
                    "name": name, "date": datetime(2026, 10, day),
                    "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
                })
                punches.append(f"{name},2026-10-{day:02d},09:00,{end}")
        pd.DataFrame(facts).to_excel(info["system"] / "daily_facts.xlsx", index=False)
        info["daka"].write_text("\n".join(punches), encoding="utf-8")
        draft = build_draft(info, write=False)
        normal = draft[draft["employee_no"].astype(str) == "T100"].iloc[0]["ot_suggest"]
        expected = "OT (Hours): 0.5 \u2013 0.5 = 0\n12/10 : 0.5\n8/10 已補0.5"
        if normal != expected:
            raise SystemExit(f"OT memo:\n{normal}\nexpected:\n{expected}")
        manual = draft[draft["employee_no"].astype(str) == "B026"].iloc[0]["ot_suggest"]
        if str(manual).strip() not in {"", "nan"}:
            raise SystemExit(f"injury case should not get an OT memo: {manual!r}")
        print("ot memo ok")
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        os.environ.pop("PAYROLL_STAFF", None)


def _report():
    import re
    from openpyxl import load_workbook
    from payroll.core.labels import chinese_note
    from payroll.documents.report import write_report

    translated = chinese_note("attendance bonus on the slip is 1000.0, rule gives 0.0")
    if translated != "舊糧單有勤工獎 $1000.0，但按規則應為 $0.0，已沿用舊糧單金額。":
        raise SystemExit(f"chinese_note did not translate the bonus note: {translated}")
    info = parse_month("2026-10")
    path = write_report(info)
    book = load_workbook(path, read_only=True)
    names = set(book.sheetnames)
    for required in ("開始", BG, MD, OFFICE, "不在糧單", "每日紀錄"):
        if required not in names:
            book.close()
            raise SystemExit(f"report is missing {required}: {book.sheetnames}")
    if "全部數字" in names or "審核" in names:
        book.close()
        raise SystemExit(f"old sheet still in the report: {book.sheetnames}")
    found = False
    for title in (BG, MD, OFFICE, "不在糧單", "每日紀錄"):
        headers = next(book[title].iter_rows(max_row=1, values_only=True))
        for heading in headers:
            if heading and re.search(r"[A-Za-z]", str(heading)):
                book.close()
                raise SystemExit(f"{title} heading is not Chinese: {heading}")
        if title == BG and ("本月勤工獎" not in headers or "本季發放" not in headers):
            book.close()
            raise SystemExit(f"bonus columns missing: {headers}")
        if title != BG:
            continue
        problem_at = list(headers).index("問題")
        for row in book[title].iter_rows(min_row=2, values_only=True):
            problem = "" if row[problem_at] is None else str(row[problem_at])
            if "attendance bonus" in problem or "rule gives" in problem:
                book.close()
                raise SystemExit(f"English note still in the report: {problem}")
            if "舊糧單有勤工獎" in problem:
                found = True
    book.close()
    if not found:
        raise SystemExit("the report did not show the translated bonus note")
    print("report ok")


def _bonus_rule():
    from payroll.attendance.days import memo_source
    from payroll.core.money import attendance_bonus

    if memo_source("09:00-18:00", "09:00", "18:30") != "加班 0.5":
        raise SystemExit(f"OT source was {memo_source('09:00-18:00', '09:00', '18:30')}")
    if memo_source("09:00-18:00", "09:00", "17:36") != "已補 0.5":
        raise SystemExit(f"early source was {memo_source('09:00-18:00', '09:00', '17:36')}")
    checks = [
        (attendance_bonus(True, 0, 0, 0, 0, None, month=10), 1000, "October earns it"),
        (attendance_bonus(True, 0, 0, 0, 0, None, month=3), 1000, "March"),
        (attendance_bonus(True, 5, 0, 0, 0, None, month=6), 1000, "5 minutes"),
        (attendance_bonus(True, 6, 0, 0, 0, None, month=6), 0, "6 minutes"),
        (attendance_bonus(True, 0, 10, 0, 0, None, month=9), 0, "early leave"),
        (attendance_bonus(False, 0, 0, 0, 0, None, month=12), 0, "ineligible"),
        (attendance_bonus(True, 0, 0, 0, 0, 1000, month=10), 1000, "override"),
    ]
    for got, expected, label in checks:
        if abs(float(got) - expected) > 0.001:
            raise SystemExit(f"{label} bonus is {got}, expected {expected}")

    home = scratch_dir("bonus")
    os.environ["PAYROLL_HOME"] = str(home)
    os.environ["PAYROLL_STAFF"] = str(home / "staff.xlsx")
    try:
        book = Workbook()
        sheet = book.active
        sheet.title = "BG & MD"
        sheet.append(["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"])
        people = [
            ("M1", "全勤", "全職", "mpf"),
            ("M2", "租金", "全職", "rent"),
            ("M3", "遲到", "全職", "mpf"),
            ("M4", "五分鐘", "全職", "mpf"),
            ("M5", "早退", "全職", "mpf"),
            ("M6", "兼職", "兼職", "mpf"),
        ]
        for number, name, form, _scheme in people:
            sheet.append([number, name, name, "", "", datetime(2020, 1, 1), None, "在職", form])
        other = book.create_sheet("內地勞工")
        other.append(["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"])
        book.save(home / "staff.xlsx")
        data = home / "data"
        data.mkdir(parents=True, exist_ok=True)
        rows = []
        clocks = {
            "全勤": ("09:00", "18:00"),
            "租金": ("09:00", "18:00"),
            "遲到": ("09:06", "18:00"),
            "五分鐘": ("09:05", "18:00"),
            "早退": ("09:00", "17:40"),
            "兼職": ("09:00", "18:00"),
        }
        for index, (number, name, _form, scheme) in enumerate(people, start=1):
            rows.append({
                "employee_no": number, "staff_id": f"243-{index}", "slip_name": name, "roster_name": name,
                "basic_salary": 20000, "scheme": scheme, "rent_rate": 0.1 if scheme == "rent" else 0,
                "rent_base": "basic", "water": 0, "bonus_eligible": 1, "rest_days_month": 0,
                "allowance_desc": "", "allowance_amount": 0, "allowance_note": "", "allowance_section": "",
            })
        pd.DataFrame(rows).to_excel(data / "pay_table.xlsx", index=False)
        pd.DataFrame([rows[0]]).to_excel(data / "pay_table_admin.xlsx", index=False)
        info = parse_month("2026-03")
        info["folder"].mkdir(parents=True, exist_ok=True)
        info["system"].mkdir(parents=True, exist_ok=True)
        facts = []
        punches = ["姓名,日期,上班,下班"]
        for day in range(1, 32):
            for name, (start, end) in clocks.items():
                facts.append({
                    "name": name, "date": datetime(2026, 3, day),
                    "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
                })
                punches.append(f"{name},2026-03-{day:02d},{start},{end}")
        pd.DataFrame(facts).to_excel(info["system"] / "daily_facts.xlsx", index=False)
        info["daka"].write_text("\n".join(punches), encoding="utf-8")
        draft = build_draft(info, write=False)
        expected = {"243-1": 1000, "243-2": 0, "243-3": 0, "243-4": 1000, "243-5": 0, "243-6": 0}
        for staff_id, bonus in expected.items():
            row = draft[draft["staff_id"].astype(str) == staff_id].iloc[0]
            if abs(float(row.bonus or 0) - bonus) > 0.001:
                raise SystemExit(f"{staff_id} {row.slip_name} bonus is {row.bonus}, expected {bonus}")
        admin = build_draft(book_info(info, "admin"), write=False)
        office = admin[admin["staff_id"].astype(str) == "243-1"].iloc[0]
        if abs(float(office.bonus or 0)) > 0.001:
            raise SystemExit(f"office bonus is {office.bonus}, expected 0")
        print("bonus rule ok")
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        os.environ.pop("PAYROLL_STAFF", None)


def _pay_row(number, name, staff_id, scheme="mpf", rest=4, roster=None):
    return {
        "employee_no": number, "staff_id": staff_id, "slip_name": name,
        "roster_name": name if roster is None else roster,
        "basic_salary": 20000, "scheme": scheme, "rent_rate": 0.1 if scheme == "rent" else 0,
        "rent_base": "basic", "water": 0, "bonus_eligible": 1, "rest_days_month": rest,
        "allowance_desc": "", "allowance_amount": 0, "allowance_note": "", "allowance_section": "",
    }


def _write_month(info, people, days):
    """people: name -> (clock in, clock out) or 'sick' or 'miss' or a set of miss days."""
    facts = []
    punches = ["姓名,日期,上班,下班"]
    for day in range(1, days + 1):
        for name, kind in people.items():
            if kind == "off":
                continue
            miss_days = kind if isinstance(kind, set) else set()
            if kind == "sick" and day == 1:
                facts.append({
                    "name": name, "date": datetime(info["year"], info["month"], day),
                    "roster": "病假", "shop": "TW_Bread", "wrong_site": 0,
                })
                continue
            if kind == "miss" or day in miss_days:
                facts.append({
                    "name": name, "date": datetime(info["year"], info["month"], day),
                    "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
                })
                continue
            start, end = ("09:06", "18:00") if kind == "late" else ("09:00", "18:00")
            if isinstance(kind, tuple):
                start, end = kind
            facts.append({
                "name": name, "date": datetime(info["year"], info["month"], day),
                "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
            })
            punches.append(f"{name},{info['year']}-{info['month']:02d}-{day:02d},{start},{end}")
    info["folder"].mkdir(parents=True, exist_ok=True)
    info["system"].mkdir(parents=True, exist_ok=True)
    pd.DataFrame(facts).to_excel(info["system"] / "daily_facts.xlsx", index=False)
    info["daka"].write_text("\n".join(punches), encoding="utf-8")


def _rules():
    import calendar
    from payroll.core.money import overtime_pay
    from payroll.pay.payroll import write_closing
    from payroll.pay.review import save_one
    from payroll.documents.slips import keep_person
    from payroll.core.names import match_roster_name

    if match_roster_name("Leung Hiu Man 梁曉雯", "", "", ["Carmen Leung"]) != "Carmen Leung":
        raise SystemExit("office nickname did not match 梁曉雯")
    if match_roster_name("Li Ting Yan Andrew " + varying_pay()[0], "", "", ["James Chan", "Carmen Leung"]):
        raise SystemExit("a boss should not match an office roster name")

    home = scratch_dir("rules")
    os.environ["PAYROLL_HOME"] = str(home)
    os.environ["PAYROLL_STAFF"] = str(home / "staff.xlsx")
    try:
        import payroll.pay.payroll as engine
        engine._EARNED.clear()
        engine._EARLIER_DRAFTS.clear()
        book = Workbook()
        sheet = book.active
        sheet.title = "BG & MD"
        sheet.append(["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"])
        people = [
            ("C1", "全勤", datetime(2020, 1, 1), None, "在職"),
            ("C2", "七月", datetime(2020, 1, 1), None, "在職"),
            ("C3", "新入", datetime(2026, 9, 10), None, "在職"),
            ("C4", "離職", datetime(2020, 1, 1), datetime(2026, 8, 15), "已離職"),
            ("C5", "病假", datetime(2020, 1, 1), None, "在職"),
            ("A1", "缺勤", datetime(2020, 1, 1), None, "在職"),
            ("O1", "陳家樂", datetime(2020, 1, 1), None, "在職"),
        ]
        for number, name, joined, left, status in people:
            sheet.append([number, name, name, "", "", joined, left, status, "全職"])
        other = book.create_sheet("內地勞工")
        other.append(["員工編號", "中文姓名", "英文姓名", "職位", "部門", "入職日期", "離職日期", "僱傭狀況", "就業形式"])
        book.save(home / "staff.xlsx")
        data = home / "data"
        data.mkdir(parents=True, exist_ok=True)
        rows = [
            _pay_row("C1", "全勤", "243-1"),
            _pay_row("C2", "七月", "243-2"),
            _pay_row("C3", "新入", "243-3", rest=8),
            _pay_row("C4", "離職", "243-4"),
            _pay_row("C5", "病假", "243-5"),
            _pay_row("A1", "缺勤", "243-6"),
        ]
        pd.DataFrame(rows).to_excel(data / "pay_table.xlsx", index=False)
        pd.DataFrame([
            _pay_row("O1", "Chan Ka Lok 陳家樂", "197-3", roster="陳家樂"),
            _pay_row("X1", "Li Ting Yan Andrew " + varying_pay()[0], "197-1", roster=""),
        ]).to_excel(data / "pay_table_admin.xlsx", index=False)

        def shop(year, month, pattern):
            info = parse_month(f"{year}-{month:02d}")
            _write_month(info, pattern, calendar.monthrange(year, month)[1])
            return info

        july = shop(2026, 7, {
            "全勤": ("09:00", "18:00"), "七月": ("09:00", "18:00"),
            "離職": ("09:00", "18:00"), "病假": "sick", "缺勤": "off", "新入": "off",
        })
        august = shop(2026, 8, {
            "全勤": ("09:00", "18:00"), "七月": "late",
            "離職": ("09:00", "18:00"), "病假": ("09:00", "18:00"), "缺勤": "off", "新入": "off",
        })
        september_days = {}
        for day in range(10, 22):
            september_days[day] = True
        sep_people = {
            "全勤": ("09:00", "18:00"), "七月": "late", "病假": ("09:00", "18:00"),
            "缺勤": "off", "離職": "off",
        }
        september = parse_month("2026-09")
        facts = []
        punches = ["姓名,日期,上班,下班"]
        for day in range(1, 31):
            for name, kind in sep_people.items():
                if kind == "off":
                    continue
                start, end = ("09:06", "18:00") if kind == "late" else kind
                facts.append({
                    "name": name, "date": datetime(2026, 9, day),
                    "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
                })
                punches.append(f"{name},2026-09-{day:02d},{start},{end}")
            if day in september_days:
                facts.append({
                    "name": "新入", "date": datetime(2026, 9, day),
                    "roster": "09:00-18:00", "shop": "TW_Bread", "wrong_site": 0,
                })
                punches.append(f"新入,2026-09-{day:02d},09:00,18:00")
        september["folder"].mkdir(parents=True, exist_ok=True)
        september["system"].mkdir(parents=True, exist_ok=True)
        pd.DataFrame(facts).to_excel(september["system"] / "daily_facts.xlsx", index=False)
        september["daka"].write_text("\n".join(punches), encoding="utf-8")

        july_draft = build_draft(july, write=False)
        write_closing(july, july_draft)
        sick = july_draft[july_draft["staff_id"].astype(str) == "243-5"].iloc[0]
        if abs(float(sick.unpaid_amount) - round(20000 / 31, 2)) > 0.02:
            raise SystemExit(f"one sick day should deduct one day: {sick.unpaid_amount}")
        august_draft = build_draft(august, write=False)
        rested = august_draft[august_draft["staff_id"].astype(str) == "243-5"].iloc[0]
        clean_rest = august_draft[august_draft["staff_id"].astype(str) == "243-1"].iloc[0]
        if float(clean_rest.unused_rest) - float(rested.unused_rest) != 1 or "上月有病假" not in str(rested.review):
            raise SystemExit(
                f"sick leave should cut one rest day: clean {clean_rest.unused_rest} sick {rested.unused_rest} {rested.review}"
            )
        leaver = august_draft[august_draft["staff_id"].astype(str) == "243-4"].iloc[0]
        if float(leaver.bonus) != 0 or float(leaver.bonus_paid) != 0 or "未發放" not in str(leaver.review):
            raise SystemExit(f"leaver bonus should wait: bonus {leaver.bonus} paid {leaver.bonus_paid} {leaver.review}")
        save_one(august, "243-4", {"bonus_leaver": "pay"})
        engine._EARNED.clear()
        paid_leaver = build_draft(august, write=False)
        paid = paid_leaver[paid_leaver["staff_id"].astype(str) == "243-4"].iloc[0]
        if float(paid.bonus_paid) != 1000:
            raise SystemExit(f"paying the leaver should release July only: {paid.bonus_paid}")

        september_draft = build_draft(september, write=False)
        clean = september_draft[september_draft["staff_id"].astype(str) == "243-1"].iloc[0]
        partial_bonus = september_draft[september_draft["staff_id"].astype(str) == "243-2"].iloc[0]
        joiner = september_draft[september_draft["staff_id"].astype(str) == "243-3"].iloc[0]
        if float(clean.bonus) != 1000 or float(clean.bonus_paid) != 3000:
            raise SystemExit(f"three clean months should pay 3000: {clean.bonus} {clean.bonus_paid}")
        if abs(float(clean.net) - (20000 - 1000 + 3000)) > 0.05:
            raise SystemExit(f"quarter bonus should enter net: {clean.net}")
        if float(partial_bonus.bonus) != 0 or float(partial_bonus.bonus_paid) != 1000:
            raise SystemExit(f"July only should pay 1000: {partial_bonus.bonus} {partial_bonus.bonus_paid}")
        if float(joiner.bonus) != 0 or float(joiner.unused_rest) != 3:
            raise SystemExit(f"part month earns 0 and rest is floor(12/5) plus the September statutory holiday: bonus {joiner.bonus} rest {joiner.unused_rest}")

        july_facts = (july["system"] / "daily_facts.xlsx").read_bytes()
        july_daka = july["daka"].read_bytes()
        august_facts = (august["system"] / "daily_facts.xlsx").read_bytes()
        august_daka = august["daka"].read_bytes()
        office_july = book_info(july, "admin")
        _write_month(office_july, {"陳家樂": "sick"}, 31)
        office = build_draft(office_july, write=False)
        boss = office[office["staff_id"].astype(str) == "197-1"].iloc[0]
        if str(boss.roster_name).strip() not in {"", "nan"}:
            raise SystemExit(f"boss was linked: {boss.roster_name}")
        write_closing(office_july, office)
        office_august = book_info(august, "admin")
        _write_month(office_august, {"陳家樂": ("09:00", "18:00")}, 31)
        office_next = build_draft(office_august, write=False)
        office_rest = office_next[office_next["staff_id"].astype(str) == "197-3"].iloc[0]
        if float(office_rest.unused_rest) != 8 or "上月有病假" in str(office_rest.review):
            raise SystemExit(f"office rest should not change: {office_rest.unused_rest} {office_rest.review}")
        (july["system"] / "daily_facts.xlsx").write_bytes(july_facts)
        july["daka"].write_bytes(july_daka)
        (august["system"] / "daily_facts.xlsx").write_bytes(august_facts)
        august["daka"].write_bytes(august_daka)

        november = shop(2026, 11, {"缺勤": {3, 5, 7}, "全勤": "off", "七月": "off", "新入": "off", "離職": "off", "病假": "off"})
        pending = build_draft(november, write=False)
        waiting = pending[pending["staff_id"].astype(str) == "243-6"].iloc[0]
        if "3/11" not in str(waiting.absence_pending) or "缺勤未確認" not in str(waiting.review):
            raise SystemExit(f"absence should wait for an answer: {waiting.absence_pending} {waiting.review}")
        save_one(november, "243-6", {"absence_choices": "3/11:unpaid、5/11:sick、7/11:worked", "sick_hours": 2})
        answered = build_draft(november, write=False)
        row = answered[answered["staff_id"].astype(str) == "243-6"].iloc[0]
        if str(row.absence_pending).strip() not in {"", "nan"}:
            raise SystemExit(f"answered absence still pending: {row.absence_pending}")
        from payroll.core.money import unpaid_amount
        hours = overtime_pay(20000, 30, 2)
        expected_unpaid = unpaid_amount(20000, 30, 2) + hours
        if abs(float(row.unpaid_amount) - expected_unpaid) > 0.05:
            raise SystemExit(f"unpaid plus sick day plus sick hours: {row.unpaid_amount}, expected {expected_unpaid}")
        if "病假 2 小時" not in str(row.absent_text):
            raise SystemExit(f"sick hours should be in the memo: {row.absent_text}")
        if float(row.days_worked) < 1:
            raise SystemExit("forgot-to-punch should count as worked")

        save_one(august, "243-2", {"bonus_override": 1000})
        noted = build_draft(august, write=False)
        note_row = noted[noted["staff_id"].astype(str) == "243-2"].iloc[0]
        if "舊糧單有勤工獎 $1000" not in str(note_row.review) or "遲到超過 5 分鐘" not in str(note_row.review):
            raise SystemExit(f"bonus note should give the reason: {note_row.review}")
        print("rules ok")
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        os.environ.pop("PAYROLL_STAFF", None)


def _one_slip():
    from docx import Document
    from payroll.documents.slips import keep_person, write_person_slip
    from payroll.documents.slips_admin import write_person_slip as write_admin_person

    home = scratch_dir("oneslip")
    copied = home / "one.docx"
    source = ROOT / "templates" / "payslip_md.docx"
    if not source.exists():
        raise SystemExit(f"missing {source}")
    import shutil
    shutil.copyfile(source, copied)
    slips = parse_slips(copied)
    if len(slips) < 2:
        raise SystemExit("the template should contain more than one slip")
    document = Document(str(copied))
    if not keep_person(document, slips[0]["staff_id"]):
        raise SystemExit("keep_person found nobody")
    document.save(str(copied))
    again = parse_slips(copied)
    if len(again) != 1 or again[0]["staff_id"] != slips[0]["staff_id"]:
        raise SystemExit(f"one-person Word slip is { [item['staff_id'] for item in again] }")

    info = book_info(parse_month("2026-10"), "admin")
    draft = build_draft(info, write=False)
    person = draft[draft["pay_this"].astype(bool)].iloc[0]
    booked = dict(info)
    booked["output"] = home / "out"
    path = write_admin_person(booked, draft, str(person.staff_id))
    parsed = parse_admin(path if path.suffix == ".xlsx" else path.with_suffix(".xlsx"))
    if len(parsed) != 1 or parsed[0]["staff_id"] != str(person.staff_id):
        raise SystemExit(f"one-person Excel slip is {[item['staff_id'] for item in parsed]}")
    word_info = book_info(parse_month("2026-10"), "md")
    word_draft = build_draft(word_info, write=False)
    word_person = word_draft[word_draft["pay_this"].astype(bool)].iloc[0]
    word_booked = dict(word_info)
    word_booked["output"] = home / "out"
    word_path = write_person_slip(word_booked, word_draft[word_draft["staff_id"].astype(str) == str(word_person.staff_id)], str(word_person.staff_id))
    if word_path.suffix == ".pdf" and not word_path.exists():
        raise SystemExit("the PDF path was returned but the file is missing")
    print("one slip ok", path.name, word_path.name)


def _quarter_slips():
    from docx import Document
    from payroll.documents.slips import _paint_quarter

    bg = ROOT / "templates" / "payslip_bg_quarter.docx"
    md = ROOT / "templates" / "payslip_md_quarter.docx"
    if not bg.exists() or not md.exists():
        raise SystemExit("quarter templates were not copied")
    slips = parse_slips(bg)
    lined = [slip for slip in slips if slip.get("bonus_lines")]
    if not lined:
        raise SystemExit("the quarter template has no monthly bonus lines")
    sample = lined[0]
    total = sample.get("bonus_overall")
    if total is None:
        raise SystemExit(f"no overall bonus on {sample['staff_id']}")
    if abs(sum(sample["bonus_lines"].values()) - float(total)) > 0.05:
        raise SystemExit(f"bonus lines {sample['bonus_lines']} do not add up to {total}")
    home = scratch_dir("quarter")
    copied = home / "quarter.docx"
    import shutil
    shutil.copyfile(bg, copied)
    document = Document(str(copied))
    draft = pd.DataFrame([{
        "staff_id": sample["staff_id"],
        "bonus": 0,
        "bonus_paid": 1000,
        "bonus_history": "7月 $1000、8月 $0",
        "pay_this": True,
    }])
    _paint_quarter(document, draft, {"month": 9, "year": 2026, "book": "bg"})
    document.save(str(copied))
    painted = next(slip for slip in parse_slips(copied) if slip["staff_id"] == sample["staff_id"])
    if painted["bonus_lines"].get(7) != 1000 or painted["bonus_lines"].get(9) != 0:
        raise SystemExit(f"painted lines: {painted['bonus_lines']}")
    if painted.get("bonus_overall") != 1000:
        raise SystemExit(f"painted total: {painted.get('bonus_overall')}")
    print("quarter template ok")


def main():
    _october()
    _references()
    _leaver()
    _ot_memo()
    _grey()
    _report()
    _bonus_rule()
    _rules()
    _quarter_slips()
    _one_slip()
    print("book checks ok")


if __name__ == "__main__":
    main()
