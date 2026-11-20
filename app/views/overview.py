import html
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.components.cards import callout, kpi, page_header, section
from app.components.chips import chip, chips, legend, stepper
from app.components.format import hk
from app.components.tables import style_days as _day_style
from app.components.theme import inject, show_logo
from app.lock import claim
from app.state import (
    default_scheme, format_pay_date, last_month, new_joiners, parse_pay_date, problem_people,
    roster_report, step_status, unlinked_roster_names,
)
from payroll.core.config import book_info, home, parse_month
from payroll.core.holidays import holiday_count, holiday_known
from payroll.core.labels import (
    BOOKS, MANUAL_PAY, NEW_JOINER, PAY_HEADINGS, SCHEME, SCHEME_STORED, SECTION, YES, chinese_note, show,
)
from payroll.core.money import bonus_rule_text
from payroll.pay.part_time import (
    PT_BOOKS, build_pt, pt_reference, save_pt_lines, set_pt_reference, summary_book, summary_name,
)
from payroll.pay.payroll import pay_sheet_rows
from payroll.pay.review import apply_pay, apply_pay_date, approve_all, save_one
from payroll.pay.run import _draft_from_facts, _pay_date, run_check, run_slips
from payroll.staff.staff import (
    add_new_joiner, ensure_pay_table, load_staff, pay_table_path, read_refs, set_batch, set_refs,
    suggested_batch,
)

from app.context import _blocked, _context, _month_label, _pull_daka

def _mark(title, state, detail):
    section(title, state, detail)

def _next_page(status, waiting):
    if status["daka"] != "done":
        return "pages/attendance.py", "處理出勤"
    if status["joiners"] != "done":
        return "pages/salary.py", "設定新同事"
    if waiting:
        return "pages/review.py", "去審核"
    return "pages/payout.py", "去出糧"

def page_overview():
    _pull_daka()
    info, _readonly, draft, staff, table = _context(steps=True)
    slips_ready = bool(st.session_state.get("slips_ready"))
    status = step_status(info, draft, staff, table, slips_ready=slips_ready)
    page_header("總覽", _month_label(info["key"]))
    if draft is None or "book" not in getattr(draft, "columns", []):
        columns = st.columns(4)
        for column, (label, value) in zip(columns, (("本月出糧", "—"), ("淨薪金", "—"), ("未批准", "—"), ("糧單", "—"))):
            with column:
                kpi(label, value, "請先到出勤頁", "muted")
        st.info("未有計算結果。請先到出勤頁。")
        return
    paid_all = draft[draft["pay_this"].astype(bool)] if "pay_this" in draft.columns else draft
    net_all = float(paid_all["net"].sum()) if len(paid_all) and "net" in paid_all.columns else 0
    waiting_all = 0
    made = 0
    for book in BOOKS:
        blocked = _blocked(draft, book)
        waiting_all += 0 if blocked is None else len(blocked)
        if book_info(info, book)["slip_output"].exists():
            made += 1
    columns = st.columns(4)
    cards = (
        ("本月出糧", f"{len(paid_all)} 人", "三份糧單合計", "info"),
        ("淨薪金", hk(net_all), "未計未批准的改動", "ok"),
        ("未批准", f"{waiting_all} 人", "審核後才能出糧", "block" if waiting_all else "ok"),
        ("糧單", f"{made} / {len(BOOKS)}", "已製作的檔案", "ok" if made == len(BOOKS) else "todo"),
    )
    for column, (label, value, note, tone) in zip(columns, cards):
        with column:
            kpi(label, value, note, tone)
    st.write("")
    cost_rows = []
    for book, label in BOOKS.items():
        group = draft[draft["book"].astype(str).eq(book)]
        paid = group[group["pay_this"].astype(bool)] if "pay_this" in group.columns else group
        waiting = _blocked(draft, book)
        waiting_n = 0 if waiting is None else len(waiting)
        net = float(paid["net"].sum()) if len(paid) and "net" in paid.columns else 0
        cost_rows.append({"糧單": label, "淨薪金": net})
        needs = group[group["pay_this"].astype(bool)] if "pay_this" in group.columns else group
        review = needs["review"].astype(str).str.strip() if len(needs) and "review" in needs.columns else None
        flagged = needs[review.ne("") & review.str.lower().ne("nan")] if review is not None else needs.iloc[0:0]
        approved = flagged["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"]) if len(flagged) else []
        done_n = int(approved.sum()) if len(flagged) else 0
        total_n = len(flagged)
        ratio = 1.0 if not total_n else done_n / total_n
        with st.container(border=True):
            st.markdown(f"**{label}**")
            chips([
                (f"{len(paid)} 人", "info"),
                (hk(net), "ok"),
                (f"未批准 {waiting_n} 人", "block" if waiting_n else "ok"),
            ])
            st.progress(ratio, text=f"審核 {done_n}/{total_n}" if total_n else "沒有待審核的人")
            path, link = _next_page(status, waiting_n)
            st.page_link(path, label=link, icon=":material/arrow_forward:")
    if cost_rows:
        import pandas as pd
        from app.components.charts import bars
        st.altair_chart(bars(pd.DataFrame(cost_rows), "糧單", "淨薪金", title="各糧單淨薪金"), use_container_width=True)
        st.caption("各糧單淨薪金合計，未計未批准的改動。")
