import html
import os

import pandas as pd
import streamlit as st

from app.components.cards import callout, kpi, page_header, section
from app.components.chips import chip, chips, legend, stepper
from app.components.format import hk
from app.components.tables import style_days as _day_style
from app.components.theme import inject, show_logo
from app.lock import claim
from app.state import (
    default_scheme, format_pay_date, new_joiners, parse_pay_date, problem_people,
    roster_report, step_status, unlinked_roster_names,
)
from payroll.core.config import book_info, parse_month
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
    from payroll.core.history import is_issued
    state = "已出糧" if is_issued(key) else "進行中"
    return f"{year}年{int(month)}月 · {state}"

def _choose_month():
    if DEMO:
        st.sidebar.caption("示範月份：2026年10月")
        return "2026-10"
    from app.state import month_choices
    options, current = month_choices()
    return st.sidebar.selectbox(
        "月份", options, index=options.index(current), format_func=_month_label, key="payroll-month",
    )

def _month_key(show):
    if DEMO:
        if show:
            st.sidebar.caption("示範月份：2026年10月")
        return "2026-10"
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

def refresh_rosters(info):
    """Copy the latest roster files and check attendance again."""
    from payroll.attendance.rosters import RosterProblem, copy_rosters
    from payroll.core.history import is_issued

    if is_issued(info["key"]):
        st.info("這個月已經出糧，不會改更表。")
        return False

    try:
        with st.spinner("正在更新更表"):
            copy_rosters(info)
            if info["daka"].exists() and not DEMO:
                from payroll.pay.run import run_check
                run_check(info, open_workbook=False, fetch=False)
    except PermissionError:
        st.error("請先關閉 Excel 中的考勤核對表，然後再試。")
        return False
    except (SystemExit, RosterProblem) as error:
        st.error(str(error))
        return False
    st.session_state.pop("days_frame", None)
    st.session_state.pop("day_join", None)
    st.session_state.pop("draft", None)
    stamp = info["daka"].stat().st_mtime if info["daka"].exists() else None
    st.session_state["auto_checked"] = stamp
    st.toast("更表已更新")
    return True


def _pull_daka(force=False):
    """File the exports the DAKA server uploaded, at most every 2 minutes. The demo never connects.

    A forced pull asks the server for a fresh export. A PC on Tailscale asks directly
    and waits about a minute. Other PCs leave a request on the shared drive, and the
    home page checks for the answer.
    """
    if DEMO:
        return "示範模式不會連線" if force else ""
    import time
    last = st.session_state.get("daka_pull_at")
    if not force and last is not None and time.time() - last < 2 * 60:
        return ""
    st.session_state["daka_pull_at"] = time.time()
    from payroll.daka.daka_inbox import OFFLINE, export_now, file_inbox, request_export
    try:
        if force:
            with st.spinner("正在向 DAKA 伺服器取最新打卡，大約一分鐘"):
                message = export_now()
            if message == OFFLINE or (message and "已請" in str(message)):
                st.session_state["daka_requested"] = request_export()
                return "已請 DAKA 伺服器匯出最新打卡，大約兩至三分鐘。今日出勤頁會自動更新。"
            st.session_state.pop("daka_requested", None)
            return message
        file_inbox()
        return ""
    except OSError:
        return "有一份 DAKA 檔案暫時讀不到，其他資料照常顯示。"

@st.fragment(run_every="2m")
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
    from app.lock import _user
    from payroll.core.history import is_issued
    from payroll.core.settings import role_for
    who = _user()
    role = role_for(who)
    issued = is_issued(info["key"])
    if issued:
        can_edit, owner = False, ""
    else:
        can_edit, owner = claim(info)
    readonly = issued or not can_edit
    if issued:
        st.markdown(
            '<div class="payroll-banner">這個月已經出糧，糧單、更表和出勤只供查看，不會再計算。</div>',
            unsafe_allow_html=True,
        )
    staff = load_staff()
    table = ensure_pay_table()
    draft = _drafts(info)
    slips_ready = bool(st.session_state.get("slips_ready"))
    if steps:
        stepper(step_status(info, draft, staff, table, slips_ready=slips_ready))
    from html import escape
    if can_edit:
        st.sidebar.markdown(
            f'<span class="pay-chip pay-chip-ok">你正在處理 {escape(_month_label(info["key"]))}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            f'<span class="pay-chip pay-chip-block">{escape(str(owner or ""))} 正在使用</span>',
            unsafe_allow_html=True,
        )
        if st.sidebar.button("接手", help="另一位同事正在處理這個月時，才需要接手。"):
            claim(info, take_over=True)
            st.rerun()
    from payroll.core.settings import app_version, display_name
    roles = {"admin": "管理員", "hr": "HR 同事"}
    st.sidebar.markdown(
        f'<div class="gh-footer">GrainHR v{escape(str(app_version()))}<br>'
        f'{escape(str(display_name(who)))} · {escape(roles.get(role, "HR 同事"))}</div>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("進階"):
        if st.button("立即同步 DAKA", disabled=readonly or DEMO, help="向打卡伺服器要最新的打卡，大約一分鐘。"):
            _pull_daka(force=True)
            st.rerun()
        if st.button("重新檢查", disabled=readonly, help="用現有打卡和更表再核對一次出勤。"):
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
