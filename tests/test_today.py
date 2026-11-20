"""The daily board reads one roster cell and leaves late and overtime to the existing rules."""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from payroll.core.config import scratch_dir
from payroll.attendance.today import load_day, location_for, missed, place_names


def _punch(clock_in, clock_out, code="JD"):
    return {
        "in": clock_in, "out": clock_out, "place": "", "code": code,
        "in_place": "", "out_place": "", "in_code": code, "out_code": code,
    }


def test_one_day():
    folder = scratch_dir("today-board")
    path = folder / "JD_Retail_roaster_2026_Oct.xlsx"
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
        ("丁", "2026-10-01"): _punch("10:00", "19:00", "WC"),
        "__names__": {"甲", "乙", "丙", "丁"},
    }
    rows, missing = load_day(day, punches=punches, files=[("JD_Retail", path, "10月")])
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
    if "無排班" not in str(extra["Status"]) or "灣仔" not in place_names(extra["Chosen shop"]):
        raise SystemExit(f"an unrostered punch should sit on its shop card: {extra['Status']} {extra['Chosen shop']}")
    if location_for("JD_Retail") != ["佐敦零售"] or location_for("JD_Bread") != ["佐敦生產"]:
        raise SystemExit(f"retail and production were not split: {location_for('JD_Retail')} {location_for('JD_Bread')}")
    variant = scratch_dir("today-variant")
    book = variant / "shop.xlsx"
    pd.DataFrame([
        [None, date(2026, 10, 1)],
        ["Name", "Thursday"],
        ["梁廣鍚", "06:30-16:00"],
    ]).to_excel(book, sheet_name="10月", index=False, header=False)
    variant_punches = {
        ("梁廣錫", "2026-10-01"): _punch("6:24", "", "SPK"),
        "__names__": {"梁廣錫"},
    }
    variant_rows, variant_missing = load_day(
        day, punches=variant_punches, files=[("3F_Bread", book, "10月")],
    )
    if variant_missing or len(variant_rows) != 1:
        raise SystemExit(f"variant rows {len(variant_rows)} {variant_missing}")
    matched = variant_rows.iloc[0]
    if str(matched["Name"]) != "梁廣鍚" or str(matched["DAKA in"]) != "6:24" or missed(matched, day):
        raise SystemExit(f"variant was not linked: {matched['Name']} {matched['DAKA in']} {matched['Status']}")
    print("today board ok")


if __name__ == "__main__":
    test_one_day()
