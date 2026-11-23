"""The daily board reads one roster cell and leaves late and overtime to the existing rules."""

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from payroll.core.config import scratch_dir
from payroll.attendance.today import load_day, location_for, missed, place_names


def _punch(clock_in, clock_out, code="S1"):
    return {
        "in": clock_in, "out": clock_out, "place": "", "code": code,
        "in_place": "", "out_place": "", "in_code": code, "out_code": code,
    }


def test_one_day():
    folder = scratch_dir("today-board")
    path = folder / "S1_Shop_roaster_2026_Oct.xlsx"
    import pandas as pd
    frame = pd.DataFrame([
        ["Period", date(2026, 10, 1), None],
        [None, None, None],
        [None, None, date(2026, 10, 1)],
        ["Name", None, "Thursday"],
        ["甲", 0, "09:00-18:00"],
        ["乙", 0, "休假"],
        ["丙", 0, "09:00-18:00"],
        [None, None, None],
    ])
    frame.to_excel(path, sheet_name="10月", index=False, header=False)
    day = date(2026, 10, 1)
    punches = {
        ("甲", "2026-10-01"): _punch("9:10", "18:40"),
        ("丁", "2026-10-01"): _punch("10:00", "19:00", "S5"),
        "__names__": {"甲", "乙", "丙", "丁"},
    }
    rows, missing = load_day(day, punches=punches, files=[("S1_Shop", path, "10月")])
    if missing:
        raise SystemExit(missing)

    def row(name):
        found = rows.loc[rows["Name"].astype(str).eq(name)]
        if not len(found):
            raise SystemExit(f"missing {name}")
        return found.iloc[0]

    person = row("甲")
    if int(person["Late"]) != 10 or float(person["OT"]) <= 0:
        raise SystemExit(f"late or overtime was not kept: {person['Late']} {person['OT']}")
    rested = row("乙")
    if missed(rested, day) or "休假" not in str(rested["Status"]):
        raise SystemExit(f"leave was treated as a missed shift: {rested['Status']}")
    if not missed(row("丙"), day):
        raise SystemExit(f"a rostered day with no punch should be missed: {row('丙')['Status']}")
    extra = row("丁")
    labels = scratch_dir("today-labels") / "company.toml"
    labels.write_text(
        '[[locations]]\nlabel = "Shop 1 retail"\ncode = "S1_Shop"\n\n'
        '[[locations]]\nlabel = "Shop 1 production"\ncode = "S1_Make"\n\n'
        '[punch_places]\nS5 = "Shop 5"\n',
        encoding="utf-8",
    )
    from payroll.core.settings import load
    old_company = os.environ.get("PAYROLL_COMPANY")
    os.environ["PAYROLL_COMPANY"] = str(labels)
    load.cache_clear()
    try:
        if "無排班" not in str(extra["Status"]) or "Shop 5" not in " ".join(place_names(extra["Chosen shop"])):
            raise SystemExit(f"an unrostered punch should sit on its shop card: {extra['Status']} {extra['Chosen shop']}")
        if location_for("S1_Shop") != ["Shop 1 retail"] or location_for("S1_Make") != ["Shop 1 production"]:
            raise SystemExit(f"retail and production were not split: {location_for('S1_Shop')} {location_for('S1_Make')}")
    finally:
        if old_company is None:
            os.environ.pop("PAYROLL_COMPANY", None)
        else:
            os.environ["PAYROLL_COMPANY"] = old_company
        load.cache_clear()
    variant = scratch_dir("today-variant")
    book = variant / "shop.xlsx"
    pd.DataFrame([
        [None, date(2026, 10, 1)],
        ["Name", "Thursday"],
        ["甲鍚", "06:30-16:00"],
    ]).to_excel(book, sheet_name="10月", index=False, header=False)
    variant_punches = {
        ("甲錫", "2026-10-01"): _punch("6:24", "", "K1"),
        "__names__": {"甲錫"},
    }
    variant_rows, variant_missing = load_day(
        day, punches=variant_punches, files=[("3F_Bread", book, "10月")],
    )
    if variant_missing or len(variant_rows) != 1:
        raise SystemExit(f"variant rows {len(variant_rows)} {variant_missing}")
    matched = variant_rows.iloc[0]
    if str(matched["Name"]) != "甲鍚" or str(matched["DAKA in"]) != "6:24" or missed(matched, day):
        raise SystemExit(f"variant was not linked: {matched['Name']} {matched['DAKA in']} {matched['Status']}")
    print("today board ok")


def test_late_chart_names_the_people():
    import pandas as pd
    from app.views.attendance import _late_people
    shown = pd.DataFrame([
        {"Name": "甲", "Late": 0},
        {"Name": "乙", "Late": 12},
        {"Name": "乙", "Late": 8},
        {"Name": "丙", "Late": 40},
    ])
    people = _late_people(shown)
    if list(people["姓名"]) != ["丙", "乙"]:
        raise SystemExit(people.to_dict("records"))
    if int(people.iloc[1]["分鐘"]) != 20:
        raise SystemExit(people.to_dict("records"))
    if _late_people(pd.DataFrame([{"Name": "甲", "Late": 0}])) is not None:
        raise SystemExit("a day with no late arrivals should not draw a chart")
    from app.views.today import _newest_roster
    folder = scratch_dir("newest-roster")
    (folder / "roster.xlsx").write_bytes(b"x")
    found = _newest_roster(folder)
    if found is None:
        raise SystemExit("the newest roster time was not read")


if __name__ == "__main__":
    test_one_day()
    test_newest_roster_reads_the_file_time()
    test_late_chart_names_the_people()
    print("roster time ok")
