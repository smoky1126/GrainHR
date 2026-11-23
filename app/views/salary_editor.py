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

from app.context import _show_choice, _text

def _pt_frame(rows):
    scheme_options = [SCHEME["mpf"], SCHEME["none"]]
    frame = pd.DataFrame([{
        "employee_no": row["employee_no"],
        "name": row["name_zh"] or row["name_en"],
        "hours": row["hours"],
        "extra_hours": row["extra_hours"],
        "extra_note": row["extra_note"],
        "rate": row["rate"],
        "salary": row["salary"],
        "employer_mpf": row["employer_mpf"],
        "employee_mpf": row["employee_mpf"],
        "transfer": row["transfer"],
        "scheme": SCHEME.get(row["scheme"], SCHEME["mpf"]),
        "bank": row["bank"],
        "account": row["account"],
        "pay_this": "是" if row["pay_this"] == "Y" else "否",
    } for row in rows])
    return frame, scheme_options

def _pt_editor(info, readonly):
    st.markdown("**兼職薪金**")
    st.caption(
        f"兼職不計入全職糧單。{PT_BOOKS['bg']}和 {PT_BOOKS['md']}各有自己的交易編號。"
        "時數是更表的上班時間，加班不會加進去，休假也不計。"
        "未滿 60 日，或薪金不足 $7,100，僱員強積金是 0。僱主強積金仍是薪金的 5%，除非選了不扣強積金。"
        "其他時數用來加減工時，例如無薪休息。"
    )
    try:
        staff = load_staff()
        rows = build_pt(info, staff)
    except SystemExit as error:
        st.error(str(error))
        return
    chosen = st.selectbox("兼職糧單", list(PT_BOOKS.values()), key="pt-book")
    company = next(key for key, label in PT_BOOKS.items() if label == chosen)
    shown = [row for row in rows if row["company"] == company]
    if not shown:
        st.caption("這份兼職這個月沒有人。")
        return
    frame, scheme_options = _pt_frame(shown)
    locked = ["employee_no", "name", "hours", "salary", "employer_mpf", "employee_mpf", "transfer"]
    edited = st.data_editor(
        frame,
        column_config={
            "employee_no": st.column_config.TextColumn("員工編號", disabled=True, pinned=True),
            "name": st.column_config.TextColumn("姓名", disabled=True, pinned=True),
            "hours": st.column_config.NumberColumn("更表時數", disabled=True, format="%.2f"),
            "extra_hours": st.column_config.NumberColumn(
                "其他時數", disabled=readonly, format="%.2f", min_value=-400, max_value=400,
            ),
            "extra_note": st.column_config.TextColumn("備註", disabled=readonly),
            "rate": st.column_config.NumberColumn(
                "時薪", disabled=readonly, format="%.2f", min_value=0, max_value=10000,
            ),
            "salary": st.column_config.NumberColumn("薪金", disabled=True, format="accounting"),
            "employer_mpf": st.column_config.NumberColumn("僱主強積金", disabled=True, format="accounting"),
            "employee_mpf": st.column_config.NumberColumn("僱員強積金", disabled=True, format="accounting"),
            "transfer": st.column_config.NumberColumn("過數金額", disabled=True, format="accounting"),
            "scheme": st.column_config.SelectboxColumn("計薪方式", options=scheme_options, disabled=readonly),
            "bank": st.column_config.TextColumn("銀行", disabled=readonly),
            "account": st.column_config.TextColumn("戶口", disabled=readonly),
            "pay_this": st.column_config.SelectboxColumn("本月出糧", options=["是", "否"], disabled=readonly),
        },
        column_order=[
            "employee_no", "name", "hours", "extra_hours", "rate", "salary",
            "employer_mpf", "employee_mpf", "transfer", "scheme", "pay_this",
            "bank", "account", "extra_note",
        ],
        disabled=locked,
        hide_index=True,
        key=f"pt-grid-{info['key']}-{company}",
    )
    if _grid_dirty(frame, edited):
        chip("未儲存", "todo")
    if readonly or not st.button("儲存兼職薪金", type="primary", disabled=readonly):
        return
    payload = edited.to_dict("records")
    for row in payload:
        row["scheme"] = SCHEME_STORED.get(_text(row.get("scheme")), "mpf")
        row["pay_this"] = "N" if _text(row.get("pay_this")) == "否" else "Y"
    try:
        save_pt_lines(info, payload)
    except SystemExit as error:
        st.error(str(error))
        return
    st.toast("兼職薪金已儲存")
    st.rerun()

_PAY_HELP = {
    "basic_salary": "本月基本薪金。",
    "rent_amount": "只扣內地勞工。本地員工儲存時會變成 0。",
    "water": "只扣內地勞工。請填實額。",
    "electricity": "只扣內地勞工。請填實額。",
    "transport_amount": "填實額。和健康津貼相加就是糧單上的津貼。",
    "health_amount": "填實額。和交通津貼相加就是糧單上的津貼。",
}

_MONEY_COLUMNS = {"basic_salary", "rent_amount", "water", "electricity", "transport_amount", "health_amount"}

def _grid_dirty(original, edited):
    if list(original.columns) != list(edited.columns) or len(original) != len(edited):
        return True
    for column in original.columns:
        for left, right in zip(original[column].tolist(), edited[column].tolist()):
            if _text(left) == _text(right):
                continue
            try:
                if abs(float(left) - float(right)) < 0.001:
                    continue
            except (TypeError, ValueError):
                return True
            return True
    return False

def _salary_editor(info, readonly):
    st.markdown("**薪金資料**")
    from app.access import books as visible_books
    shown = visible_books()
    labels = list(shown.values())
    if not labels:
        st.info("沒有可以查看的糧單。")
        return
    chosen = st.selectbox("糧單", labels, key="salary-book")
    book = next(key for key, label in shown.items() if label == chosen)
    try:
        staff = load_staff()
        table = ensure_pay_table(book=book)
    except SystemExit as error:
        st.error(str(error))
        return
    rows = pay_sheet_rows(staff, table, info)
    rows = rows[rows["problem"].astype(str) != NEW_JOINER].copy()
    scheme_options = ["", *SCHEME.values()]
    def _one_of(value, mapping, options):
        text = _show_choice(mapping, value)
        return text if text in options else ""

    rows["scheme"] = rows["scheme"].map(lambda value: _one_of(value, SCHEME, set(scheme_options)))
    rows["bonus_eligible"] = rows["bonus_eligible"].map(lambda value: _one_of(value, YES, {"", "是", "否"}))
    rows["allowance_section"] = rows["allowance_section"].map(lambda value: _one_of(value, SECTION, {"", "店舖", "寫字樓"}))
    numbers = {"basic_salary", "rent_amount", "water", "electricity", "rest_days_month", "transport_amount", "health_amount"}
    config = {}
    for key, label in PAY_HEADINGS.items():
        if key not in rows.columns:
            continue
        locked = readonly or key in {"employee_no", "slip_name", "problem"}
        pinned = key in {"employee_no", "slip_name"}
        help_text = _PAY_HELP.get(key)
        if key in {"scheme"}:
            config[key] = st.column_config.SelectboxColumn(
                label, options=scheme_options, disabled=locked, pinned=pinned, help=help_text,
            )
        elif key == "bonus_eligible":
            config[key] = st.column_config.SelectboxColumn(
                label, options=["", "是", "否"], disabled=locked, pinned=pinned, help=help_text,
            )
        elif key == "allowance_section":
            config[key] = st.column_config.SelectboxColumn(
                label, options=["", "店舖", "寫字樓"], disabled=locked, pinned=pinned, help=help_text,
            )
        elif key in _MONEY_COLUMNS:
            config[key] = st.column_config.NumberColumn(
                label, disabled=locked, format="accounting", pinned=pinned, help=help_text,
                min_value=0, max_value=10000000,
            )
        elif key in numbers:
            config[key] = st.column_config.NumberColumn(
                label, disabled=locked, pinned=pinned, help=help_text, min_value=0, max_value=31,
            )
        else:
            config[key] = st.column_config.TextColumn(
                label, disabled=locked, pinned=pinned, help=help_text,
                **({"width": "medium"} if pinned else {}),
            )
    st.caption("租金、水費和電費只扣內地勞工，請填實額。本地員工這三格會存成 0。交通津貼和健康津貼也填實額。")
    edited = st.data_editor(
        rows,
        column_config=config,
        column_order=[key for key in PAY_HEADINGS if key in rows.columns],
        disabled=["employee_no", "slip_name", "problem"],
        hide_index=True,
        key=f"pay-grid-{info['key']}-{book}",
    )
    if _grid_dirty(rows, edited):
        chip("未儲存", "todo")
    if readonly or not st.button("儲存薪金", type="primary", disabled=readonly):
        return
    try:
        apply_pay(edited.to_dict("records"), book=book, info=info)
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("draft", None)
    st.toast("薪金已儲存")
    st.rerun()
