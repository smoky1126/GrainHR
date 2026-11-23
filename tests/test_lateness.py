"""Late report: the 5-minute rule, who a roster name belongs to, and October."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from payroll.attendance.days import merge_days
from payroll.attendance.lateness import late_summary, link_groups, shops_by_name
from payroll.core.money import LATE_GRACE_MINUTES
from payroll.staff.directory import GROUP_LABEL


def _days(rows):
    return pd.DataFrame(rows)


def _staff(rows):
    frame = pd.DataFrame(rows)
    for column in ("name_en", "roster_hint", "position", "department", "employment", "sheet", "active"):
        if column not in frame.columns:
            frame[column] = "" if column != "active" else True
    return frame


def test_grace_rule_and_dates():
    days = _days([
        {"Name": "甲", "Date": "2026-11-03", "Late": 12, "Chosen shop": "S1_Make"},
        {"Name": "甲", "Date": "2026-11-07", "Late": 4, "Chosen shop": "S1_Make"},
        {"Name": "甲", "Date": "2026-10-31", "Late": LATE_GRACE_MINUTES, "Chosen shop": "S1_Make"},
        {"Name": "乙", "Date": "2026-11-02", "Late": 0, "Status": "不在 DAKA", "Chosen shop": "S1_Make"},
        {"Name": "丙", "Date": "2026-11-04", "Late": LATE_GRACE_MINUTES, "Chosen shop": "S2_Shop"},
    ])
    shown = late_summary(days, {})
    person = shown[shown["name"] == "甲"].iloc[0]
    if person["times"] != 3 or person["minutes"] != 12 + 4 + LATE_GRACE_MINUTES:
        raise SystemExit(f"every late minute should count: {person.to_dict()}")
    if person["over_grace"] != 1 or "longest" in shown.columns:
        raise SystemExit(f"only a lateness over {LATE_GRACE_MINUTES} minutes is over the limit: {person.to_dict()}")
    if person["dates"] != f"31/10 {LATE_GRACE_MINUTES}分\n\n3/11 12分\n\n7/11 4分":
        raise SystemExit(f"dates should stay in order: {person['dates']}")
    if "乙" in set(shown["name"]):
        raise SystemExit("a person who was not late should not be on the report")
    within = shown[shown["name"] == "丙"].iloc[0]
    if within["affects_bonus"] or within["over_grace"]:
        raise SystemExit(f"{LATE_GRACE_MINUTES} minutes is still inside the rule: {within.to_dict()}")
    hidden = late_summary(days, {}, hide_within_grace=True)
    if set(hidden["name"]) != {"甲"}:
        raise SystemExit(f"the switch should leave only lateness over {LATE_GRACE_MINUTES} minutes: {set(hidden['name'])}")
    kept = hidden.iloc[0]
    if kept["times"] != 1 or kept["minutes"] != 12 or kept["dates"] != "3/11 12分":
        raise SystemExit(f"shorter lateness should be hidden: {kept.to_dict()}")


def test_late_day_shows_roster_clock_in_and_punch_count():
    days = _days([
        {"Name": "甲", "Date": "2026-11-01", "Late": 0, "Roster cell": "09:00-18:00", "DAKA in": "09:00", "Punch count": 4},
        {"Name": "甲", "Date": "2026-11-02", "Late": 0, "Roster cell": "09:00-18:00", "DAKA in": "08:58", "Punch count": 4},
        {"Name": "甲", "Date": "2026-11-03", "Late": 12, "Roster cell": "09:00-18:00", "DAKA in": "09:12", "Punch count": 3},
        {"Name": "乙", "Date": "2026-11-03", "Late": 8, "Roster cell": "10:00-19:00", "DAKA in": "10:08", "Punch count": 2},
    ])
    shown = late_summary(days, {})
    text = shown[shown["name"] == "甲"].iloc[0]["dates"]
    if "更表 09:00-18:00" not in text or "打卡 09:12" not in text or "3次（平時 4 次）" not in text:
        raise SystemExit(f"four-punch staff should show the short day: {text}")
    other = shown[shown["name"] == "乙"].iloc[0]["dates"]
    if "打卡 10:08" not in other or "2次" not in other or "平時 4 次" in other:
        raise SystemExit(f"a two-punch day should not be compared with four: {other}")
    from payroll.attendance.lateness import person_late_table
    detail = person_late_table(days[days["Name"] == "甲"])
    if list(detail["打卡次數"]) != ["3，平時 4"] or list(detail["上班打卡"]) != ["09:12"]:
        raise SystemExit(f"detail {detail.to_dict('records')}")
    if list(detail["更表時間"]) != ["09:00-18:00"]:
        raise SystemExit(f"roster time {detail.to_dict('records')}")
    from payroll.attendance.daka import punch_counts
    from pathlib import Path
    folder = Path(__file__).resolve().parents[1] / "_tmp" / "punch-count"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "daka.csv"
    path.write_text(
        "姓名,日期,上班,上班位置,下班,下班位置,上班,上班位置,下班,下班位置\n"
        "甲,2026-11-03,09:12,North,13:00,North,14:00,North,,\n",
        encoding="utf-8",
    )
    if punch_counts(path) != {("甲", "2026-11-03"): 3}:
        raise SystemExit(f"punch count {punch_counts(path)}")
    full = folder / "four.csv"
    full.write_text(
        "姓名,日期,上班,上班位置,下班,下班位置,上班,上班位置,下班,下班位置\n"
        "甲,2026-11-04,09:12,North,13:00,North,14:05,North,18:10,North\n",
        encoding="utf-8",
    )
    from payroll.attendance.daka import punch_logs
    clocks = punch_logs(full)[("甲", "2026-11-04")]
    if clocks != [("上班", "9:12"), ("下班", "13:00"), ("上班", "14:05"), ("下班", "18:10")]:
        raise SystemExit(f"four clocks {clocks}")
    four_days = _days([
        {"Name": "甲", "Date": "2026-11-04", "Late": 12, "Roster cell": "09:00-18:00", "DAKA in": "09:12", "Punch count": 4,
         "Punch log": "上班 9:12、下班 13:00、上班 14:05、下班 18:10"},
    ])
    four_text = late_summary(four_days, {}).iloc[0]["dates"]
    first, _, second = four_text.partition("\n")
    if "更表 09:00-18:00" not in first or "打卡 09:12" not in first or "4次" not in first:
        raise SystemExit(f"the first line should keep the late-day note: {four_text}")
    if second != "上班 9:12、下班 13:00、上班 14:05、下班 18:10":
        raise SystemExit(f"the four clocks should be the next line: {four_text}")


def test_retail_late_lists_overtime_that_can_make_up_time():
    days = _days([
        {"Name": "零售", "Date": "2026-11-02", "Late": 0, "OT": 1.5, "Roster cell": "12:00-21:00", "DAKA out": "22:40"},
        {"Name": "零售", "Date": "2026-11-08", "Late": 20, "OT": 0, "Roster cell": "09:00-18:00", "DAKA in": "09:20"},
        {"Name": "工場", "Date": "2026-11-03", "Late": 0, "OT": 2, "Roster cell": "07:00-16:00", "DAKA out": "18:00"},
        {"Name": "工場", "Date": "2026-11-09", "Late": 15, "OT": 0, "Roster cell": "07:00-16:00", "DAKA in": "07:15"},
    ])
    links = {
        "零售": {"employee_no": "R001", "group": "bg_retail", "name": "零售"},
        "工場": {"employee_no": "B001", "group": "bg_prod", "name": "工場"},
    }
    shown = late_summary(days, links)
    retail = shown[shown["name"] == "零售"].iloc[0]
    if retail["ot_hours"] != 1.5 or "2/11 加班 1.5小時" not in retail["ot_dates"] or "下班 22:40" not in retail["ot_dates"]:
        raise SystemExit(f"retail overtime {retail['ot_hours']} {retail['ot_dates']}")
    if "8/11" in str(retail["ot_dates"]):
        raise SystemExit("a late day with no overtime should not be listed as 補鐘")
    factory = shown[shown["name"] == "工場"].iloc[0]
    if factory["ot_hours"] or factory["ot_dates"]:
        raise SystemExit(f"production overtime should not be listed here: {factory['ot_dates']}")


def test_part_time_and_mainland_do_not_lose_a_bonus():
    days = _days([
        {"Name": "兼職", "Date": "2026-11-03", "Late": 20},
        {"Name": "甜品兼職", "Date": "2026-11-03", "Late": 20},
        {"Name": "內地", "Date": "2026-11-03", "Late": 20},
        {"Name": "甜品內地", "Date": "2026-11-03", "Late": 20},
        {"Name": "寫字樓", "Date": "2026-11-03", "Late": 20},
        {"Name": "零售", "Date": "2026-11-03", "Late": 20},
        {"Name": "工場", "Date": "2026-11-03", "Late": 20},
        {"Name": "甜品", "Date": "2026-11-03", "Late": 20},
    ])
    links = {
        "兼職": {"employee_no": "RPT001", "group": "bg_pt", "name": "兼職"},
        "甜品兼職": {"employee_no": "B2001", "group": "md_pt", "name": "甜品兼職"},
        "內地": {"employee_no": "ESL001", "group": "bg_esl", "name": "內地"},
        "甜品內地": {"employee_no": "ESL002", "group": "md_esl", "name": "甜品內地"},
        "寫字樓": {"employee_no": "A001", "group": "admin", "name": "寫字樓"},
        "零售": {"employee_no": "R001", "group": "bg_retail", "name": "零售"},
        "工場": {"employee_no": "B001", "group": "bg_prod", "name": "工場"},
        "甜品": {"employee_no": "P001", "group": "md_ft", "name": "甜品"},
    }
    shown = {row["name"]: row["affects_bonus"] for _, row in late_summary(days, links).iterrows()}
    for name in ("兼職", "甜品兼職", "內地", "甜品內地", "寫字樓"):
        if shown[name]:
            raise SystemExit(f"{name} does not earn 勤工獎: {shown[name]}")
    for name in ("零售", "工場", "甜品"):
        if shown[name] != "影響勤工獎":
            raise SystemExit(f"{name} should lose the bonus: {shown[name]}")


def test_two_shifts_and_missing_daka_use_the_scored_row():
    day = "2026-11-08"
    facts = pd.DataFrame([
        {"shop": "S1_Make", "name": "甲", "date": day, "roster": "09:00-13:00", "wrong_site": 0},
        {"shop": "S3_Make", "name": "甲", "date": day, "roster": "14:00-18:00", "wrong_site": 0},
        {"shop": "S2_Shop", "name": "乙", "date": day, "roster": "09:00-18:00", "wrong_site": 0},
    ])
    punches = {
        "__names__": {"甲"},
        ("甲", day): {
            "in": "09:20", "out": "18:00", "place": "", "code": "S1",
            "in_place": "", "out_place": "", "in_code": "S1", "out_code": "S3",
        },
    }
    summaries, evidence = merge_days(facts, punches)
    if int(summaries["乙"]["late_mins"]) != 0:
        raise SystemExit(f"someone missing from DAKA has no lateness: {summaries['乙']}")
    shown = late_summary(evidence, {})
    if "乙" in set(shown["name"]):
        raise SystemExit("someone missing from DAKA should not be listed as late")
    person = shown[shown["name"] == "甲"]
    if len(person) != 1:
        raise SystemExit(f"two shifts on one day are one row: {shown.to_dict('records')}")
    got = int(person.iloc[0]["minutes"])
    if got != int(summaries["甲"]["late_mins"]) or got <= 0 or person.iloc[0]["times"] != 1:
        raise SystemExit(f"two-shift lateness {got}, attendance says {summaries['甲']['late_mins']}")


def test_linking_order():
    from payroll.core.settings import load
    office_map = {
        str(key): str(value)
        for key, value in (load().get("office_names") or {"測試甲": "Ada Test"}).items()
    }
    zh, nick = next(iter(office_map.items()))
    staff = _staff([
        {"employee_no": "A002", "name_zh": zh, "name_en": "CHAN ACCOUNT", "department": "Office - Administration",
         "employment": "全職", "position": "Accounting Officer", "active": True},
        {"employee_no": "A999", "name_zh": "另一人", "name_en": "", "department": "Office - Administration",
         "employment": "全職", "active": True},
        {"employee_no": "RPT001", "name_zh": "陳大文", "name_en": "", "roster_hint": "陳大文",
         "department": "Shop - Retail", "employment": "兼職", "position": "店員", "active": True},
        {"employee_no": "B010", "name_zh": "麵包師", "department": "Make - Bread", "employment": "全職",
         "position": "麵包師", "active": True},
    ])
    pay = pd.DataFrame([
        {"employee_no": "A999", "roster_name": nick},
        {"employee_no": "B010", "roster_name": "麵包師"},
        {"employee_no": "B010", "roster_name": "重複"},
    ])
    other = pd.DataFrame([{"employee_no": "A002", "roster_name": "重複"}])
    part_time = [staff[staff["employee_no"] == "RPT001"].iloc[0].to_dict()]
    names = [nick, "陳大文 (PT)", "麵包師", "重複", "路人", "阿明 (PT)"]
    shops = {
        "路人": ["S2_Shop", "S1_Shop", "S1_Make"],
        "阿明 (PT)": ["K1_B2"],
        nick: ["Office"],
    }
    linked = link_groups(names, staff, {"bg": pay, "md": other}, part_time, shops)
    if linked[nick]["employee_no"] != "A999":
        raise SystemExit(f"the pay table should win over the office nickname: {linked[nick]}")
    if linked["陳大文 (PT)"]["employee_no"] != "RPT001" or linked["陳大文 (PT)"]["group"] != "bg_pt":
        raise SystemExit(f"part-time name was not linked: {linked['陳大文 (PT)']}")
    if linked["麵包師"]["employee_no"] != "B010" or linked["麵包師"]["group"] != "bg_prod":
        raise SystemExit(f"roster name on the pay table should keep its group: {linked['麵包師']}")
    if linked["重複"]["employee_no"] != "":
        raise SystemExit(f"two pay tables disagree, so the name stays unmatched: {linked['重複']}")
    if linked["路人"]["employee_no"] or linked["路人"]["group"] != "bg_retail":
        raise SystemExit(f"an unknown name should follow the shop: {linked['路人']}")
    if linked["阿明 (PT)"]["group"] != "md_pt":
        raise SystemExit(f"the second company part-time group was not used: {linked['阿明 (PT)']}")
    office = link_groups([nick], staff, {}, [], {nick: ["Office"]})
    if office[nick]["employee_no"] != "A002" or office[nick]["group"] != "admin":
        raise SystemExit(f"without a pay table the office nickname should match: {office[nick]}")
    if office[nick]["name"] != zh:
        raise SystemExit(f"the report should show the staff name: {office[nick]}")
    unknown = link_groups(["沒有店鋪"], staff, {}, [], {})
    if unknown["沒有店鋪"]["group"] or unknown["沒有店鋪"]["employee_no"]:
        raise SystemExit(f"no shop and no staff should stay unclassified: {unknown['沒有店鋪']}")
    summary = late_summary(
        _days([
            {"Name": nick, "Date": "2026-11-01", "Late": 8},
            {"Name": "路人", "Date": "2026-11-02", "Late": 3},
        ]),
        linked,
    )
    office_row = summary[summary["employee_no"] == "A999"].iloc[0]
    if office_row["group_label"] != GROUP_LABEL["admin"]:
        raise SystemExit(f"group label {office_row['group_label']}")
    shop_row = summary[summary["name"] == "路人"].iloc[0]
    if shop_row["group"] != "bg_retail" or shop_row["group_label"] != GROUP_LABEL["bg_retail"]:
        raise SystemExit(f"shop group label {shop_row.to_dict()}")


def test_same_person_on_two_roster_names_is_one_row():
    days = _days([
        {"Name": "甲", "Date": "2026-11-01", "Late": 10},
        {"Name": "甲的別名", "Date": "2026-11-01", "Late": 6},
        {"Name": "甲的別名", "Date": "2026-11-02", "Late": 2},
    ])
    links = {
        "甲": {"employee_no": "B001", "group": "bg_prod", "name": "甲"},
        "甲的別名": {"employee_no": "B001", "group": "bg_prod", "name": "甲"},
    }
    shown = late_summary(days, links)
    if len(shown) != 1:
        raise SystemExit(f"one employee should be one row: {shown.to_dict('records')}")
    row = shown.iloc[0]
    if row["times"] != 2 or row["minutes"] != 12:
        raise SystemExit(f"the same day should count once, at the longer lateness: {row.to_dict()}")
    if set(row["roster_names"]) != {"甲", "甲的別名"}:
        raise SystemExit(f"both roster names should stay available: {row['roster_names']}")


def test_shops_follow_the_roster_name():
    shops = shops_by_name(_days([
        {"Name": "甲", "Chosen shop": "S1_Make"},
        {"Name": "甲", "Chosen shop": "S1_Make"},
        {"Name": "甲", "Chosen shop": "S3_Shop"},
        {"Name": "", "Chosen shop": "S2_Make"},
    ]))
    if shops != {"甲": ["S1_Make", "S3_Shop"]}:
        raise SystemExit(f"shops {shops}")


def test_october_totals_match_the_attendance_check():
    month = Path(__file__).resolve().parents[2] / "data" / "months" / "2026_10"
    facts_path = month / "_system" / "daily_facts.xlsx"
    daka_path = month / "daka.csv"
    if not facts_path.exists() or not daka_path.exists():
        print(f"october lateness check skipped, no copy at {month}")
        return
    from payroll.attendance.daka import load_daka
    summaries, evidence = merge_days(pd.read_excel(facts_path), load_daka(daka_path))
    shown = late_summary(evidence, {})
    got = {str(row["name"]): int(row["minutes"]) for _, row in shown.iterrows()}
    for name, summary in summaries.items():
        expected = int(summary["late_mins"] or 0)
        actual = got.get(name, 0)
        if actual != expected:
            raise SystemExit(f"{name} is late {actual} minutes here, and {expected} in the attendance check")
    extra = set(got) - set(summaries)
    if extra:
        raise SystemExit(f"names that are not in October: {sorted(extra)[:8]}")
    print(f"october lateness matches for {len(summaries)} people, {len(shown)} of them late")


if __name__ == "__main__":
    test_grace_rule_and_dates()
    test_two_shifts_and_missing_daka_use_the_scored_row()
    test_linking_order()
    test_same_person_on_two_roster_names_is_one_row()
    test_shops_follow_the_roster_name()
    test_october_totals_match_the_attendance_check()
    print("lateness ok")
