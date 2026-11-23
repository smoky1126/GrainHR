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

from app.views.attendance import _days_for
from app.context import DEMO, _absence_pending, _number, _ot_pending, _patch, _pull_daka, _remember, _text
from app.views.overview import _mark

@st.dialog("全部批准")
def _confirm_approve_all(month_key, pairs, skipped):
    count = len(pairs)
    st.write(f"將批准 {count} 人。")
    if skipped:
        st.write(f"有 {skipped} 人的加班備註或缺勤未確認，會跳過。")
    if not st.button("確定批准", type="primary"):
        return
    info = parse_month(month_key)
    grouped = {}
    for book, staff_id in pairs:
        grouped.setdefault(book, []).append(staff_id)
    for book, ids in grouped.items():
        approve_all(book_info(info, book), ids)
        for staff_id in ids:
            st.session_state.pop(f"yes-{book}-{staff_id}", None)
    st.session_state.pop("approve_open", None)
    st.session_state["dirty"] = True
    st.toast(f"已批准 {count} 人")
    st.rerun()

def step_problems(info, status, draft, readonly):
    if status["problems"] == "wait":
        _mark("3. 處理問題", "wait", "請先完成上一步。")
        return draft
    people = problem_people(draft)
    if people is None or len(people) == 0:
        _mark("3. 處理問題", "done", "沒有需要處理的問題。")
        return draft
    waiting = people[~people["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"])]
    if len(waiting) == 0:
        _mark("3. 處理問題", "done", "問題已全部批准。")
    else:
        _mark("3. 處理問題", "todo", f"還有 {len(waiting)} 人未批准。")
    st.progress((len(people) - len(waiting)) / len(people), text=f"{len(people) - len(waiting)} / {len(people)} 已批准")
    pending = waiting[waiting.apply(lambda row: _ot_pending(row) or _absence_pending(row), axis=1)] if len(waiting) else waiting
    ready = waiting.drop(index=pending.index) if len(waiting) else waiting
    if len(pending):
        st.warning(f"有 {len(pending)} 人的加班備註或缺勤未確認，全部批准會跳過他們。")
    if not readonly and len(ready) and st.button("全部批准"):
        pairs = []
        from app.access import books as visible_books
        for book in visible_books():
            group = ready[ready["book"].astype(str).eq(book)] if "book" in ready.columns else ready
            pairs.extend((book, _text(value)) for value in group["staff_id"] if _text(value))
        st.session_state["approve_open"] = (info["key"], tuple(pairs), len(pending))
    opened = st.session_state.get("approve_open")
    if opened and not readonly:
        _confirm_approve_all(*opened)
    chosen = []
    from app.access import books as visible_books
    for book, label in visible_books().items():
        group = people[people["book"].astype(str).eq(book)] if "book" in people.columns else people.iloc[0:0]
        if len(group):
            chosen.append((book, label, group))
    if not chosen and "book" not in people.columns:
        chosen = [("bg", BOOKS["bg"], people)]
    if chosen:
        tabs = st.tabs([label for _book, label, _group in chosen])
        for tab, (book, _label, group) in zip(tabs, chosen):
            with tab:
                view = st.segmented_control(
                    "顯示", ["未批准", "全部", "已批准"], default="未批准", key=f"review-view-{book}",
                ) or "未批准"
                approved_mask = group["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"])
                pending_rows = group[~approved_mask]
                done_rows = group[approved_mask]
                if view in {"未批准", "全部"}:
                    for _, row in pending_rows.iterrows():
                        _problem_card(info, draft, row, book, readonly)
                if view in {"已批准", "全部"} and len(done_rows):
                    with st.expander(f"已批准（{len(done_rows)}）", expanded=view == "已批准"):
                        for _, row in done_rows.iterrows():
                            st.markdown(
                                f"<strong>{html.escape(_text(row.slip_name))}</strong> "
                                '<span class="pay-chip pay-chip-ok">已批准</span>',
                                unsafe_allow_html=True,
                            )
    return draft

def _absence_editor(booked, draft, row, book, staff_id, readonly):
    del draft
    pending = [part for part in _text(row.get("absence_pending")).split("、") if part]
    if not pending or readonly:
        return
    st.caption("更表有更但沒有打卡。請確認每一天是無薪假、病假，還是有上班但忘記打卡。")
    from payroll.pay.payroll import parse_absence_choices
    stored = parse_absence_choices(row.get("absence_choices"))
    options = ["無薪假", "病假", "有上班（忘記打卡）"]
    codes = {"無薪假": "unpaid", "病假": "sick", "有上班（忘記打卡）": "worked"}
    reverse = {value: key for key, value in codes.items()}
    picked = {}
    for label in pending:
        current = reverse.get(stored.get(label), options[0])
        picked[label] = st.radio(
            label, options, index=options.index(current) if current in options else 0,
            horizontal=True, key=f"abs-{book}-{staff_id}-{label}",
        )
    if st.button("儲存缺勤確認", key=f"abs-save-{book}-{staff_id}"):
        merged = dict(stored)
        for label, choice in picked.items():
            merged[label] = codes[choice]
        text = "、".join(f"{label}:{kind}" for label, kind in merged.items())
        save_one(booked, staff_id, {"absence_choices": text})
        st.session_state["dirty"] = True
        st.toast("已儲存缺勤")
        st.rerun()

def _problem_card(info, draft, row, book, readonly):
    staff_id = _text(row.staff_id)
    if not staff_id:
        return
    booked = book_info(info, book)
    approved_now = _text(row.approved).upper() in {"Y", "是"}
    with st.container(border=True):
        head = st.columns([4, 3])
        head[0].markdown(f"**{_text(row.slip_name)}**")
        badges = []
        if _ot_pending(row):
            badges.append(("加班未確認", "todo"))
        if _absence_pending(row):
            badges.append(("缺勤未確認", "block"))
        if approved_now:
            badges.append(("已批准", "ok"))
        if badges:
            with head[1]:
                chips(badges)
        note = html.escape(chinese_note(row.review) or "有加班，請選擇支薪或補鐘。")
        callout(note)
        saved_memo = _text(row.get("ot_text"))
        suggested = _text(row.get("ot_suggest"))
        memo = saved_memo
        if saved_memo or suggested:
            memo_key = f"otmemo-{book}-{staff_id}"
            base_key = f"otbase-{book}-{staff_id}"
            if memo_key not in st.session_state:
                st.session_state[memo_key] = suggested or saved_memo
                st.session_state[base_key] = st.session_state[memo_key]
            elif (
                suggested
                and saved_memo
                and saved_memo != suggested
                and st.session_state.get(memo_key) == saved_memo
                and not st.session_state.get(f"otkept-{book}-{staff_id}")
            ):
                st.session_state[memo_key] = suggested
                st.session_state[base_key] = suggested
                st.session_state[f"otkept-{book}-{staff_id}"] = True
            memo = st.text_area("加班備註", key=memo_key, disabled=readonly)
            if suggested and not saved_memo:
                st.caption("未確認。這是按打卡預算的時數，批准後才會印上糧單。")
            elif suggested and saved_memo != suggested:
                st.caption("這格是按打卡預算的時數。已儲存的那句不同：十月是從舊糧單抄來的。按下面的按鈕，糧單才改用這格。")
                if not readonly and st.button("採用這個加班備註", key=f"useot-{book}-{staff_id}"):
                    save_one(booked, staff_id, {"ot_text": memo})
                    _patch(draft, staff_id, book, ot_text=memo)
                    st.session_state[base_key] = memo
                    st.session_state["dirty"] = True
                    st.toast("已採用加班備註")
                    st.rerun()
        _absence_editor(booked, draft, row, book, staff_id, readonly)
        history = _text(row.get("bonus_history"))
        if history:
            st.caption(f"本季已累積：{history}。本月勤工獎 {hk(row.get('bonus'))}。")
        if "已累積，未發放" in _text(row.get("review")) and not readonly:
            choice = st.radio(
                "離職前已累積的勤工獎", ["未決定", "發放", "不發放"],
                horizontal=True, key=f"leaver-bonus-{book}-{staff_id}",
            )
            if choice != "未決定" and st.button("儲存勤工獎決定", key=f"leaver-save-{book}-{staff_id}"):
                save_one(booked, staff_id, {"bonus_leaver": "pay" if choice == "發放" else "skip"})
                st.session_state["dirty"] = True
                st.toast("已儲存")
                st.rerun()
        sick_hours = st.number_input(
            "病假時數", min_value=0.0, step=0.5, value=_number(row.get("sick_hours")),
            key=f"sick-hours-{book}-{staff_id}", disabled=readonly,
        )
        if not readonly and abs(sick_hours - _number(row.get("sick_hours"))) > 0.001:
            if st.button("儲存病假時數", key=f"sick-save-{book}-{staff_id}"):
                save_one(booked, staff_id, {"sick_hours": sick_hours})
                st.session_state["dirty"] = True
                st.toast("已儲存")
                st.rerun()
        approved = _text(row.approved).upper() in {"Y", "是"}
        detected = _number(row.ot_hours_detected)
        if detected > 0 and not readonly:
            stored = "支薪" if _text(row.ot_choice) in {"Pay", "支薪"} else "補鐘"
            choice = st.radio(
                "加班", ["補鐘", "支薪"], index=0 if stored == "補鐘" else 1,
                horizontal=True, key=f"ot-{book}-{staff_id}",
            )
            paid_hours = None
            if choice == "支薪":
                current = _number(row.ot_hours_paid) or detected
                paid_hours = st.number_input(
                    "支薪時數", min_value=0.0, step=0.5, value=float(current), key=f"hrs-{book}-{staff_id}",
                )
            changed = choice != stored
            if choice == "支薪" and paid_hours is not None and abs(paid_hours - (_number(row.ot_hours_paid) or detected)) > 0.001:
                changed = True
            if changed:
                save_one(booked, staff_id, {
                    "ot_choice": "Pay" if choice == "支薪" else "Exchange",
                    "ot_hours_paid": paid_hours if choice == "支薪" else "",
                })
                _patch(
                    draft, staff_id, book,
                    ot_choice="Pay" if choice == "支薪" else "Exchange",
                    ot_hours_paid=paid_hours if choice == "支薪" else "",
                )
                st.session_state["dirty"] = True
                _remember(info, draft)
                st.toast("已儲存加班選擇")
                st.rerun()
        st.divider()
        foot = st.columns([3, 1])
        if readonly:
            foot[1].write("已批准" if approved else "未批准")
        else:
            if _absence_pending(row):
                foot[0].caption("缺勤未確認，暫時不能批准。")
            toggled = foot[1].toggle(
                "批准", value=approved, key=f"yes-{book}-{staff_id}",
                disabled=_absence_pending(row),
            )
            edited = memo != st.session_state.get(f"otbase-{book}-{staff_id}", memo)
            if toggled != approved or (toggled and edited):
                changes = {}
                if toggled != approved:
                    changes["approved"] = "Y" if toggled else ""
                if toggled:
                    changes["ot_text"] = memo
                save_one(booked, staff_id, changes)
                _patch(draft, staff_id, book, **changes)
                st.session_state[f"otbase-{book}-{staff_id}"] = memo
                st.session_state["dirty"] = True
                st.toast("已批准" if toggled else "已取消批准")
                st.rerun()
        with st.expander("進階"):
            _advanced(booked, draft, row, staff_id, readonly, book)

def _advanced(info, draft, row, staff_id, readonly, book="bg"):
    if st.button("立即同步 DAKA", key=f"daka-sync-{book}-{staff_id}", disabled=readonly or DEMO):
        _pull_daka(force=True)
        st.rerun()
    fields = [
        ("unpaid_days", "無薪假"),
        ("sick_days", "病假"),
        ("annual_taken", "年假"),
        ("birthday_days", "生日假"),
        ("taken_rest", "已休假"),
        ("statutory_days", "法定假日"),
        ("bonus_override", "獎金調整"),
        ("manual_delta", "其他調整"),
    ]
    values = {}
    for key, label in fields:
        help_text = None
        if key == "statutory_days":
            count = holiday_count(info, book)
            if book == "admin":
                label = "公眾假期"
                help_text = f"政府公布的公眾假期，本月 {count} 日，不包括星期日。"
            else:
                help_text = f"勞工處法定假日，本月 {count} 日。{BOOKS['bg']}和 {BOOKS['md']} 會加進未用休假。"
            if not holiday_known(info["year"]):
                help_text = "這一年的假期表還沒有收錄，請在這格填上。"
            else:
                help_text += "這格留空就用這個數；改了就以你填的為準。"
        values[key] = st.number_input(
            label, value=_number(row.get(key)), key=f"{key}-{book}-{staff_id}",
            disabled=readonly, help=help_text,
        )
    note = st.text_input("備註", value=_text(row.note), key=f"note-{book}-{staff_id}", disabled=readonly)
    ref_key = f"ownref-{book}-{staff_id}"
    if ref_key not in st.session_state:
        st.session_state[ref_key] = _text(row.get("salary_reference"))
    own_ref = st.text_input("交易編號（只限此人）", key=ref_key, disabled=readonly)
    st.caption(f"{bonus_rule_text()} 這個人本月是 {hk(row.get('bonus'))}。")
    days = _days_for(info, _text(row.roster_name))
    if days is not None and len(days):
        st.caption("紅色的下班時間是加班或早退。加班備註的時數是從這些日子算出來的。")
        st.dataframe(_day_style(days), hide_index=True, width="stretch")
    if readonly or not st.button("儲存這項修改", key=f"more-{book}-{staff_id}"):
        return
    changes = dict(values)
    changes["note"] = note
    changes["salary_reference"] = own_ref
    save_one(info, staff_id, changes)
    _patch(draft, staff_id, book, **changes)
    st.session_state["dirty"] = True
    _remember(info, draft)
    st.toast("已儲存")
    st.rerun()
