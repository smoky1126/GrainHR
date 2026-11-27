"""Early pay for someone who resigns before month-end."""

from datetime import date, datetime
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from payroll.documents.slips import _saved_pay_date
from payroll.documents.slips_admin import _pay_date
from payroll.pay.early import (
    early_keys, include_in_month_pay, leaving_this_month, needs_approval, record_early,
)
from payroll.pay.part_time import build_pt, clip_days


def test_leave_date_must_fall_in_this_month():
    info = {"year": 2026, "month": 11, "days": 30}
    left = {"status": "已離職", "leave_date": date(2026, 11, 21)}
    if not leaving_this_month(left, info):
        raise SystemExit("a leave date in this month was skipped")
    earlier = {"status": "已離職", "leave_date": date(2026, 10, 31)}
    if leaving_this_month(earlier, info):
        raise SystemExit("last month was treated as this month")
    still_employed = {"status": "在職", "leave_date": date(2026, 11, 21)}
    if leaving_this_month(still_employed, info):
        raise SystemExit("someone still employed was listed")


def test_approval_blocks_early_pay():
    pending = {"review": "本月離職：只計 1/11–21/11 基本薪金", "approved": ""}
    if needs_approval(pending) != "請先在審核批准這個人。":
        raise SystemExit(needs_approval(pending))
    approved = {"review": "本月離職", "approved": "Y"}
    if needs_approval(approved):
        raise SystemExit(needs_approval(approved))
    bonus = {"review": "10月 $300 已累積，未發放。請選擇發放或不發放。", "approved": "Y"}
    if "勤工獎" not in needs_approval(bonus):
        raise SystemExit(needs_approval(bonus))
    absence = {"review": "", "approved": "Y", "absence_pending": "11/5"}
    if "缺勤" not in needs_approval(absence):
        raise SystemExit(needs_approval(absence))


def test_month_end_skips_someone_already_paid():
    if include_in_month_pay(True, "BG-1", "A001", set(), set()) is not True:
        raise SystemExit("an unpaid person was skipped")
    if include_in_month_pay(True, "BG-1", "A001", {"BG-1"}, set()):
        raise SystemExit("a paid staff id was included")
    if include_in_month_pay(True, "", "A001", set(), {"A001"}):
        raise SystemExit("a paid employee number was included")
    if include_in_month_pay(False, "BG-1", "A001", set(), set()):
        raise SystemExit("someone already off payroll was included")


def test_pay_date_override_does_not_read_the_month_file():
    info = {"pay_date_override": "22 Nov 2026"}
    if _saved_pay_date(info) != "22 Nov 2026":
        raise SystemExit(_saved_pay_date(info))
    if _pay_date(info) != "22 Nov 2026":
        raise SystemExit(_pay_date(info))


def test_part_time_hours_stop_on_the_leave_date():
    row = {
        "days": {1: 8, 22: 8},
        "extra_hours": 0,
        "rate": 60,
        "scheme": "none",
        "join_date": date(2020, 1, 1),
    }
    info = {"year": 2026, "month": 11, "days": 30}
    clipped = clip_days(row, 21, row, info)
    if abs(clipped["hours"] - 8) > 0.001 or abs(clipped["salary"] - 480) > 0.001:
        raise SystemExit(clipped)
    if 22 in clipped["days"]:
        raise SystemExit(clipped["days"])


def test_employee_mpf_uses_the_leave_date():
    row = {
        "days": {},
        "extra_hours": 80,
        "rate": 100,
        "scheme": "mpf",
        "join_date": date(2026, 9, 20),
    }
    info = {"year": 2026, "month": 11, "days": 30}
    clipped = clip_days(row, 10, row, info)
    if clipped["employee_mpf"] != 0 or abs(clipped["employer_mpf"] - 400) > 0.001:
        raise SystemExit(clipped)


def test_record_is_kept_and_a_second_pay_is_refused():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        system = root / "system"
        system.mkdir()
        info = {
            "system": system, "year": 2026, "month": 11, "days": 30,
            "key": "2026-11", "output": root,
        }
        person = {
            "kind": "part", "book": "bg", "employee_no": "P1", "staff_id": "",
            "name": "甲", "leave_date": date(2026, 11, 21),
        }
        record_early(info, person, date(2026, 11, 22), 480, root / "slip.xlsx")
        ids, numbers = early_keys(info)
        if numbers != {"P1"} or ids:
            raise SystemExit((ids, numbers))
        try:
            record_early(info, person, date(2026, 11, 22), 480, root / "slip.xlsx")
        except SystemExit as error:
            if "不會再發一次" not in str(error):
                raise
        else:
            raise SystemExit("a second early pay was accepted")


def test_recorded_part_time_is_left_out_of_the_summary():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        system = root / "system"
        system.mkdir()
        info = {
            "system": system, "year": 2026, "month": 11, "days": 30,
            "key": "2026-11", "output": root,
        }
        staff = pd.DataFrame([{
            "employee_no": "P1",
            "name_zh": "甲",
            "name_en": "Ada",
            "roster_hint": "Ada",
            "department": "Shop",
            "position": "",
            "join_date": datetime(2020, 1, 1).date(),
            "leave_date": None,
            "status": "在職",
            "employment": "兼職",
            "part_time": True,
        }])
        facts = pd.DataFrame([
            {"name": "Ada (PT)", "date": datetime(2026, 11, 2), "roster": "09:00-17:00"},
        ])
        lines = pd.DataFrame([{
            "employee_no": "P1", "rate": 60, "scheme": "none", "extra_hours": 0,
            "extra_note": "", "bank": "", "account": "", "pay_this": "Y",
        }])
        record_early(info, {
            "kind": "part", "book": "bg", "employee_no": "P1", "staff_id": "",
            "name": "甲", "leave_date": date(2026, 11, 21),
        }, date(2026, 11, 22), 480, root / "slip.xlsx")
        rows = build_pt(info, staff, facts, lines)
        if len(rows) != 1 or rows[0]["pay_this"] != "N" or rows[0]["salary"] != 0:
            raise SystemExit(rows)


def test_future_shifts_are_counted_before_the_last_day():
    from datetime import timedelta
    from payroll.attendance.days import merge_days
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    def row(day):
        return {
            "shop": "S1", "name": "Ada", "date": day.isoformat(),
            "roster": "09:00-17:00", "wrong_site": 0,
        }

    facts = pd.DataFrame([row(yesterday), row(today), row(tomorrow)])
    punches = {"__names__": {"Ada"}}
    summaries, _rows = merge_days(facts, punches, assume_until={"Ada": tomorrow})
    summary = summaries["Ada"]
    if summary["missing_days"] != 1 or summary["days_worked"] != 2:
        raise SystemExit(summary)
    punched = {"__names__": {"Ada"}, ( "Ada", today.isoformat()): {
        "in": "09:00", "out": "17:00", "place": "", "code": "",
        "in_place": "", "out_place": "", "in_code": "", "out_code": "",
    }}
    summaries, _rows = merge_days(facts, punched, assume_until={"Ada": tomorrow})
    summary = summaries["Ada"]
    if summary["days_worked"] != 2 or summary["missing_days"] != 1:
        raise SystemExit(summary)


def test_last_payment_includes_unused_leave_and_overtime():
    from payroll.core.money import annual_leave_pay, pay_detected_overtime
    if annual_leave_pay(19800, 2.39) != 1555.79:
        raise SystemExit(annual_leave_pay(19800, 2.39))
        raise SystemExit(annual_leave_pay(30000, 2))
    if annual_leave_pay(30000, 0) != 0:
        raise SystemExit("zero unused leave was paid")
    if not pay_detected_overtime("", True):
        raise SystemExit("a last payment skipped detected overtime")
    if pay_detected_overtime("exchange", True):
        raise SystemExit("time off was paid as overtime")
    if pay_detected_overtime("", False):
        raise SystemExit("a normal month paid overtime that was not chosen")
    if not pay_detected_overtime("pay", False):
        raise SystemExit("chosen overtime was skipped")
    if pay_detected_overtime("pay", True, office=True):
        raise SystemExit("office staff were paid overtime")
    from payroll.core.money import serious_late
    if serious_late("3/11 10分鐘、4/11 16分鐘、5/11 15分鐘") != [("4/11", 16)]:
        raise SystemExit(serious_late("3/11 10分鐘、4/11 16分鐘、5/11 15分鐘"))
    if serious_late("3/11 200分鐘、4/11 300分鐘", 240) != [("4/11", 300)]:
        raise SystemExit(serious_late("3/11 200分鐘、4/11 300分鐘", 240))
    from payroll.core.money import employee_mpf
    if employee_mpf(12540, "rent") != 0:
        raise SystemExit("mainland staff were charged MPF")
    if employee_mpf(12540 + 1972.60 + 500, "mpf") != round((12540 + 1972.60 + 500) * 0.05, 2):
        raise SystemExit("income column was not the MPF base")
    from payroll.pay.early import early_hold
    note = "本月離職：只計 1/11–19/11 基本薪金（19 天）。"
    if early_hold({"review": note, "approved": ""}):
        raise SystemExit(early_hold({"review": note, "approved": ""}))
    if "勤工獎" not in early_hold({"review": "10月 $300 已累積，未發放。請選擇發放或不發放。", "approved": "Y"}):
        raise SystemExit("bonus choice was ignored")
    if "缺勤" not in early_hold({"review": "", "absence_pending": "11/5", "approved": "Y"}):
        raise SystemExit("an open absence was ignored")
    note = "本月離職：只計 1/11–21/11 基本薪金；未到最後工作日的更表，先按更表計算，不當作缺卡。"
    if needs_approval({"review": note, "approved": ""}, prior=True):
        raise SystemExit(needs_approval({"review": note, "approved": ""}, prior=True))
    if not needs_approval({"review": "缺卡 1/11", "approved": ""}, prior=True):
        raise SystemExit("a real missing punch was ignored")


def test_office_slip_pdf_shows_partial_pay_and_unused_leave():
    from payroll.documents.slip_pdf import slip_content, write_office_pdf
    row = pd.Series({
        "slip_name": "Yeung Yuen Ting 楊宛婷",
        "name_en": "Yeung Yuen Ting Alice",
        "staff_id": "197-4",
        "department": "Administration 行政部",
        "position": "Admin Officer",
        "join_date": date(2023, 1, 3),
        "period": "1/11/2026-19/11/2026 (19 Days)",
        "full_salary": 19800,
        "basic_salary": 12540,
        "month_days": 30,
        "counted_days": 19,
        "leave_pay": 1555.79,
        "unused_annual_days": 2.39,
        "other_income": 1555.79,
        "mpf_employee": 704.79,
        "mpf_employer": 704.79,
        "net": 13391,
        "final_transport": 316.67,
        "final_health": 0,
        "allowance_amount": 316.67,
        "standing_transport": 500,
        "standing_health": 150,
    })
    content = slip_content(row, {"year": 2026, "month": 11})
    amounts = [item[1] for item in content["payments"]]
    if 19800 not in amounts or 12540 not in amounts or 1555.79 not in amounts:
        raise SystemExit(f"payment lines: {content['payments']}")
    notes = [item[2] for item in content["payments"]]
    if "($19,800/30*19)" not in notes or "($237,600/365*2.39)" not in notes:
        raise SystemExit(f"formulas missing: {notes}")
    if content["subtotal"] != 14095.79 or content["total"] != 13391:
        raise SystemExit(f"totals {content['subtotal']} {content['total']}")
    if content["transport_note"] != "($500/30*19)":
        raise SystemExit(content["transport_note"])
    if content["nickname"] != "Alice" or content["file_no"] != "#197- 4":
        raise SystemExit((content["nickname"], content["file_no"]))
    folder = Path(tempfile.mkdtemp())
    path = write_office_pdf(folder / "slip.pdf", row, {"year": 2026, "month": 11})
    if path.suffix != ".pdf" or not path.read_bytes().startswith(b"%PDF"):
        raise SystemExit("office slip was not a pdf")


def test_slip_keeps_the_transfer_reference():
    from payroll.documents.slip_pdf import slip_content
    content = slip_content(pd.Series({
        "slip_name": "Ada",
        "staff_id": "1-1",
        "basic_salary": 10000,
        "full_salary": 10000,
        "net": 9500,
        "mpf_employee": 500,
        "salary_reference": "NB-SAL",
        "allowance_reference": "NB-ALL",
    }), {"pay_date_override": "23 Nov 2026", "month": 11})
    if content["salary_reference"] != "NB-SAL" or content["allowance_reference"] != "NB-ALL":
        raise SystemExit(content)
    if content["pay_date"] != "23 Nov 2026":
        raise SystemExit(content["pay_date"])


def test_mainland_contract_ends_the_day_before_until_renewed():
    from payroll.staff.staff import employed_window
    info = {"year": 2026, "month": 11, "days": 30}
    record = {
        "sheet": "內地勞工", "status": "在職",
        "join_date": date(2024, 11, 28), "leave_date": None,
        "contract_end": date(2026, 11, 28),
    }
    if employed_window(record, info) != (date(2026, 11, 1), date(2026, 11, 27)):
        raise SystemExit(employed_window(record, info))
    record["contract_end"] = date(2027, 11, 28)
    if employed_window(record, info) != (date(2026, 11, 1), date(2026, 11, 30)):
        raise SystemExit(employed_window(record, info))
    record["contract_end"] = date(2026, 12, 1)
    if employed_window(record, info) != (date(2026, 11, 1), date(2026, 11, 30)):
        raise SystemExit(employed_window(record, info))
    record["contract_end"] = date(2026, 11, 1)
    if employed_window(record, info) is not None:
        raise SystemExit("an ended mainland contract was still paid")
    office = {
        "sheet": "BG & MD", "status": "在職",
        "join_date": date(2024, 1, 1), "leave_date": None,
        "contract_end": date(2026, 11, 28),
    }
    if employed_window(office, info) != (date(2026, 11, 1), date(2026, 11, 30)):
        raise SystemExit(employed_window(office, info))


def test_breakdown_is_this_month_and_shows_the_formula():
    from payroll.documents.breakdown import breakdown_lines, dates_in_month
    if dates_in_month("12/10(AM)、3/11(PM)", 11) != "3/11(PM)":
        raise SystemExit(dates_in_month("12/10(AM)、3/11(PM)", 11))
    row = pd.Series({
        "annual_dates": "12/10(AM)",
        "annual_taken": 0,
        "full_salary": 19800,
        "basic_salary": 12540,
        "month_days": 30,
        "counted_days": 19,
        "leave_pay": 1555.79,
        "unused_annual_days": 2.39,
        "late_text": "2/11 15分鐘、3/11 16分鐘",
        "salary_deduct_days": 0.5,
        "book": "admin",
    })
    text = " | ".join(breakdown_lines(row, 11, 2026))
    if "12/10" in text or "本月年假" in text or "扣薪" in text or "無薪假" in text:
        raise SystemExit(text)


def test_late_minutes_deduct_at_the_hourly_rate():
    from payroll.core.money import minute_deduction, minutes_for_pay
    from payroll.documents.breakdown import breakdown_lines
    from payroll.documents.slip_pdf import slip_content
    expected = round(19800 * (16 / 60) / (30 * 9.5), 2)
    if minute_deduction(19800, 30, 16) != expected or minute_deduction(19800, 30, 0) != 0:
        raise SystemExit(minute_deduction(19800, 30, 16))
    if minutes_for_pay("admin", 16) != 0 or minutes_for_pay("bg", 16) != 16:
        raise SystemExit((minutes_for_pay("admin", 16), minutes_for_pay("bg", 16)))
    row = pd.Series({
        "full_salary": 19800,
        "basic_salary": 19800,
        "month_days": 30,
        "salary_deduct_minutes": 16,
        "minute_deduct_amount": expected,
        "unpaid_amount": expected,
        "late_text": "3/11 16分鐘",
        "net": 19800 - expected,
        "mpf_employee": 0,
    })
    content = slip_content(row, {"year": 2026, "month": 11})
    labels = [item[0] for item in content["deductions"]]
    if labels != ["遲到 16 分鐘"] or content["deductions"][0][1] != expected:
        raise SystemExit(content["deductions"])
    if content["absent_mins"] != 16:
        raise SystemExit(content["absent_mins"])
    from payroll.documents.slip_pdf import _company_from_text, render_office_pdf
    if _company_from_text("Sample Limited有限公司Employee name") != "Sample Limited有限公司":
        raise SystemExit(_company_from_text("Sample Limited有限公司Employee name"))
    pdf = render_office_pdf(row, {"year": 2026, "month": 11, "book": "bg"})
    if not pdf.startswith(b"%PDF"):
        raise SystemExit("shop slip was not a pdf")


def test_a_forgotten_punch_is_marked_in_the_deduction_column():
    from payroll.documents.breakdown import missing_punch_marks
    from payroll.documents.slip_pdf import slip_content
    marks = missing_punch_marks("12/10下班、8/11上班、19/11下班、3/11", 11)
    if marks != ["8/11 上班缺卡", "19/11 下班缺卡", "3/11 全天缺卡"]:
        raise SystemExit(marks)
    row = pd.Series({
        "punch_missing": "8/11上班、19/11下班",
        "basic_salary": 10000,
        "net": 10000,
        "mpf_employee": 0,
    })
    content = slip_content(row, {"year": 2026, "month": 11})
    if content["punch_marks"] != ["8/11 上班缺卡", "19/11 下班缺卡"]:
        raise SystemExit(content["punch_marks"])
    if any("缺卡" in line for line in content["details"]):
        raise SystemExit(content["details"])
    if any(item[0].startswith("8/11") for item in content["deductions"]):
        raise SystemExit(content["deductions"])


def test_a_typed_water_or_electricity_charge_replaces_the_standing_one():
    from payroll.pay.payroll import chosen_charge
    if chosen_charge("", 4.3) != 4.3 or chosen_charge(None, 4.3) != 4.3:
        raise SystemExit(chosen_charge("", 4.3))
    if chosen_charge(0, 4.3) != 0 or chosen_charge(8.5, 4.3) != 8.5:
        raise SystemExit((chosen_charge(0, 4.3), chosen_charge(8.5, 4.3)))


def test_mainland_rent_is_ten_percent_after_deductions():
    from payroll.core.money import mainland_rent
    # Water and electricity are not taken off before the 10%.
    if mainland_rent(16680, 556) != round((16680 - 556) * 0.1, 2):
        raise SystemExit(mainland_rent(16680, 556))
    if mainland_rent(15012, 593.07) != round((15012 - 593.07) * 0.1, 2):
        raise SystemExit(mainland_rent(15012, 593.07))


def test_lateness_and_early_leave_are_separate_deductions():
    from payroll.core.money import split_charged_minutes
    from payroll.documents.slip_pdf import slip_content
    if split_charged_minutes(38, 18, 24) != (14, 24):
        raise SystemExit(split_charged_minutes(38, 18, 24))
    if split_charged_minutes(16, 16, 0) != (16, 0):
        raise SystemExit(split_charged_minutes(16, 16, 0))
    content = slip_content(pd.Series({
        "basic_salary": 16680,
        "full_salary": 16680,
        "month_days": 30,
        "salary_deduct_minutes": 38,
        "minute_deduct_amount": 37.07,
        "unpaid_amount": 37.07,
        "late_text": "15/11 4分鐘、19/11 14分鐘",
        "early_text": "24/11 24分鐘",
        "net": 16680 - 37.07,
        "mpf_employee": 0,
    }), {"year": 2026, "month": 11})
    labels = [item[0] for item in content["deductions"]]
    if labels != ["遲到 14 分鐘", "早退 24 分鐘"]:
        raise SystemExit(labels)
    notes = [item[2] for item in content["deductions"]]
    if notes != [
        "15/11 4分鐘、19/11 14分鐘\n($16,680/30/9.5/60*14)",
        "24/11 24分鐘\n($16,680/30/9.5/60*24)",
    ]:
        raise SystemExit(notes)
    npl = slip_content(pd.Series({
        "basic_salary": 16680,
        "full_salary": 16680,
        "month_days": 30,
        "unpaid_days": 1,
        "unpaid_amount": 556,
        "net": 16124,
        "mpf_employee": 0,
    }), {"year": 2026, "month": 11})
    if npl["deductions"][0][2] != "($16,680/30*1)":
        raise SystemExit(npl["deductions"])


def test_slip_shows_the_staff_number_and_puts_a_missing_punch_under_npl():
    from payroll.documents.slip_pdf import allowance_rows, deduction_sequence, slip_content
    order = [item[1] for item in deduction_sequence(
        [("NPL 無薪假", 556), ("遲到 38 分鐘", 37.07), ("Rent 租金", 1497.49), ("Water 水費", 4.3)],
        ["8/11 全天缺卡"],
    )]
    if order != ["NPL 無薪假", "8/11 全天缺卡", "遲到 38 分鐘", "Rent 租金", "Water 水費"]:
        raise SystemExit(order)
    content = slip_content(pd.Series({
        "employee_no": "ESL004",
        "slip_name": "Tu",
        "basic_salary": 10000,
        "net": 10000,
        "mpf_employee": 0,
        "final_health": 0,
        "final_transport": 0,
        "allowance_amount": 0,
    }), {"year": 2026, "month": 11})
    if content["employee_no"] != "ESL004":
        raise SystemExit(content["employee_no"])
    if allowance_rows(content):
        raise SystemExit(allowance_rows(content))


def test_breakdown_lists_rest_days_and_statutory_holidays():
    from payroll.core.holidays import holiday_dates
    from payroll.documents.breakdown import breakdown_lines
    if holiday_dates(2026, 12, "bg") != "25/12、26/12":
        raise SystemExit(holiday_dates(2026, 12, "bg"))
    if holiday_dates(2026, 10, "admin") != "1/10、19/10":
        raise SystemExit(holiday_dates(2026, 10, "admin"))
    from payroll.documents.slip_pdf import slip_content
    row = pd.Series({"book": "bg", "taken_dates": "12/10、2/11、8/11", "basic_salary": 1000, "net": 1000})
    content = slip_content(row, {"year": 2026, "month": 11})
    if content["rest_taken"] != "2/11、8/11":
        raise SystemExit(content["rest_taken"])
    if content["holiday_dates"] != "無":
        raise SystemExit(content["holiday_dates"])
    december = slip_content(
        pd.Series({"book": "bg", "basic_salary": 1, "net": 1, "rest_entitlement": 4}),
        {"year": 2026, "month": 12},
    )
    if december["rest_month"] != "4" or december["holiday_dates"] != "25/12、26/12":
        raise SystemExit((december["rest_month"], december["holiday_dates"]))


def test_editing_an_issued_slip_updates_the_amount_and_does_not_add_another_pay():
    from payroll.core.config import scratch_dir
    from payroll.core.excel_io import save_excel
    from payroll.pay.early import COLUMNS, load_early, revise_issued_net
    folder = scratch_dir("early-revise")
    system = folder / "system"
    system.mkdir()
    info = {"system": system}
    frame = pd.DataFrame([{
        "employee_no": "ESL004",
        "staff_id": "243-13",
        "name": "Tu",
        "kind": "full",
        "book": "bg",
        "leave_date": "2026-11-28",
        "pay_date": "27 Nov 2026",
        "net": 100,
        "slip": "slip.pdf",
        "time": "",
        "user": "",
    }])
    save_excel(system / "early_paid.xlsx", frame.reindex(columns=COLUMNS))
    revise_issued_net(info, "ESL004", 80)
    saved = load_early(info)
    if len(saved) != 1 or float(saved.iloc[0]["net"]) != 80:
        raise SystemExit(saved.to_dict("records"))


def test_a_compiled_slip_stays_on_the_leaver_list():
    from payroll.core.config import scratch_dir
    from payroll.core.excel_io import save_excel
    from payroll.pay.early import COLUMNS, issued_people
    folder = scratch_dir("early-list")
    system = folder / "system"
    system.mkdir()
    frame = pd.DataFrame([{
        "employee_no": "ESL004",
        "staff_id": "243-13",
        "name": "Tu",
        "kind": "full",
        "book": "bg",
        "leave_date": "2026-11-28",
        "pay_date": "27 Nov 2026",
        "net": 1,
        "slip": "slip.docx",
        "time": "",
        "user": "",
    }])
    save_excel(system / "early_paid.xlsx", frame.reindex(columns=COLUMNS))
    people = issued_people({"system": system})
    if len(people) != 1 or people[0]["employee_no"] != "ESL004":
        raise SystemExit(people)
    if people[0]["leave_date"] != date(2026, 11, 28) or people[0]["name"] != "Tu":
        raise SystemExit(people)


def test_a_later_contract_does_not_pay_the_gap_month():
    import os
    from payroll.core.config import scratch_dir
    from payroll.staff.contracts import apply_renewal, clear_contract_cache
    from payroll.staff.staff import employed_window
    home = scratch_dir("contract-gap")
    os.environ["PAYROLL_HOME"] = str(home)
    clear_contract_cache()
    try:
        record = {
            "sheet": "內地勞工", "status": "在職", "employee_no": "E001",
            "join_date": date(2024, 11, 28), "leave_date": None,
            "contract_end": date(2026, 11, 28),
        }
        november = {"year": 2026, "month": 11, "days": 30}
        december = {"year": 2026, "month": 12, "days": 31}
        january = {"year": 2027, "month": 1, "days": 31}
        if employed_window(record, december) is not None:
            raise SystemExit("十二月在續約前已被出糧")
        apply_renewal("E001", date(2024, 11, 28), date(2026, 11, 28), date(2027, 1, 1), date(2028, 1, 1))
        record["contract_end"] = date(2028, 1, 1)
        if employed_window(record, november) != (date(2026, 11, 1), date(2026, 11, 27)):
            raise SystemExit(employed_window(record, november))
        if employed_window(record, december) is not None:
            raise SystemExit("中間的月份被出糧")
        if employed_window(record, january) != (date(2027, 1, 1), date(2027, 1, 31)):
            raise SystemExit(employed_window(record, january))
    finally:
        os.environ.pop("PAYROLL_HOME", None)
        clear_contract_cache()


def test_someone_outside_monthly_pay_is_not_a_new_joiner():
    import os
    import pandas as pd
    from payroll.core.config import scratch_dir
    from payroll.core.settings import load, no_monthly_pay
    home = scratch_dir("no-monthly")
    (home / "company.toml").write_text("[people]\nno_monthly_pay = [\"E009\"]\n", encoding="utf-8")
    os.environ["PAYROLL_COMPANY"] = str(home / "company.toml")
    load.cache_clear()
    try:
        if no_monthly_pay() != {"E009"}:
            raise SystemExit(no_monthly_pay())
        from app.state import new_joiners
        staff = pd.DataFrame([
            {"employee_no": "E009", "active": True, "part_time": False, "status": "在職", "leave_date": None},
            {"employee_no": "E010", "active": True, "part_time": False, "status": "在職", "leave_date": None},
        ])
        found = [_text_no(row.employee_no) for row in new_joiners(staff, pd.DataFrame(columns=["employee_no"]))]
        if found != ["E010"]:
            raise SystemExit(found)
    finally:
        os.environ.pop("PAYROLL_COMPANY", None)
        load.cache_clear()


def _text_no(value):
    return str(value).strip()


def test_chosen_last_day_ends_the_pay_window():
    from payroll.pay.payroll import _window_until
    info = {"year": 2026, "month": 11, "days": 30}
    record = {"join_date": date(2020, 1, 1), "leave_date": None, "status": "在職"}
    window = _window_until(record, info, date(2026, 11, 21))
    if window != (date(2026, 11, 1), date(2026, 11, 21)):
        raise SystemExit(window)


def main():
    test_leave_date_must_fall_in_this_month()
    test_approval_blocks_early_pay()
    test_month_end_skips_someone_already_paid()
    test_pay_date_override_does_not_read_the_month_file()
    test_part_time_hours_stop_on_the_leave_date()
    test_employee_mpf_uses_the_leave_date()
    test_record_is_kept_and_a_second_pay_is_refused()
    test_recorded_part_time_is_left_out_of_the_summary()
    test_future_shifts_are_counted_before_the_last_day()
    test_last_payment_includes_unused_leave_and_overtime()
    test_office_slip_pdf_shows_partial_pay_and_unused_leave()
    test_breakdown_is_this_month_and_shows_the_formula()
    test_mainland_contract_ends_the_day_before_until_renewed()
    test_a_later_contract_does_not_pay_the_gap_month()
    test_someone_outside_monthly_pay_is_not_a_new_joiner()
    test_slip_keeps_the_transfer_reference()
    test_late_minutes_deduct_at_the_hourly_rate()
    test_a_forgotten_punch_is_marked_in_the_deduction_column()
    test_a_typed_water_or_electricity_charge_replaces_the_standing_one()
    test_mainland_rent_is_ten_percent_after_deductions()
    test_lateness_and_early_leave_are_separate_deductions()
    test_slip_shows_the_staff_number_and_puts_a_missing_punch_under_npl()
    test_breakdown_lists_rest_days_and_statutory_holidays()
    test_editing_an_issued_slip_updates_the_amount_and_does_not_add_another_pay()
    test_a_compiled_slip_stays_on_the_leaver_list()
    test_chosen_last_day_ends_the_pay_window()
    print("early pay checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
