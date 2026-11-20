"""Build the staff master, opening balances and October adjustments from #243."""

import shutil

import pandas as pd

from payroll.core.config import REFERENCE_SLIPS, home, parse_month
from payroll.core.money import attendance_bonus, unused_rest
from payroll.core.names import chinese, match_roster_name
from payroll.documents.parse_slips import load_allowances, parse_slips


def _roster_stats(facts):
    stats = {}
    if facts is None or facts.empty:
        return stats
    work = facts.drop_duplicates(["name", "date"])
    for name, group in work.groupby("name"):
        rest = group[group["roster"].astype(str).str.contains("休假", na=False)]
        annual = group[group["roster"].astype(str).str.contains("年假", na=False)]
        sick = group[group["roster"].astype(str).str.contains("病假", na=False)]
        unpaid = group[group["roster"].astype(str).str.contains("無薪", na=False)]
        birthday = group[group["roster"].astype(str).str.contains("生日", na=False)]
        stats[name] = {
            "late_mins": int(group["late_mins"].sum()),
            "early_mins": int(group["early_mins"].sum()),
            "ot_hours": float(group["ot_hours"].sum()),
            "missing_days": int(group["missing_punch"].sum()),
            "wrong_site_days": int(group["wrong_site"].sum()),
            "rest_days": int(len(rest)),
            "rest_dates": _dates(rest["date"]),
            "annual_days": int(len(annual)),
            "sick_days": int(len(sick)),
            "unpaid_days": int(len(unpaid)),
            "birthday_days": int(len(birthday)),
            "shops": ",".join(sorted(set(group["shop"].astype(str)))),
        }
    return stats


def _dates(series):
    days = []
    for value in series:
        text = str(value)
        day = text[8:10].lstrip("0") if len(text) >= 10 else text
        if day:
            days.append(day)
    return ",".join(days)


def _allowance_for(slip, allowances):
    target = chinese(slip["name_zh"]) or chinese(slip["slip_name"])
    hits = [row for row in allowances if target and target in chinese(row["name"])]
    if len(hits) == 1:
        return hits[0]
    tokens = slip["name_en"].lower()
    hits = [row for row in allowances if tokens and tokens.split(" ")[0] in row["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    return None


def seed_october(facts=None):
    info = parse_month("2026-10")
    slips = parse_slips(REFERENCE_SLIPS)
    allowances = load_allowances(info["allowance_source"])
    facts_path = info["system"] / "daily_facts.xlsx"
    if facts is None and facts_path.exists():
        facts = pd.read_excel(facts_path)
    roster_names = sorted(set(facts["name"].astype(str))) if facts is not None else []
    stats = _roster_stats(facts)

    master_rows = []
    balance_rows = []
    adjustment_rows = []
    unmatched = []
    for slip in slips:
        roster_name = match_roster_name(slip["slip_name"], slip["name_en"], slip["name_zh"], roster_names)
        if not roster_name:
            unmatched.append(slip["slip_name"])
        person = stats.get(roster_name, {})
        allowance = _allowance_for(slip, allowances)
        rest_calc = unused_rest(
            slip["opening_rest"], slip["rest_entitlement"], slip["statutory_days"], slip["taken_rest"]
        )
        rest_override = ""
        if abs(rest_calc - float(slip["unused_rest"] or 0)) > 0.01:
            rest_override = slip["unused_rest"]
        bonus_rule = attendance_bonus(
            slip["bonus_eligible"],
            person.get("late_mins", slip["absent_mins"]),
            person.get("early_mins", 0),
            slip["unpaid_days"],
            slip["absent_days"],
            None,
            month=info["month"],
        )
        bonus_override = ""
        if slip["bonus"] is not None and abs(bonus_rule - float(slip["bonus"])) > 0.01:
            bonus_override = slip["bonus"]
        notes = []
        if slip["manual_delta"]:
            notes.append(f"總數同公式相差 {slip['manual_delta']}")
        if slip["stated_extra"] and not slip["other_income"]:
            notes.append(f"糧單有額外 {slip['stated_extra']}，沒有計入總數")
        if rest_override != "":
            notes.append(f"糧單剩餘休假 {slip['unused_rest']}，公式 {rest_calc}")
        if bonus_override != "":
            notes.append(
                f"舊糧單有勤工獎 ${float(slip['bonus']):g}，但按規則應為 ${float(bonus_rule):g}，已沿用舊糧單金額。"
            )

        al_lines = [dict(line) for line in slip["al_lines"]]
        if al_lines:
            al_lines[-1]["days"] = float(al_lines[-1]["days"]) + float(slip["annual_taken"] or 0)
        master_rows.append({
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "name_en": slip["name_en"],
            "name_zh": slip["name_zh"],
            "roster_name": roster_name,
            "aliases": roster_name,
            "department": slip["department"],
            "position": slip["position"],
            "join_date": slip["join_date"],
            "basic_salary": slip["basic_salary"],
            "scheme": slip["scheme"],
            "rent_rate": 0.1 if slip["scheme"] == "rent" else 0,
            "rent_base": slip["rent_base"] or "basic",
            "water": slip["water"],
            "bonus_eligible": int(slip["bonus_eligible"]),
            "rest_days_month": slip["rest_entitlement"],
            "allowance_desc": allowance["description"] if allowance else slip["allowance_desc"],
            "allowance_amount": allowance["amount"] if allowance else slip["allowance_amount"],
            "allowance_note": allowance["note"] if allowance else "",
            "allowance_section": allowance["section"] if allowance else "",
        })
        balance_rows.append({
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "opening_rest": slip["opening_rest"],
            "opening_ot_hours": 0,
            "al_1_label": al_lines[0]["label"] if len(al_lines) > 0 else "",
            "al_1_opening": al_lines[0]["days"] if len(al_lines) > 0 else "",
            "al_2_label": al_lines[1]["label"] if len(al_lines) > 1 else "",
            "al_2_opening": al_lines[1]["days"] if len(al_lines) > 1 else "",
        })
        adjustment_rows.append({
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "unpaid_days": slip["unpaid_days"],
            "absent_days": slip["absent_days"],
            "statutory_days": slip["statutory_days"],
            "sick_days": slip["sick_days"],
            "annual_taken": slip["annual_taken"],
            "birthday_days": slip["birthday_days"],
            "taken_rest": slip["taken_rest"],
            "taken_dates": slip["taken_dates"],
            "absent_mins": slip["absent_mins"],
            "absent_text": "\n".join(slip["absent_lines"]),
            "ot_text": "\n".join(slip["ot_lines"]),
            "ot_pay": 0,
            "other_income": slip["other_income"],
            "stated_extra": slip["stated_extra"],
            "manual_delta": slip["manual_delta"],
            "bonus_override": bonus_override,
            "rest_override": rest_override,
            "water_override": "",
            "note": "; ".join(notes),
            "approved": "Y",
        })

    data = home() / "data"
    balances = data / "balances"
    balances.mkdir(parents=True, exist_ok=True)
    template = home() / "templates"
    template.mkdir(parents=True, exist_ok=True)
    master_path = data / "staff_master.xlsx"
    pd.DataFrame(master_rows).to_excel(master_path, index=False)
    pd.DataFrame(balance_rows).to_excel(balances / "2026_10_open.xlsx", index=False)
    adjust_path = info["adjustments"]
    with pd.ExcelWriter(adjust_path, engine="openpyxl") as writer:
        pd.DataFrame(adjustment_rows).to_excel(writer, sheet_name="lines", index=False)
        pd.DataFrame([{
            "pay_date": "4 Nov 2026",
            "salary_reference": "NB0498755329",
            "allowance_reference": "NB0498819638",
        }]).to_excel(writer, sheet_name="meta", index=False)
    shutil.copyfile(REFERENCE_SLIPS, template / "payslip_bg.docx")
    print(f"staff {len(master_rows)} written to {master_path}")
    if unmatched:
        print("unmatched roster names:")
        for name in unmatched:
            print(" -", name)
    return {
        "slips": slips,
        "master": master_path,
        "adjustments": adjust_path,
        "unmatched": unmatched,
    }


def _link_employee(slip, staff):
    from payroll.staff.staff import _match_person, _text
    match = _match_person(slip, staff)
    if match is not None:
        return _text(match["employee_no"])
    return f"未入檔-{slip['staff_id']}"


def _tidy_md_number(path):
    """鍾玉鳳's October slip is stored as #243 - 2. The copy uses #243-2."""
    from docx import Document
    document = Document(path)
    changed = False
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if "#243 - 2" in cell.text or "#243- 2" in cell.text:
                    for paragraph in cell.paragraphs:
                        if "243" in paragraph.text and "2" in paragraph.text:
                            for run in paragraph.runs:
                                run.text = run.text.replace("#243 - 2", "#243-2").replace("#243- 2", "#243-2")
                            changed = True
    if changed:
        document.save(path)


def seed_book(book, facts=None):
    """October pay table, balances, adjustments and template for the other books."""
    from payroll.core.config import book_info
    from payroll.documents.parse_admin import parse_admin
    from payroll.staff.staff import load_staff

    if book not in {"md", "admin"}:
        raise SystemExit(f"seed_book 只用於 md 或 admin，不是 {book}")
    info = book_info(parse_month("2026-10"), book)
    if book == "md":
        folder = home() / "Oct_2026" / "MD"
        found = sorted(folder.glob("*#243*.docx")) if folder.exists() else []
        source = found[0] if found else folder / "payslip.docx"
        slips = parse_slips(source)
    else:
        source = home() / "Oct_2026" / "Admin" / "#197_0_office.xlsx"
        slips = parse_admin(source)
    facts_path = info["system"] / "daily_facts.xlsx"
    if facts is None and facts_path.exists():
        facts = pd.read_excel(facts_path)
    roster_names = sorted(set(facts["name"].astype(str))) if facts is not None else []
    stats = _roster_stats(facts)
    staff = load_staff()
    pay_rows = []
    balance_rows = []
    adjustment_rows = []
    unmatched = []
    for slip in slips:
        roster_name = match_roster_name(slip["slip_name"], slip.get("name_en", ""), slip.get("name_zh", ""), roster_names)
        if not roster_name:
            unmatched.append(slip["slip_name"])
        person = stats.get(roster_name, {})
        rest_calc = unused_rest(
            slip.get("opening_rest", 0), slip.get("rest_entitlement", 0),
            slip.get("statutory_days", 0), slip.get("taken_rest", 0),
        )
        rest_override = ""
        if abs(rest_calc - float(slip.get("unused_rest") or 0)) > 0.01:
            rest_override = slip.get("unused_rest")
        bonus_rule = attendance_bonus(
            bool(slip.get("bonus_eligible")),
            person.get("late_mins", slip.get("absent_mins", 0)),
            person.get("early_mins", 0),
            slip.get("unpaid_days") or 0,
            slip.get("absent_days") or 0,
            None,
            month=info["month"],
        )
        bonus_override = ""
        if slip.get("bonus") is not None and abs(bonus_rule - float(slip["bonus"])) > 0.01:
            bonus_override = slip["bonus"]
        employee_no = _link_employee(slip, staff)
        section = ""
        pay_rows.append({
            "employee_no": employee_no,
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "roster_name": roster_name,
            "basic_salary": slip["basic_salary"],
            "scheme": slip["scheme"],
            "rent_rate": 0.1 if slip["scheme"] == "rent" else 0,
            "rent_base": slip.get("rent_base") or "basic",
            "water": slip.get("water") or 0,
            "bonus_eligible": int(bool(slip.get("bonus_eligible"))),
            "rest_days_month": slip.get("rest_entitlement") or 0,
            "allowance_desc": slip.get("allowance_desc") or "",
            "allowance_amount": slip.get("allowance_amount") or 0,
            "allowance_note": "",
            "allowance_section": section,
        })
        al_lines = [dict(line) for line in slip.get("al_lines") or []]
        balance_rows.append({
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "opening_rest": slip.get("opening_rest") or 0,
            "opening_ot_hours": 0,
            "al_1_label": al_lines[0]["label"] if len(al_lines) > 0 else "",
            "al_1_opening": al_lines[0]["days"] if len(al_lines) > 0 else "",
            "al_2_label": al_lines[1]["label"] if len(al_lines) > 1 else "",
            "al_2_opening": al_lines[1]["days"] if len(al_lines) > 1 else "",
        })
        adjustment_rows.append({
            "staff_id": slip["staff_id"],
            "slip_name": slip["slip_name"],
            "unpaid_days": slip.get("unpaid_days") or 0,
            "absent_days": slip.get("absent_days") or 0,
            "statutory_days": slip.get("statutory_days") or 0,
            "sick_days": slip.get("sick_days") or 0,
            "annual_taken": slip.get("annual_taken") or 0,
            "birthday_days": slip.get("birthday_days") or 0,
            "taken_rest": slip.get("taken_rest") or 0,
            "taken_dates": slip.get("taken_dates") or "",
            "absent_mins": slip.get("absent_mins") or 0,
            "absent_text": "\n".join(slip.get("absent_lines") or []),
            "ot_text": "\n".join(slip.get("ot_lines") or []),
            "ot_pay": 0,
            "other_income": slip.get("other_income") or 0,
            "stated_extra": slip.get("stated_extra") or 0,
            "manual_delta": slip.get("manual_delta") or 0,
            "bonus_override": bonus_override,
            "rest_override": rest_override,
            "water_override": "",
            "note": "",
            "approved": "Y",
        })
    data = home() / "data"
    balances = data / "balances"
    balances.mkdir(parents=True, exist_ok=True)
    templates = home() / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    info["system"].mkdir(parents=True, exist_ok=True)
    pd.DataFrame(pay_rows).to_excel(home() / "data" / ("pay_table_md.xlsx" if book == "md" else "pay_table_admin.xlsx"), index=False)
    suffix = "_md" if book == "md" else "_admin"
    pd.DataFrame(balance_rows).to_excel(balances / f"2026_10_open{suffix}.xlsx", index=False)
    batch = 243 if book == "md" else 197
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        pd.DataFrame(adjustment_rows).to_excel(writer, sheet_name="lines", index=False)
        pd.DataFrame([{
            "pay_date": "4 Nov 2026",
            "salary_reference": "NB0498755329",
            "allowance_reference": "NB0498819638",
            "batch": batch,
        }]).to_excel(writer, sheet_name="meta", index=False)
    shutil.copyfile(source, info["slip_template"])
    if book == "md":
        _tidy_md_number(info["slip_template"])
    print(f"{book}: {len(pay_rows)} people")
    for name in unmatched:
        print(" - no roster", name)
    missing_staff = [row["slip_name"] for row in pay_rows if str(row["employee_no"]).startswith("未入檔")]
    for name in missing_staff:
        print(" - not in staff file", name)
    return {"unmatched": unmatched, "missing_staff": missing_staff}


if __name__ == "__main__":
    seed_october()
