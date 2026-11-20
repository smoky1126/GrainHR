"""The guided page, approve-all, overtime pay, and a new joiner's slip."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_packages"))
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"

from payroll.core.config import scratch_dir
from payroll.setup.demo import build_demo

HOME = scratch_dir("app")
os.environ["PAYROLL_HOME"] = str(HOME)
os.environ["PAYROLL_DEMO"] = "1"
os.chdir(ROOT)

import pandas as pd

from payroll.core.config import parse_month
from payroll.core.money import overtime_pay
from payroll.pay.payroll import build_draft
from payroll.documents.parse_slips import parse_slips
from payroll.pay.review import approve_all, save_one
from payroll.pay.run import run_slips
from payroll.staff.staff import add_new_joiner, ensure_pay_table, load_staff
from payroll.core.labels import BOOKS
from app.state import default_scheme, new_joiners, problem_people


def _text(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _prepare():
    print("copying the October demo")
    build_demo(force=True, dest=HOME)
    info = parse_month("2026-10")
    facts = info["system"] / "daily_facts.xlsx"
    daka = info["daka"]
    if daka.exists():
        os.utime(facts, (daka.stat().st_mtime + 60, daka.stat().st_mtime + 60))
    staff = load_staff()
    table = ensure_pay_table()
    joiners = new_joiners(staff, table, info)
    if not joiners:
        raise SystemExit("the demo should have at least one new joiner")
    if default_scheme({"sheet": "內地勞工"}) != "rent":
        raise SystemExit("內地勞工新同事應預設為扣租金")
    mainland = next((record for record in joiners if _text(record.get("sheet")) == "內地勞工"), None)
    if mainland is not None and default_scheme(mainland) != "rent":
        raise SystemExit("內地勞工新同事應預設為扣租金")
    slip_id = None
    slip_no = None
    for record in joiners:
        employee_no = _text(record["employee_no"])
        name = _text(record["name_zh"]) or _text(record["name_en"]) or employee_no
        staff_id = add_new_joiner(info, employee_no, name, 20000, "強積金", "")
        if slip_id is None:
            slip_id = staff_id
            slip_no = employee_no
    paid = table[table["scheme"].astype(str).str.strip().eq("mpf")]
    person = paid.iloc[0]
    employee_no = _text(person["employee_no"])
    from payroll.pay.review import apply_pay
    apply_pay([{
        "employee_no": employee_no,
        "slip_name": _text(person["slip_name"]),
        "roster_name": _text(person["roster_name"]),
        "basic_salary": 20000,
        "scheme": _text(person["scheme"]),
        "rent_rate": person["rent_rate"],
        "rent_base": _text(person["rent_base"]) or "basic",
        "water": person["water"],
        "bonus_eligible": person["bonus_eligible"],
        "rest_days_month": person["rest_days_month"],
        "allowance_desc": _text(person["allowance_desc"]),
        "allowance_amount": person["allowance_amount"],
        "allowance_note": _text(person["allowance_note"]),
        "allowance_section": _text(person["allowance_section"]),
    }])
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    lines["approved"] = ""
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)
    from payroll.core.config import book_info
    md_lines = pd.read_excel(book_info(info, "md")["adjustments"], sheet_name="lines")
    md_meta = pd.read_excel(book_info(info, "md")["adjustments"], sheet_name="meta")
    md_lines.loc[md_lines.index[0], "approved"] = ""
    md_id = _text(md_lines.iloc[0]["staff_id"])
    with pd.ExcelWriter(book_info(info, "md")["adjustments"], engine="openpyxl") as writer:
        md_lines.to_excel(writer, sheet_name="lines", index=False)
        md_meta.to_excel(writer, sheet_name="meta", index=False)
    before = build_draft(info, write=False)
    target = before[before["employee_no"].astype(str) == employee_no].iloc[0]
    return info, before, _text(target["staff_id"]), float(target["net"]), slip_id, slip_no, md_id


def _titles(app):
    values = []
    for item in list(app.title) + list(app.subheader) + list(app.markdown):
        values.append(str(getattr(item, "value", "")))
    return " ".join(values)


def _open(app, path):
    app.switch_page(path)
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    return _titles(app)


def _page(info, problem_ids, md_id, pending_ids):
    from streamlit.testing.v1 import AppTest
    print("opening the page")
    app = AppTest.from_file(str(ROOT / "app" / "main.py"))
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    home = _titles(app)
    if "今日出勤" not in home or "立即更新" not in [item.label for item in app.button]:
        raise SystemExit(f"沒有打開今日出勤：{home}")
    overview = _open(app, "pages/overview.py")
    for word in (BOOKS["bg"], BOOKS["md"], BOOKS["admin"]):
        if word not in overview:
            raise SystemExit(f"總覽沒有「{word}」。見到：{overview}")
    from payroll.staff.staff import latest_staff_file
    staff_file = latest_staff_file()
    staff_stamp = staff_file.stat().st_mtime
    app.switch_page("pages/staff.py")
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    labels = [item.label for item in app.button]
    if "新增員工" not in labels:
        raise SystemExit(f"員工頁沒有「新增員工」：{labels}")
    if staff_file.stat().st_mtime != staff_stamp:
        raise SystemExit("員工頁寫入了真正的員工檔。")
    attendance = _open(app, "pages/attendance.py")
    if "出勤" not in attendance and "放入 DAKA" not in attendance:
        raise SystemExit(f"沒有打開出勤：{attendance}")
    salary = _open(app, "pages/salary.py")
    if "新同事" not in salary and "薪金表" not in salary:
        raise SystemExit(f"沒有打開薪金表：{salary}")
    review = _open(app, "pages/review.py")
    if "處理問題" not in review and "審核" not in review:
        raise SystemExit(f"沒有打開審核：{review}")
    choices = []
    for radio in app.radio:
        choices.extend(list(radio.options or []))
    if "支薪" not in choices or "補鐘" not in choices:
        raise SystemExit(f"加班選項應該是支薪和補鐘，見到：{choices}")
    button = next((item for item in app.button if item.label == "全部批准"), None)
    if button is None:
        raise SystemExit("頁面沒有「全部批准」。")
    button.click()
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    confirm = next((item for item in app.button if item.label == "確定批准"), None)
    if confirm is None:
        raise SystemExit("全部批准之後沒有「確定批准」。")
    confirm.click()
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    from payroll.core.config import book_info
    saved = pd.read_excel(info["adjustments"], sheet_name="lines")
    saved["staff_id"] = saved["staff_id"].map(_text)
    saved["approved"] = saved["approved"].map(_text)
    for staff_id in problem_ids:
        rows = saved[saved["staff_id"] == staff_id]
        approved = "" if rows.empty else rows.iloc[0]["approved"]
        if staff_id in pending_ids:
            if approved == "Y":
                raise SystemExit(f"全部批准不應確認未核對加班備註的 {staff_id}")
        elif rows.empty or approved != "Y":
            raise SystemExit(f"全部批准後 {staff_id} 仍未是 Y")
    md_saved = pd.read_excel(book_info(info, "md")["adjustments"], sheet_name="lines")
    md_saved["staff_id"] = md_saved["staff_id"].map(_text)
    md_saved["approved"] = md_saved["approved"].map(_text)
    md_row = md_saved[md_saved["staff_id"] == md_id]
    if md_row.empty or md_row.iloc[0]["approved"] != "Y":
        raise SystemExit(f"全部批准後 {BOOKS['md']} {md_id} 仍未是 Y")
    from payroll.core.config import book_info
    outputs = {
        "bg": book_info(info, "bg")["slip_output"],
        "md": book_info(info, "md")["slip_output"],
        "admin": book_info(info, "admin")["slip_output"],
    }
    before = {key: path.stat().st_mtime if path.exists() else None for key, path in outputs.items()}
    payout = _open(app, "pages/payout.py")
    if "出糧" not in payout:
        raise SystemExit(f"沒有打開出糧：{payout}")
    make = next((item for item in app.button if item.label == "製作" + BOOKS["md"] + "糧單"), None)
    if make is None:
        raise SystemExit("頁面沒有製作" + BOOKS["md"] + "糧單。")
    if getattr(make, "disabled", False):
        raise SystemExit("製作糧單不應被另一份的未批准擋住。")
    make.click()
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    if not outputs["md"].exists() or outputs["md"].stat().st_mtime == before["md"]:
        raise SystemExit("製作第二份糧單沒有更新 payslips_md.docx")
    for key in ("bg", "admin"):
        after = outputs[key].stat().st_mtime if outputs[key].exists() else None
        if after != before[key]:
            raise SystemExit(f"製作第二份糧單也更新了 {outputs[key].name}")
    one = next((item for item in app.button if item.label == "製作這個人的糧單"), None)
    if one is None:
        raise SystemExit("頁面沒有「製作這個人的糧單」。")
    one.click()
    app.run(timeout=300)
    if app.exception:
        raise SystemExit(app.exception)
    made = []
    for book in ("bg", "md", "admin"):
        folder = book_info(info, book)["output"] / "個別"
        if folder.exists():
            made.extend(folder.glob("*"))
    if not made:
        raise SystemExit("個人糧單沒有產生檔案")


def _overtime(info, staff_id, net_before):
    save_one(info, staff_id, {"ot_choice": "支薪", "ot_hours_paid": 3})
    after = build_draft(info, write=False)
    row = after[after["staff_id"].astype(str) == staff_id].iloc[0]
    added = round(float(row["net"]) - net_before, 2)
    expected = overtime_pay(20000, 31, 3)
    if added != expected:
        raise SystemExit(f"支薪 3 小時應加 {expected}，實際加了 {added}")
    return after


def _slip(info, draft, staff_id):
    run_slips(info, draft)
    slips = parse_slips(info["output"] / "payslips.docx")
    found = [slip for slip in slips if slip["staff_id"] == staff_id]
    if not found:
        raise SystemExit(f"糧單沒有新同事 {staff_id}")
    row = draft[draft["staff_id"].astype(str) == staff_id].iloc[0]
    if abs(float(found[0]["net"]) - float(row["net"])) > 0.02:
        raise SystemExit(f"{staff_id} 糧單淨薪 {found[0]['net']}，應為 {row['net']}")


def main():
    info, before, staff_id, net_before, slip_id, _slip_no, md_id = _prepare()
    problems = problem_people(before)
    problem_ids = [_text(value) for value in problems["staff_id"] if _text(value)]
    pending_ids = {
        _text(row.staff_id) for _, row in before.iterrows()
        if _text(row.staff_id) and (
            (_text(row.get("ot_suggest")) and not _text(row.get("ot_text")))
            or _text(row.get("absence_pending"))
        )
    }
    if staff_id not in problem_ids and not problem_ids:
        raise SystemExit("沒有需要批准的人")
    _page(info, problem_ids, md_id, pending_ids)
    # approve_all is what the button calls; keep the direct call as a guard if the
    # page approved a filtered set. The assertion above already checked the button.
    approve_all(info, problem_ids)
    after = _overtime(info, staff_id, net_before)
    _slip(info, after, slip_id)
    print("app checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
