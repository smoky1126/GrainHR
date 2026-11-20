"""October 2026 must match the saved attendance workbook and the #243 slips."""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("PAYROLL_HOME", None)
os.environ.pop("PAYROLL_DEMO", None)

import pandas as pd

from payroll.core.config import opening_balance_path, parse_month, scratch_dir
from payroll.pay.payroll import build_draft, pay_sheet_rows
from payroll.setup.regression import attendance_differences, pay_differences
from payroll.core.names import chinese
from payroll.pay.review import apply_pay, apply_pay_date, apply_review, review_edits_from_frame
from payroll.documents.slips import allowance_rows, fill_document, write_allowance_summary
from payroll.documents.parse_slips import parse_slips
from payroll.staff.staff import ensure_adjustments, ensure_pay_table, load_staff, pay_table_path


def _check_new_month():
    november = parse_month("2026-11")
    if november["sheet"] != "11月" or november["days"] != 30 or november["month_token"] != "Nov":
        raise SystemExit(f"unexpected November settings: {november}")
    opening = opening_balance_path(november)
    if opening is None or opening.name != "2026_10_close.xlsx":
        raise SystemExit(f"November should open from October's closing file, not {opening}")
    folder = scratch_dir("november")
    try:
        november["adjustments"] = folder / "adjustments.xlsx"
        table = ensure_pay_table()
        ensure_adjustments(november, table)
        lines = pd.read_excel(november["adjustments"], sheet_name="lines")
        approved = lines["approved"].fillna("").astype(str).str.strip()
        approved = approved[~approved.str.lower().eq("nan")]
        if len(lines) != len(table) or approved.ne("").any():
            raise SystemExit("A first check should create a blank adjustments file.")
        ensure_adjustments(november, table)
        if len(pd.read_excel(november["adjustments"], sheet_name="lines")) != len(lines):
            raise SystemExit("The blank adjustments file was overwritten.")
    finally:
        shutil.rmtree(folder)


def main():
    info = parse_month("2026-10")
    opening = opening_balance_path(info)
    if opening is None or opening.name != "2026_10_open.xlsx":
        raise SystemExit(f"October should open from 2026_10_open.xlsx, not {opening}")
    _check_new_month()
    check = info["system"] / f"{info['sheet']}考勤核對表.xlsx"
    attendance = attendance_differences(check)
    if attendance:
        raise SystemExit("attendance mismatch:\n" + "\n".join(attendance[:20]))
    saved = info["adjustments"].read_bytes()
    draft = build_draft(info)
    _keep_october_bonus(info, draft)
    draft = build_draft(info)
    pay = pay_differences(draft)
    if pay:
        raise SystemExit("pay mismatch:\n" + "\n".join(pay))
    _print_problem_counts(info, draft)
    pay_path = pay_table_path()
    saved_pay = pay_path.read_bytes()
    pay_before = pd.read_excel(pay_path)
    date_before = str(pd.read_excel(info["adjustments"], sheet_name="meta").iloc[0]["pay_date"])
    try:
        shown = draft[draft["show_on_review"]].copy()
        apply_review(info, review_edits_from_frame(shown))
        apply_pay_date(info, date_before)
        apply_pay(pay_sheet_rows(load_staff(), ensure_pay_table()).to_dict("records"))
        draft = build_draft(info, write=False)
        pay = pay_differences(draft)
        if pay:
            raise SystemExit("pay mismatch after review round-trip:\n" + "\n".join(pay))
        date_after = str(pd.read_excel(info["adjustments"], sheet_name="meta").iloc[0]["pay_date"])
        if date_after != date_before:
            raise SystemExit(f"pay date changed from {date_before!r} to {date_after!r}")
        _same_pay_table(pay_before, pd.read_excel(pay_path))
    finally:
        info["adjustments"].write_bytes(saved)
        pay_path.write_bytes(saved_pay)
        draft = build_draft(info)
    document = fill_document(info, draft)
    filled = parse_slips(document)
    filled_problems = pay_differences(draft, filled)
    if filled_problems:
        raise SystemExit("filled slip mismatch:\n" + "\n".join(filled_problems))
    _check_allowances(draft)
    summary = write_allowance_summary(info, "Oct 2026", draft)
    print("october ok")
    print(document)
    print(summary)
    return 0


def _keep_october_bonus(info, draft):
    """Combining rosters can reveal late minutes the old count dropped.

    The October slip amount is kept with a bonus override, and named in the note.
    """
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    from payroll.core.config import REFERENCE_SLIPS
    slips = parse_slips(REFERENCE_SLIPS)
    kept = []
    lines["staff_id"] = lines["staff_id"].map(lambda value: "" if pd.isna(value) else str(value).strip())
    if "note" not in lines.columns:
        lines["note"] = ""
    for slip in slips:
        if slip.get("bonus") is None:
            continue
        rows = draft[draft["staff_id"].astype(str) == slip["staff_id"]]
        if rows.empty:
            continue
        if abs(float(rows.iloc[0].bonus or 0) - float(slip["bonus"])) <= 0.02:
            continue
        mask = lines["staff_id"] == slip["staff_id"]
        lines.loc[mask, "bonus_override"] = slip["bonus"]
        note = lines.loc[mask, "note"].fillna("").astype(str)
        lines.loc[mask, "note"] = note.map(
            lambda text: text if "kept from #243 slip" in text else f"{text}; kept from #243 slip".strip("; ")
        )
        kept.append(f"{slip['staff_id']} {slip['slip_name']} bonus kept at {slip['bonus']}")
    if not kept:
        return
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)
    print("bonus kept from #243:")
    print("\n".join(kept))


def _print_problem_counts(info, draft):
    facts = pd.read_excel(info["system"] / "daily_facts.xlsx")
    paid = draft[draft["pay_this"].astype(bool)]
    before = 0
    for name in paid["roster_name"].astype(str):
        if not name or name == "nan":
            continue
        group = facts[facts["name"].astype(str) == name].drop_duplicates(["date"])
        if group.empty:
            continue
        if int(group["missing_punch"].sum()) or int(group["wrong_site"].sum()):
            before += 1
    after = int((paid["review"].astype(str).str.strip() != "").sum())
    shown = int((draft["show_on_review"] & draft["review"].astype(str).str.strip().ne("")).sum())
    missing_after = int(paid["review"].astype(str).str.contains("缺卡").sum())
    print(f"paid rows with a problem before: {before}")
    print(f"paid rows with a missing punch after: {missing_after}")
    print(f"paid rows with a problem after: {after}")
    print(f"review rows with a problem: {shown}")


def _same_pay_table(before, after):
    if len(before) != len(after):
        raise SystemExit("pay table shape changed on a round trip with no edits")
    number_columns = {
        "basic_salary", "rent_rate", "water", "bonus_eligible", "rest_days_month", "allowance_amount",
    }
    for column in before.columns:
        for index in range(len(before)):
            left = before.iloc[index][column]
            right = after.iloc[index][column]
            if column in number_columns:
                left_blank = pd.isna(left) or str(left).strip() == ""
                right_blank = pd.isna(right) or str(right).strip() == ""
                if left_blank and right_blank:
                    continue
                if left_blank or right_blank or abs(float(left) - float(right)) > 0.001:
                    who = before.iloc[index]["slip_name"]
                    raise SystemExit(f"pay table {column} changed for {who}: {left!r} -> {right!r}")
                continue
            left_text = "" if pd.isna(left) else str(left).strip()
            right_text = "" if pd.isna(right) else str(right).strip()
            if left_text.lower() == "nan":
                left_text = ""
            if right_text.lower() == "nan":
                right_text = ""
            if left_text != right_text:
                who = before.iloc[index]["slip_name"]
                raise SystemExit(f"pay table {column} changed for {who}: {left_text!r} -> {right_text!r}")


def _check_allowances(draft):
    rows = allowance_rows(draft)
    paid = draft[draft["pay_this"].astype(bool)]
    expected = 0
    for _, person in paid.iterrows():
        amount = 0 if pd.isna(person.allowance_amount) else float(person.allowance_amount)
        section = "" if pd.isna(person.allowance_section) else str(person.allowance_section).strip().lower()
        if amount > 0 and section in {"shop", "office"}:
            expected += 1
    if len(rows) != expected:
        raise SystemExit(f"allowance summary has {len(rows)} rows, pay table has {expected}")
    by_name = {chinese(row["name"]): row for row in rows}
    tin_lok = by_name.get(chinese("張天樂"))
    if tin_lok is None or abs(tin_lok["amount"] - 1100) > 0.01 or tin_lok["section"] != "shop":
        raise SystemExit(f"張天樂 allowance should be shop 1100, got {tin_lok}")
    mai = by_name.get(chinese("麥土燕"))
    if mai is None or abs(mai["amount"] - 25.81) > 0.01 or "200/31*4" not in mai["note"]:
        raise SystemExit(f"麥土燕 allowance should stay 25.81 with the day note, got {mai}")
    for name in ("梁嘉軒", "關偉健", "梁敬", "馮家柔", "何進傑", "楊富來", "梁頌熙", "楊思懿", "涂玉成"):
        if chinese(name) in by_name:
            raise SystemExit(f"{name} was a false allowance match and should not be on the summary")
    for name in ("陳家樂", "楊宛婷", "梁曉雯"):
        if chinese(name) in by_name:
            raise SystemExit(f"{name} is not on this payroll")
    print(f"allowance summary rows: {len(rows)}")


if __name__ == "__main__":
    raise SystemExit(main())
