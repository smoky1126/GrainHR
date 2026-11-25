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


def main():
    test_leave_date_must_fall_in_this_month()
    test_approval_blocks_early_pay()
    test_month_end_skips_someone_already_paid()
    test_pay_date_override_does_not_read_the_month_file()
    test_part_time_hours_stop_on_the_leave_date()
    test_employee_mpf_uses_the_leave_date()
    test_record_is_kept_and_a_second_pay_is_refused()
    test_recorded_part_time_is_left_out_of_the_summary()
    print("early pay checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
