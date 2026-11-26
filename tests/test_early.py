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
    if annual_leave_pay(30000, 2) != round(30000 * 12 / 365 * 2, 2):
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
    test_chosen_last_day_ends_the_pay_window()
    print("early pay checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
