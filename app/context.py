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


DEMO = os.environ.get("PAYROLL_DEMO") == "1"

def _text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text

def _number(value):
    text = _text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0

def _month_label(key):
    year, month = key.split("-")
    return f"{year}年{int(month)}月"

def _choose_month():
    if DEMO:
        st.sidebar.caption("示範月份：2026年10月")
        return "2026-10"
    folder = home() / "months"
    options = []
    if folder.exists():
        options = sorted(
            path.name.replace("_", "-")
            for path in folder.iterdir()
            if path.is_dir() and len(path.name) == 7 and path.name[4] == "_"
        )
    current = last_month()
    if current not in options:
        options.append(current)
    options = sorted(set(options))
    return st.sidebar.selectbox(
        "月份", options, index=options.index(current), format_func=_month_label, key="payroll-month",
    )

def _month_key(show):
    if DEMO:
        if show:
            st.sidebar.caption("示範月份：2026年10月")
        return "2026-10"
    if not show:
        return st.session_state.get("payroll-month", last_month())
    return _choose_month()

def _remember(info, draft):
    book = info.get("book", "bg")
    stamp = info["adjustments"].stat().st_mtime if info["adjustments"].exists() else 0
    st.session_state.setdefault("drafts", {})
    st.session_state["drafts"][book] = draft
    st.session_state.setdefault("draft_stamps", {})
    st.session_state["draft_stamps"][book] = (info["key"], stamp)

def _draft(info):
    facts = info["system"] / "daily_facts.xlsx"
    if not facts.exists():
        return None
    book = info.get("book", "bg")
    stamp = info["adjustments"].stat().st_mtime if info["adjustments"].exists() else 0
    stamps = st.session_state.get("draft_stamps", {})
    if stamps.get(book) == (info["key"], stamp) and book in st.session_state.get("drafts", {}):
        return st.session_state["drafts"][book]
    draft = _draft_from_facts(info)
    if draft is not None:
        _remember(info, draft)
    return draft

def _drafts(info):
    frames = []
    for book in BOOKS:
        if not pay_table_path(book).exists():
            continue
        one = _draft(book_info(info, book))
        if one is None:
            continue
        one = one.copy()
        one["book"] = book
        frames.append(one)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)

def _patch(draft, staff_id, book="bg", **changes):
    mask = draft["staff_id"].astype(str) == str(staff_id)
    if "book" in draft.columns:
        mask = mask & draft["book"].astype(str).eq(book)
    for key, value in changes.items():
        draft.loc[mask, key] = value
    return draft

def _save_upload(info, upload, refresh_payroll=True):
    info["folder"].mkdir(parents=True, exist_ok=True)
    info["system"].mkdir(parents=True, exist_ok=True)
    info["daka"].write_bytes(upload.getvalue())
    if refresh_payroll:
        st.session_state["auto_checked"] = None
        st.session_state.pop("draft", None)

def _pull_daka(force=False):
    """Pull the morning export at most every 30 minutes. The demo never connects.

    A forced pull skips the quiet period. The return value is empty when the
    pull worked, and the reason when it did not.
    """
    if DEMO:
        return "示範模式不會連線" if force else ""
    import time
    last = st.session_state.get("daka_pull_at")
    if not force and last is not None and time.time() - last < 30 * 60:
        return ""
    st.session_state["daka_pull_at"] = time.time()
    from payroll.daka.daka_inbox import pull_from_server
    return pull_from_server() or ""

def _daka_chip():
    from payroll.daka.daka_inbox import read_status
    status = read_status()
    when = status.get("pulled_at") or "未同步"
    ok = status.get("ok", True) if status else True
    chip(f"DAKA 自動更新：{when}", "done" if ok and status else "muted" if not status else "todo")
    if status and not ok and status.get("message"):
        st.warning(status["message"])

def _show_choice(mapping, value):
    text = _text(value)
    if mapping is YES and text in {"1", "1.0"}:
        return "是"
    if mapping is YES and text in {"0", "0.0"}:
        return "否"
    return show(mapping, text)

def _ot_pending(row):
    return bool(_text(row.get("ot_suggest"))) and not _text(row.get("ot_text"))


def _absence_pending(row):
    return bool(_text(row.get("absence_pending")))


def _blocked(draft, book):
    if draft is None or "book" not in getattr(draft, "columns", []):
        return draft.iloc[0:0] if draft is not None else draft
    group = draft[draft["book"].astype(str).eq(book)]
    if group.empty or "pay_this" not in group.columns:
        return group.iloc[0:0]
    review = group["review"].astype(str).str.strip()
    needs = review.ne("") & review.str.lower().ne("nan")
    if "ot_suggest" in group.columns:
        needs = needs | group.apply(_ot_pending, axis=1)
    approved = group["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"])
    return group[group["pay_this"].astype(bool) & needs & ~approved]

def _context(steps=False):
    inject()
    show_logo()
    if DEMO:
        st.markdown(
            '<div class="payroll-banner">示範模式：資料是十月副本，改動不影響真實資料</div>',
            unsafe_allow_html=True,
        )
    info = parse_month(_month_key(steps))
    can_edit, owner = claim(info)
    readonly = not can_edit
    staff = load_staff()
    table = ensure_pay_table()
    draft = _drafts(info)
    slips_ready = bool(st.session_state.get("slips_ready"))
    if steps:
        stepper(step_status(info, draft, staff, table, slips_ready=slips_ready))
    if can_edit:
        st.sidebar.markdown(
            f'<span class="pay-chip pay-chip-ok">你正在處理 {_month_label(info["key"])}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            f'<span class="pay-chip pay-chip-block">{owner} 正在使用</span>',
            unsafe_allow_html=True,
        )
        if st.sidebar.button("接手"):
            claim(info, take_over=True)
            st.rerun()
    from app.lock import _user
    from payroll.core.settings import display_name, role_for
    who = _user()
    roles = {"admin": "HR 管理員", "hr": "HR 同事", "viewer": "店長"}
    st.sidebar.markdown(
        f'<div class="gh-footer">GrainHR v1.0.0<br>{display_name(who)} · {roles.get(role_for(who), "HR 同事")}</div>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("進階"):
        if st.button("立即同步 DAKA", disabled=readonly or DEMO):
            _pull_daka(force=True)
            st.rerun()
        if st.button("重新檢查", disabled=readonly):
            try:
                run_check(info, open_workbook=False, fetch=not DEMO)
            except PermissionError:
                st.error("請先關閉 Excel 中的考勤核對表，然後再按重新檢查。")
            except SystemExit as error:
                st.error(str(error))
            else:
                st.session_state.pop("draft", None)
                st.session_state["dirty"] = True
                st.rerun()
        if DEMO and st.button("重設示範"):
            from payroll.setup.demo import build_demo
            try:
                build_demo(force=True)
            except OSError as error:
                st.error(f"未能重設：{error}")
            else:
                st.session_state.clear()
                st.rerun()
    return info, readonly, draft, staff, table
