"""Small checks for combining rosters and for overtime pay."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from payroll.attendance.days import merge_days
from payroll.core.money import overtime_pay


def _facts(rows):
    return pd.DataFrame(rows)


def _punch(name, date, clock_in="", clock_out="", code=""):
    return {
        "__names__": {name},
        (name, date): {"in": clock_in, "out": clock_out, "place": "", "code": code},
    }


def test_second_roster_shift_counts():
    date = "2026-10-03"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
        {"shop": "TW_Bread", "name": "Ada", "date": date, "roster": "09:00-18:00", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
    ])
    summaries, _ = merge_days(facts, _punch("Ada", date, "09:00", "18:00", "TW"))
    summary = summaries["Ada"]
    if summary["roster_days"] != "TW_Bread 1" or summary["missing_days"]:
        raise SystemExit(f"second roster shift was not counted: {summary}")


def test_sick_without_punch_is_leave():
    date = "2026-10-04"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "病假", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
    ])
    summaries, days = merge_days(facts, _punch("Ada", date))
    summary = summaries["Ada"]
    if summary["sick_days"] != 1 or summary["missing_days"]:
        raise SystemExit(f"sick day was treated as a missing punch: {summary}")
    if days.iloc[0]["Status"] != "病假":
        raise SystemExit(f"sick day status should be 病假: {days.iloc[0]['Status']}")
    if days.iloc[0]["Leave kind"] != "sick":
        raise SystemExit(f"leave kind should be sick: {days.iloc[0]['Leave kind']}")


def test_rest_with_punch_is_day_off():
    date = "2026-10-05"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "休假", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
    ])
    summaries, days = merge_days(facts, _punch("Ada", date, "09:00", "18:00", "JD"))
    summary = summaries["Ada"]
    if summary["rest_days"] or not summary["day_off_dates"]:
        raise SystemExit(f"worked rest day was not flagged: {summary}")
    if days.iloc[0]["Status"] != "休息日有打卡":
        raise SystemExit(f"rest-day punch status should be 休息日有打卡: {days.iloc[0]['Status']}")


def test_shift_without_punch_is_missing():
    date = "2026-10-06"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "09:00-18:00", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
    ])
    summaries, days = merge_days(facts, _punch("Ada", date))
    summary = summaries["Ada"]
    if summary["missing_days"] != 1:
        raise SystemExit(f"missing shift was not flagged: {summary}")
    if days.iloc[0]["Status"] != "全天缺卡":
        raise SystemExit(f"missing shift status should be 全天缺卡: {days.iloc[0]['Status']}")
    if summary.get("absent_dates") != "6/10":
        raise SystemExit(f"full absence should be listed for confirmation: {summary}")


def test_two_shifts_are_flagged():
    date = "2026-10-07"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "09:00-18:00", "late_mins": 5,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
        {"shop": "TW_Bread", "name": "Ada", "date": date, "roster": "10:00-19:00", "late_mins": 0,
         "early_mins": 0, "ot_hours": 1, "wrong_site": 0},
    ])
    summaries, days = merge_days(facts, _punch("Ada", date, "10:00", "19:30", "TW"))
    summary = summaries["Ada"]
    if not summary["two_shift_dates"] or summary["ot_hours"] != 0.5 or summary["late_mins"]:
        raise SystemExit(f"two shifts were not resolved from DAKA: {summary}")
    if days.iloc[0]["Chosen shop"] != "TW_Bread":
        raise SystemExit(f"DAKA shop was not chosen: {days.iloc[0].to_dict()}")
    if not str(days.iloc[0]["Status"]).startswith("兩份更表同日有更"):
        raise SystemExit(f"two-shift status should be Chinese: {days.iloc[0]['Status']}")


def test_rest_without_punch_says_rest():
    date = "2026-10-08"
    facts = _facts([
        {"shop": "JD_Bread", "name": "Ada", "date": date, "roster": "休假", "late_mins": 0,
         "early_mins": 0, "ot_hours": 0, "wrong_site": 0},
    ])
    _summaries, days = merge_days(facts, _punch("Ada", date))
    if days.iloc[0]["Status"] != "休假" or days.iloc[0]["Leave kind"] != "rest":
        raise SystemExit(f"rest day should say 休假: {days.iloc[0].to_dict()}")


def test_late_early_and_overtime_columns():
    rows = []
    for day, roster, clock_in, clock_out in (
        ("2026-10-10", "09:00-18:00", "09:12", "18:00"),
        ("2026-10-11", "09:00-18:00", "09:00", "17:40"),
        ("2026-10-12", "09:00-18:00", "09:04", "18:30"),
    ):
        rows.append({
            "shop": "JD_Bread", "name": "Ada", "date": day, "roster": roster,
            "late_mins": 0, "early_mins": 0, "ot_hours": 0, "wrong_site": 0,
        })
    facts = _facts(rows)
    punches = {"__names__": {"Ada"}}
    punches[("Ada", "2026-10-10")] = {"in": "09:12", "out": "18:00", "place": "", "code": "JD"}
    punches[("Ada", "2026-10-11")] = {"in": "09:00", "out": "17:40", "place": "", "code": "JD"}
    punches[("Ada", "2026-10-12")] = {"in": "09:04", "out": "18:30", "place": "", "code": "JD"}
    _summaries, days = merge_days(facts, punches)
    late = days[days["Date"].astype(str).str.startswith("2026-10-10")].iloc[0]
    early = days[days["Date"].astype(str).str.startswith("2026-10-11")].iloc[0]
    overtime = days[days["Date"].astype(str).str.startswith("2026-10-12")].iloc[0]
    if int(late["Late"]) != 12 or "遲到 12 分鐘" not in str(late["Status"]):
        raise SystemExit(f"late day: {late.to_dict()}")
    if int(early["Early"]) <= 0 or "早退" not in str(early["Status"]) or "已補" not in str(early["Status"]):
        raise SystemExit(f"early day: {early.to_dict()}")
    if float(overtime["OT"]) <= 0 or "加班" not in str(overtime["Status"]):
        raise SystemExit(f"overtime day: {overtime.to_dict()}")
    if int(overtime["Late"]) != 4:
        raise SystemExit(f"four minutes late should stay on the row: {overtime.to_dict()}")


def test_overtime_pay():
    amount = overtime_pay(20000, 31, 3)
    if amount != 203.74:
        raise SystemExit(f"overtime pay should be 203.74, got {amount}")


def test_lunch_pair_is_not_clock_out():
    from payroll.attendance.daka import load_daka

    folder = Path(__file__).resolve().parents[1] / "_tmp" / "daka_punches"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "daka.csv"
    path.write_text(
        "姓名,日期,上班,上班位置,下班,下班位置,上班,上班位置,下班,下班位置\n"
        "Ada,2026/10/18,12:32,11 TW -2,16:00,11 TW -2,16:30,11 TW -2,21:47,2 JD -1\n",
        encoding="utf-8-sig",
    )
    punches = load_daka(path)
    row = punches[("Ada", "2026-10-18")]
    if row["in"] != "12:32" or row["out"] != "21:47":
        raise SystemExit(f"lunch pair was used as the clock times: {row}")
    if row["in_code"] != "TW" or row["out_code"] != "JD":
        raise SystemExit(f"both places should be kept: {row}")
    if row["out"] == "16:00":
        raise SystemExit("lunch clock-out was treated as leaving")


def test_split_shop_uses_morning_and_afternoon():
    date = "2026-10-18"
    facts = _facts([
        {"shop": "WC_Retail", "name": "Ada", "date": date, "roster": "09:00-13:00", "wrong_site": 0},
        {"shop": "JD_Retail", "name": "Ada", "date": date, "roster": "14:00-18:00", "wrong_site": 0},
    ])
    punch = {
        "in": "9:12", "out": "17:40", "place": "1 WC", "code": "WC",
        "in_place": "1 WC", "out_place": "2 JD", "in_code": "WC", "out_code": "JD",
    }
    punches = {"__names__": {"Ada"}, ( "Ada", date): punch}
    summary, days = merge_days(facts, punches)
    row = days.iloc[0]
    if int(row["Late"]) != 12 or int(row["Early"]) != 20:
        raise SystemExit(f"split times: {row.to_dict()}")
    if "轉店" not in str(row["Status"]) or "異地" in str(row["Status"]):
        raise SystemExit(f"matched shops should be 轉店: {row['Status']}")
    if summary["Ada"]["wrong_days"] or summary["Ada"]["two_shift_dates"]:
        raise SystemExit(f"a matched move was treated as a problem: {summary['Ada']}")
    if "WC" not in str(row["DAKA place"]) or "JD" not in str(row["DAKA place"]):
        raise SystemExit(f"both locations should show: {row['DAKA place']}")
    punch["out_code"] = "HKU"
    punch["out_place"] = "9 HKU"
    summary, days = merge_days(facts, punches)
    row = days.iloc[0]
    if "轉店" in str(row["Status"]) or "18/10" not in summary["Ada"]["wrong_dates"]:
        raise SystemExit(f"the unmatched leg should be 異地: {row['Status']} {summary['Ada']['wrong_dates']}")
    if int(row["Late"]) != 12:
        raise SystemExit(f"late should still use the morning start: {row.to_dict()}")


def test_pastry_is_separate_from_the_central_kitchen():
    from payroll.attendance.days import shop_code
    date = "2026-10-02"
    if shop_code("3F_Pastry") == shop_code("3F_Bread"):
        raise SystemExit("pastry and the central kitchen share a shop code")
    facts = _facts([
        {"shop": "3F_Pastry", "name": "Ada", "date": date, "roster": "09:00-18:00", "wrong_site": 0},
    ])
    punches = {"__names__": {"Ada"}, ( "Ada", date): {
        "in": "09:00", "out": "18:00", "place": "1 SPK", "code": "SPK",
        "in_place": "1 SPK", "out_place": "1 SPK", "in_code": "SPK", "out_code": "SPK",
    }}
    summary, days = merge_days(facts, punches)
    if "異地" in str(days.iloc[0]["Status"]) or summary["Ada"]["wrong_days"]:
        raise SystemExit(f"pastry punch at SPK was treated as the wrong shop: {days.iloc[0]['Status']}")


def main():
    test_second_roster_shift_counts()
    test_sick_without_punch_is_leave()
    test_rest_with_punch_is_day_off()
    test_shift_without_punch_is_missing()
    test_rest_without_punch_says_rest()
    test_late_early_and_overtime_columns()
    test_two_shifts_are_flagged()
    test_overtime_pay()
    test_lunch_pair_is_not_clock_out()
    test_split_shop_uses_morning_and_afternoon()
    test_pastry_is_separate_from_the_central_kitchen()
    print("day checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
