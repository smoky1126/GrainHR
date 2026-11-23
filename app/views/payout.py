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

from app.context import _blocked, _context, _drafts, _month_label, _text
from app.views.overview import _mark

def _prepare_pay_keys(info, present):
    for book in present:
        booked = book_info(info, book)
        batch_key = f"batch-{book}"
        if batch_key not in st.session_state:
            st.session_state[batch_key] = int(suggested_batch(booked))
        salary_ref, allowance_ref = read_refs(booked)
        st.session_state.setdefault(f"salref-{book}", salary_ref)
        st.session_state.setdefault(f"allref-{book}", allowance_ref)

@st.dialog("製作全部糧單")
def _confirm_make_all(month_key, books, pay_text):
    st.write(f"將製作 {len(books)} 份糧單。出糧日期是 {pay_text}。")
    if not st.button("確定製作", type="primary"):
        return
    info = parse_month(month_key)
    try:
        with st.spinner("正在製作糧單，請稍候"):
            for book in books:
                booked = book_info(info, book)
                apply_pay_date(booked, pay_text)
                set_batch(booked, int(st.session_state[f"batch-{book}"]))
                set_refs(
                    booked,
                    st.session_state.get(f"salref-{book}", ""),
                    st.session_state.get(f"allref-{book}", ""),
                )
            run_slips(info, None, books=books)
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["slips_ready"] = True
    st.session_state["dirty"] = False
    st.session_state.pop("drafts", None)
    st.toast("糧單已製作")
    st.rerun()


@st.dialog("製作這份糧單")
def _confirm_make_one(month_key, book, label, pay_text, present):
    st.write(f"將製作{label}糧單。已有的糧單會被覆蓋。出糧日期是 {pay_text}。")
    if not st.button("確定製作", type="primary", key=f"yes-slip-{book}"):
        return
    info = parse_month(month_key)
    try:
        with st.spinner("正在製作糧單，請稍候"):
            for other in present:
                apply_pay_date(book_info(info, other), pay_text)
            booked = book_info(info, book)
            set_batch(booked, int(st.session_state[f"batch-{book}"]))
            set_refs(
                booked,
                st.session_state.get(f"salref-{book}", ""),
                st.session_state.get(f"allref-{book}", ""),
            )
            run_slips(info, None, books=[book])
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["slips_ready"] = True
    st.session_state["dirty"] = False
    st.session_state.pop("drafts", None)
    st.toast(f"{label}糧單已製作")
    st.rerun()


@st.dialog("製作個人糧單")
def _confirm_person(month_key, book, staff_id, name):
    st.write(f"將製作 {name} 的糧單。已有的個人糧單會被覆蓋。")
    if not st.button("確定製作", type="primary", key="yes-person"):
        return
    info = parse_month(month_key)
    draft = _drafts(info)
    booked = book_info(info, book or "bg")
    one = draft[(draft["staff_id"].astype(str) == staff_id) & (draft["book"].astype(str) == book)] if draft is not None and "book" in draft.columns else draft
    try:
        if book == "admin":
            from payroll.documents.slips_admin import write_person_slip
        else:
            from payroll.documents.slips import write_person_slip
        with st.spinner("正在製作個人糧單，請稍候"):
            path = write_person_slip(booked, one if one is not None and len(one) else draft, staff_id)
    except SystemExit as error:
        st.error(str(error))
        return
    st.toast(f"已製作 {path.name}")
    st.download_button("下載這份糧單", path.read_bytes(), file_name=path.name, key="one-slip")

def step_pay(info, status, draft, readonly):
    if status["pay"] == "wait":
        _mark("6. 出糧", "wait", "請先完成「新同事」。")
        return draft
    from app.access import books as visible_books
    shown = visible_books()
    present = [book for book in shown if pay_table_path(book).exists()]
    ready = all(book_info(info, book)["slip_output"].exists() for book in present) and present
    if ready and not st.session_state.get("dirty"):
        _mark("6. 出糧", "done", "糧單已做好，可以下載。")
    else:
        _mark("6. 出糧", "todo", "選出糧日期，然後按各份糧單的按鈕。")
    if st.session_state.get("dirty") and draft is not None:
        with st.spinner("正在計算總數"):
            draft = _drafts(info)
        st.session_state["dirty"] = False
    _prepare_pay_keys(info, present)
    current = parse_pay_date(_pay_date(info)) or date.today()
    top = st.columns([2, 1])
    picked = top[0].date_input("出糧日期", value=current, disabled=readonly, format="YYYY-MM-DD")
    st.caption(bonus_rule_text())
    blocked_by_book = {book: _blocked(draft, book) for book in present}
    any_blocked = any(rows is not None and len(rows) for rows in blocked_by_book.values())
    if not readonly and top[1].button(
        "製作全部糧單", type="primary", disabled=any_blocked,
        icon=":material/payments:", help="按已批准的數字製作這個月的糧單。",
    ):
        _confirm_make_all(info["key"], tuple(present), format_pay_date(picked))
    names = list(shown.values())
    if names:
        choice = st.segmented_control("這次出糧", names, default=names[0], key="payout-book") or names[0]
        shown = {book: label for book, label in shown.items() if label == choice}
    columns = st.columns(1)
    for column, (book, label) in zip(columns, shown.items()):
        with column:
            with st.container(border=True):
                if book not in present:
                    st.markdown(f"**{label}**")
                    chip("未有這份糧單", "muted")
                    continue
                booked = book_info(info, book)
                blocked = blocked_by_book[book]
                waiting = 0 if blocked is None else len(blocked)
                made = booked["slip_output"].exists() and not st.session_state.get("dirty")
                st.markdown(f"**{label}**")
                if waiting:
                    chip(f"{waiting} 人未批准", "block")
                elif made:
                    chip("已製作", "ok")
                else:
                    chip("可製作", "info")
                st.number_input(f"{label} 糧單編號", min_value=1, step=1, disabled=readonly, key=f"batch-{book}")
                salary = st.text_input("薪金交易編號", key=f"salref-{book}", disabled=readonly)
                st.text_input("津貼交易編號", key=f"allref-{book}", disabled=readonly)
                if not _text(salary):
                    st.warning(f"{label}未填薪金交易編號。糧單上的交易編號會是空白。")
                if waiting:
                    names = "、".join(_text(name) for name in blocked["slip_name"].head(8))
                    st.caption(f"還有 {waiting} 人未批准（{names}），未能製作這份糧單。")
                if not readonly and st.button(f"製作{label}糧單", disabled=waiting > 0):
                    _confirm_make_one(info["key"], book, label, format_pay_date(picked), tuple(present))
                slips = booked["slip_output"]
                if slips.exists():
                    st.download_button(f"下載{label}糧單", slips.read_bytes(), file_name=slips.name, key=f"down-{book}")
                if book == "bg":
                    summary = info["output"] / "allowance_summary.xlsx"
                    if summary.exists():
                        st.download_button("下載津貼表", summary.read_bytes(), file_name=summary.name)
    st.markdown("**其他下載**")
    if draft is not None and len(draft) and "staff_id" in draft.columns and not readonly:
        from app.access import see_pay
        paid = draft[draft["pay_this"].astype(bool)] if "pay_this" in draft.columns else draft
        if "book" in paid.columns:
            paid = paid[paid["book"].map(lambda book: see_pay(book))]
        labels = [f"{_text(row.slip_name)}（{_text(row.staff_id)}）" for _, row in paid.iterrows()]
        ids = [_text(row.staff_id) for _, row in paid.iterrows()]
        books_for = [_text(row.book) for _, row in paid.iterrows()] if "book" in paid.columns else ["bg"] * len(ids)
        if labels:
            chosen = st.selectbox("個人糧單", labels)
            if st.button("製作這個人的糧單"):
                index = labels.index(chosen)
                _confirm_person(info["key"], books_for[index] or "bg", ids[index], labels[index])
    from app.access import see_pay
    report = info["output"] / "payroll_draft.xlsx"
    if see_pay("admin") and not readonly and st.button("匯出 Excel 報告"):
        try:
            with st.spinner("正在匯出 Excel 報告"):
                from payroll.documents.report import write_report
                write_report(info)
        except PermissionError:
            st.error("請先關閉 Excel 中的 payroll_draft.xlsx，然後再試。")
        except SystemExit as error:
            st.error(str(error))
        else:
            st.toast("報告已匯出")
    if see_pay("admin") and report.exists():
        st.download_button("下載 Excel 報告", report.read_bytes(), file_name=report.name, key="report-download")
    return draft

def _pt_payout(info, readonly):
    st.markdown("**兼職（另一次過數）**")
    st.caption(f"{PT_BOOKS['bg']}和 {PT_BOOKS['md']}是兩次過數，交易編號不要和全職薪金用同一個。")
    try:
        staff = load_staff()
        rows = build_pt(info, staff)
    except SystemExit as error:
        st.error(str(error))
        return
    columns = st.columns(2)
    for column, (company, label) in zip(columns, PT_BOOKS.items()):
        with column:
            with st.container(border=True):
                people = [row for row in rows if row["company"] == company and row["pay_this"] == "Y"]
                transfer = sum(row["transfer"] for row in people)
                employer = sum(row["employer_mpf"] for row in people)
                st.markdown(f"**{label}**")
                chips([(f"{len(people)} 人", "info"), (f"過數 {hk(transfer)}", "ok"), (f"僱主強積金 {hk(employer)}", "muted")])
                stored = pt_reference(info, company)
                typed = st.text_input(
                    f"{label}交易編號", value=stored, disabled=readonly, key=f"ptref-{info['key']}-{company}",
                )
                if not readonly and st.button(f"儲存{label}交易編號", key=f"save-ptref-{company}"):
                    try:
                        set_pt_reference(info, company, typed)
                    except SystemExit as error:
                        st.error(str(error))
                    else:
                        st.toast("交易編號已儲存")
                        st.rerun()
                if not stored:
                    st.warning(f"{label}未填交易編號。總表上的交易編號會是空白。")
                data = summary_book(info, company, rows, stored)
                st.download_button(
                    f"下載{label}總表",
                    data,
                    file_name=summary_name(info, company),
                    key=f"pt-down-{company}",
                )

def page_payout():
    from app.components.cards import empty_state, first_tip
    from payroll.core.history import is_issued
    info, readonly, draft, staff, table = _context(steps=True, edit=True)
    page_header("出糧", _month_label(info["key"]), purpose="選出糧日期，然後製作糧單。")
    if is_issued(info["key"]):
        empty_state("這個月已出糧", "糧單已經發出，可以在月份紀錄下載。", "前往月份紀錄", "pages/records.py")
        return
    first_tip("payout", "先完成審核，再按「製作全部糧單」。已出糧的月份不會重新計算。")
    slips_ready = bool(st.session_state.get("slips_ready"))
    status = step_status(info, draft, staff, table, slips_ready=slips_ready)
    step_pay(info, status, draft, readonly)
    _pt_payout(info, readonly)
