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

from app.context import _context, _month_label, _text
from app.views.overview import _mark
from app.views.salary_editor import _pt_editor, _salary_editor

def step_joiners(info, status, staff, table, readonly):
    if status["joiners"] == "wait":
        _mark("2. 新同事", "wait", "請先完成上一步。")
        return
    from app.access import see_pay
    from payroll.staff.directory import staff_group
    people = [
        record for record in new_joiners(staff, table, info)
        if see_pay(staff_group(record.get("department"), record.get("employment"), record.get("position"), record.get("sheet")))
    ]
    if not people:
        _mark("2. 新同事", "done", "沒有新同事。")
        return
    _mark("2. 新同事", "todo", f"有 {len(people)} 位新同事未設定薪金。")
    names = unlinked_roster_names(info, table)
    scheme_labels = list(SCHEME.values())
    from app.access import books as visible_books
    book_labels = list(visible_books().values())
    for record in people:
        employee_no = _text(record["employee_no"])
        name = _text(record.get("name_zh")) or _text(record.get("name_en")) or employee_no
        with st.form(f"join-{employee_no}"):
            st.write(f"{name}（{employee_no}）")
            if employee_no in MANUAL_PAY:
                st.info(MANUAL_PAY[employee_no])
            salary = st.number_input("基本薪金", min_value=0.0, step=100.0, key=f"salary-{employee_no}")
            scheme = st.radio(
                "計薪方式", scheme_labels,
                index=scheme_labels.index(SCHEME[default_scheme(record)]),
                horizontal=True, key=f"scheme-{employee_no}",
            )
            book_label = st.radio("糧單", book_labels, horizontal=True, key=f"book-{employee_no}")
            roster = st.selectbox("更表姓名", [""] + names, key=f"roster-{employee_no}")
            if st.form_submit_button("儲存", disabled=readonly):
                book = next(key for key, label in BOOKS.items() if label == book_label)
                try:
                    staff_id = add_new_joiner(
                        book_info(info, book), employee_no, name, salary, scheme, roster, book=book,
                    )
                except SystemExit as error:
                    st.error(str(error))
                else:
                    st.session_state.pop("draft", None)
                    st.session_state["dirty"] = True
                    st.toast(f"已加入，糧單編號 {staff_id}")
                    st.rerun()

def page_salary():
    info, readonly, draft, staff, table = _context(steps=True)
    status = step_status(info, draft, staff, table)
    page_header("薪金表", _month_label(info["key"]))
    with st.expander(f"新同事（{status['joiner_count']}）", expanded=bool(status["joiner_count"])):
        step_joiners(info, status, staff, table, readonly)
    _salary_editor(info, readonly)
    _pt_editor(info, readonly)
