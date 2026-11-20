"""Run one month: copy rosters, check attendance, then make the salary slips."""

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Downcasting object dtype")
warnings.filterwarnings("ignore", message="Data Validation extension")

from payroll.attendance.attendance import run_attendance
from payroll.core.config import home, parse_month
from payroll.pay.payroll import build_draft, write_closing
from payroll.setup.regression import attendance_differences, pay_differences
from payroll.attendance.rosters import RosterProblem, copy_rosters
from payroll.setup.seed import seed_october
from payroll.documents.slips import fill_document, write_allowance_summary
from payroll.staff.staff import pay_table_path


def _ready(info, facts):
    from payroll.setup.seed import seed_book
    master = home() / "data" / "staff_master.xlsx"
    if info["key"] == "2026-10" and not pay_table_path().exists() and not master.exists():
        seed_october(facts)
    if info["key"] == "2026-10":
        for book in ("md", "admin"):
            if not pay_table_path(book).exists():
                seed_book(book, facts)


def ensure_draft_closed(info):
    path = info["output"] / "payroll_draft.xlsx"
    if not path.exists():
        return
    try:
        with path.open("a+b"):
            pass
    except PermissionError:
        raise SystemExit("請先關閉 Excel 中的 payroll_draft.xlsx，然後再試。") from None


def run_check(info, open_workbook=False, fetch=True):
    ensure_draft_closed(info)
    info["folder"].mkdir(parents=True, exist_ok=True)
    info["system"].mkdir(parents=True, exist_ok=True)
    if not Path(info["daka"]).exists():
        raise SystemExit(f"本月的 DAKA 還沒有同步：{info['daka']}")
    if fetch:
        try:
            copy_rosters(info)
        except RosterProblem as error:
            raise SystemExit("更表未能複製：\n" + str(error))
    elif not Path(info["rosters"]).exists():
        raise SystemExit(f"找不到更表資料夾：{info['rosters']}")
    check_path = info["system"] / f"{info['sheet']}考勤核對表.xlsx"
    facts = run_attendance(
        info["daka"], info["rosters"], info["sheet"], check_path,
        info["system"] / "daily_facts.xlsx",
    )
    _ready(info, facts)
    draft = build_draft(info, facts)
    from payroll.documents.report import write_report
    try:
        write_report(info)
    except PermissionError:
        raise SystemExit("請先關閉 Excel 中的 payroll_draft.xlsx，然後再試。") from None
    report = []
    if info["key"] == "2026-10":
        attendance = attendance_differences(check_path)
        pay = pay_differences(draft)
        report.append(f"考勤差異：{len(attendance)}")
        report.extend(attendance[:20])
        report.append(f"薪金差異：{len(pay)}")
        report.extend(pay)
        if attendance:
            report.append("上面是同已儲存考勤表不同的格。薪金仍然用這些更表。")
        if pay:
            report.append("薪金同已儲存的十月糧單不同。草稿用這些更表。")
    flagged = int(
        (draft["show_on_review"] & draft["review"].astype(str).str.strip().ne("")).sum()
    )
    report.append(f"草稿人數：{len(draft)}")
    report.append(f"需審核人數：{flagged}")
    text = "\n".join(report)
    (info["system"] / "regression.txt").write_text(text, encoding="utf-8")
    print(text)
    draft_path = info["output"] / "payroll_draft.xlsx"
    print(f"draft: {draft_path}")
    if open_workbook:
        os.startfile(draft_path)
    return draft


def pd_read_facts(info):
    import pandas as pd
    return pd.read_excel(info["system"] / "daily_facts.xlsx")


def _pay_date(info):
    import pandas as pd
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    if meta.empty or "pay_date" not in meta.columns:
        return ""
    value = meta.iloc[0]["pay_date"]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _missing_layouts(draft):
    """People who are paid but have no slip number, so a Word slip cannot be built."""
    missing = []
    people = draft[draft["pay_this"].astype(bool)]
    for _, row in people.iterrows():
        staff_id = "" if row.staff_id is None else str(row.staff_id).strip()
        if not staff_id or staff_id.lower() == "nan":
            missing.append(str(row.slip_name))
    return missing


def _draft_from_facts(info):
    if not (info["system"] / "daily_facts.xlsx").exists():
        return None
    return build_draft(info, pd_read_facts(info), write=False)


def run_recalculate(info):
    draft = _draft_from_facts(info)
    if draft is None:
        raise SystemExit("本月的 DAKA 還沒有同步。")
    print(f"draft: {info['output'] / 'payroll_draft.xlsx'}")
    return draft


def _one_slip(booked, draft):
    if not _pay_date(booked):
        if booked.get("book", "bg") == "bg":
            raise SystemExit("請在「出糧」選擇出糧日期，然後再製作糧單。")
        return None
    on_payroll = draft["pay_this"].astype(bool)
    review = draft["review"].astype(str).str.strip()
    needs_review = review.ne("") & review.str.lower().ne("nan")
    if "ot_suggest" in draft.columns and "ot_text" in draft.columns:
        suggest = draft["ot_suggest"].astype(str).str.strip()
        saved = draft["ot_text"].astype(str).str.strip()
        pending = suggest.ne("") & suggest.str.lower().ne("nan") & (saved.eq("") | saved.str.lower().eq("nan"))
        needs_review = needs_review | pending
    approved = draft["approved"].astype(str).str.upper().isin(["Y", "是"])
    blocked = draft[on_payroll & needs_review & ~approved]
    if not blocked.empty:
        names = ", ".join(blocked["slip_name"].astype(str).head(8))
        raise SystemExit(
            f"有 {len(blocked)} 人未批准（{names}）。"
            "請在「處理問題」按批准，然後再製作糧單。"
        )
    missing = _missing_layouts(draft)
    if missing:
        names = ", ".join(missing[:8])
        print(f"有 {len(missing)} 人未能製作糧單：{names}。他們沒有糧單編號。")
    if booked.get("book") == "admin":
        from payroll.documents.slips_admin import fill_admin
        document = fill_admin(booked, draft)
    else:
        document = fill_document(booked, draft)
    closing = write_closing(booked, draft)
    print(f"slips: {document}")
    print(f"closing balances: {closing}")
    return document


def run_slips(info, draft=None, books=None):
    from payroll.core.config import book_info
    caller = info.get("book", "bg")
    first = None
    chosen = ("bg", "md", "admin") if not books else tuple(books)
    for book in chosen:
        if not pay_table_path(book).exists():
            continue
        booked = book_info(info, book)
        if book == caller and draft is not None:
            this = draft
        else:
            this = _draft_from_facts(booked)
        if this is None:
            if book == caller:
                this = run_check(info, fetch=False)
            else:
                continue
        document = _one_slip(booked, this)
        if first is None and document is not None:
            first = document
        if book == "bg" and this is not None:
            summary = write_allowance_summary(booked, booked["period_text"].split("(")[0].strip(), this)
            print(f"allowances: {summary}")
    return first


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print("雙擊 薪酬系統.bat，或：")
        print("  python -m payroll.pay.run 2026-10 check")
        print("  python -m payroll.pay.run 2026-10 recalc")
        print("  python -m payroll.pay.run 2026-10 slips")
        return 0
    info = parse_month(argv[0])
    action = argv[1] if len(argv) > 1 else "check"
    if action == "check":
        run_check(info, open_workbook=True)
    elif action == "recalc":
        run_recalculate(info)
    elif action == "slips":
        run_slips(info)
    elif action == "all":
        draft = run_check(info, open_workbook=True)
        run_slips(info, draft)
    elif action == "folder":
        folder = info["folder"]
        if not folder.exists():
            raise SystemExit("這個月還沒有資料。DAKA 還沒有同步。")
        os.startfile(folder)
    else:
        raise SystemExit(f"沒有這個動作：{action}。可用 check、recalc、slips 或 folder。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
