"""The first screen: one day, one card per shop."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.components.cards import kpi
from app.components.tables import style_days
from app.components.theme import inject, show_logo
from payroll.core.config import ROSTER_SOURCES
from payroll.daka.daka_inbox import read_status
from payroll.attendance.today import LOCATIONS, expected, for_board, google_sheets_present, load_day, location_for, missed, place_names

_WEEK = "一二三四五六日"


def _label(day):
    return f"{day.year}年{day.month}月{day.day}日"


def _weekday(day):
    return f"星期{_WEEK[day.weekday()]}"


def _banner():
    import os
    if os.environ.get("PAYROLL_DEMO") == "1":
        st.markdown(
            '<div class="payroll-banner">示範模式：資料是十月副本，改動不影響真實資料</div>',
            unsafe_allow_html=True,
        )


def _export_time(status):
    server = status.get("server") or {}
    return server.get("time") or ""


def _notice():
    from app.context import _pull_daka
    forced = st.session_state.pop("today-force", False)
    if forced:
        st.session_state["daka_notice"] = _pull_daka(force=True)
    else:
        quiet = _pull_daka()
        if quiet:
            st.session_state["daka_notice"] = quiet
    status = read_status()
    notice = st.session_state.get("daka_notice") or ""
    if forced and not notice:
        exported = _export_time(status)
        if exported:
            notice = f"已是最新。這份匯出是 {exported}，在這之後的打卡還未包括。"
            st.session_state["daka_notice"] = notice
    if not notice and status and status.get("ok") is False:
        notice = status.get("message") or ""
    return status.get("pulled_at") or "未同步", _export_time(status), notice


def _rows(frame, place):
    if not len(frame):
        return frame
    keep = frame["Chosen shop"].map(lambda shop: place in location_for(shop))
    shown = frame.loc[keep].copy()
    if not len(shown):
        return shown
    shown["_miss"] = shown["Status"].astype(str).str.contains("缺卡")
    shown["_in"] = shown["DAKA in"].astype(str)
    shown = shown.sort_values(["_miss", "_in"], ascending=[False, True])
    return shown.drop(columns=["_miss", "_in"])


def _counts(frame, day):
    if not len(frame):
        return 0, 0, 0, 0
    due = int(frame.apply(expected, axis=1).sum())
    late = int((pd.to_numeric(frame["Late"], errors="coerce").fillna(0) > 0).sum())
    overtime = int((pd.to_numeric(frame["OT"], errors="coerce").fillna(0) > 0).sum())
    absent = int(frame.apply(lambda row: missed(row, day), axis=1).sum())
    return due, late, overtime, absent


def _greeting():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.lock import _user
    from payroll.core.settings import display_name

    hour = datetime.now(ZoneInfo("Asia/Hong_Kong")).hour
    hello = "早晨" if hour < 12 else "午安" if hour < 18 else "晚安"
    return f"{hello}，{display_name(_user())}"


def _relative(when):
    from datetime import datetime
    if when is None:
        return "未同步", "muted", ""
    delta = datetime.now() - when
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        text = "剛剛"
    elif minutes < 60:
        text = f"{minutes} 分鐘前"
    else:
        text = f"{minutes // 60} 小時前"
    if delta > timedelta(hours=24):
        tone = "bad"
    elif delta > timedelta(hours=2):
        tone = "warn"
    else:
        tone = "ok"
    exact = when.strftime("%Y-%m-%d %H:%M")
    return text, tone, exact


def _freshness(updated, exported):
    from datetime import datetime
    from pathlib import Path

    from app.components.status import freshness
    from payroll.core.config import ROSTER_COPY_DIR, STAFF_RECORD_DIR

    def _parsed(text):
        text = str(text or "").strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    items = [("DAKA", _parsed(updated))]
    newest = None
    folder = ROSTER_COPY_DIR
    if folder and Path(folder).exists():
        files = [path for path in Path(folder).rglob("*") if path.is_file() and not path.name.startswith("~$")]
        if files:
            newest = datetime.fromtimestamp(max(path.stat().st_mtime for path in files))
    items.append(("更表", newest))
    staff_time = None
    record = STAFF_RECORD_DIR
    if record and Path(record).exists():
        books = [path for path in Path(record).glob("Staff_info_*.xlsx") if not path.name.startswith("~$")]
        if books:
            staff_time = datetime.fromtimestamp(max(path.stat().st_mtime for path in books))
    items.append(("員工檔", staff_time))
    st.markdown('<div class="gh-strip">', unsafe_allow_html=True)
    for label, when in items:
        text, tone, exact = _relative(when)
        freshness(label, text, exact, tone)
    if exported:
        freshness("匯出", str(exported), str(exported), "muted")
    st.markdown("</div>", unsafe_allow_html=True)


def render():
    from app.components.clock import live_clock

    inject()
    show_logo()
    _banner()
    today = date.today()
    if "board-date" not in st.session_state:
        st.session_state["board-date"] = today
    updated, exported, notice = _notice()
    head = st.columns([3, 1.4])
    with head[0]:
        st.markdown(f'<h1 class="gh-greet">{_greeting()}</h1><p class="gh-date">今日出勤</p>', unsafe_allow_html=True)
    with head[1]:
        live_clock()
    _freshness(updated, exported)
    bar = st.columns([1.2, 1.2, 2.4, 1.2])
    with bar[0]:
        if st.button("今天", key="today-now"):
            st.session_state["board-date"] = today
            st.rerun()
    with bar[1]:
        if st.button("昨天", key="today-yesterday"):
            st.session_state["board-date"] = today - timedelta(days=1)
            st.rerun()
    with bar[2]:
        picked = st.date_input("日期", key="board-date")
    with bar[3]:
        if st.button("立即更新", key="today-refresh"):
            st.session_state["today-force"] = True
            st.rerun()
    st.markdown(
        f'<div class="pay-head"><h1>今日出勤</h1>'
        f'<span class="pay-pill">{_label(picked)} {_weekday(picked)}</span></div>',
        unsafe_allow_html=True,
    )
    if notice:
        st.warning(notice)
    query = st.text_input("搜尋姓名", key="today-query").strip()
    frame, missing = load_day(picked)
    frame = for_board(frame, picked)
    if query and len(frame):
        frame = frame[frame["Name"].astype(str).str.contains(query, regex=False)]
    due, late, overtime, absent = _counts(frame, picked)
    arrived = max(due - absent, 0)
    cards = st.columns(4)
    figures = (
        ("應出勤", due, "info" if due else "muted"),
        ("已到", arrived, "ok" if arrived else "muted"),
        ("遲到", late, "block" if late else "muted"),
        ("缺勤", absent, "block" if absent else "muted"),
    )
    for column, (label, value, tone) in zip(cards, figures):
        with column:
            kpi(label, value, tone=tone)
    st.caption(f"加班 {overtime} 人。本頁準時 {max(arrived - late, 0)} 人，遲到 {late} 人，缺勤 {absent} 人。")
    if due:
        import pandas as pd
        from app.components.charts import doughnut
        mix = pd.DataFrame({
            "情況": ["準時", "遲到", "缺勤"],
            "人數": [max(arrived - late, 0), late, absent],
        })
        st.altair_chart(doughnut(mix, "情況", "人數", "今日出勤"), use_container_width=True)
    missed_rows = frame[frame.apply(lambda row: missed(row, picked), axis=1)] if len(frame) else frame
    if len(missed_rows):
        with st.container(border=True):
            st.markdown("**缺勤**")
            for _, row in missed_rows.iterrows():
                places = "、".join(place_names(row.get("Chosen shop"))) or "未分店"
                shift = str(row.get("Roster cell") or "").strip()
                st.markdown(f"{places} · {row['Name']} · {shift} · 缺勤")
    none_found = len(missing) == len(ROSTER_SOURCES)
    if none_found and google_sheets_present(picked):
        st.info(
            f"{picked.month}月的更表在 Google 試算表裡。程式只能讀 Excel 副本，所以還不能判斷誰缺勤。"
            "請到 script.google.com 執行一次 copyRosters，等 Drive 同步後再打開這一頁。"
        )
    elif none_found:
        st.info("更表副本還沒有，不能判斷誰缺勤。")
    shown = []
    for label, _codes in LOCATIONS:
        people = _rows(frame, label)
        absent_files = [] if none_found else [name for name in missing if _file_place(name) == label]
        if not len(people) and not absent_files:
            continue
        if query and not len(people):
            continue
        shown.append((label, people, absent_files))
    for index in range(0, len(shown), 2):
        pair = shown[index:index + 2]
        columns = st.columns(2)
        for column, (label, people, absent_files) in zip(columns, pair):
            with column:
                with st.container(border=True):
                    count = len(people)
                    st.markdown(f'<div class="pay-section"><h3>{label}</h3></div>', unsafe_allow_html=True)
                    st.caption(f"{count} 人" if count else "沒有人")
                    for name in absent_files:
                        st.caption(f"找不到更表 {name}")
                    if count:
                        st.dataframe(style_days(people), hide_index=True, width="stretch")


def _file_place(file_name):
    from payroll.core.settings import file_places
    rules = file_places()
    for token, label in rules:
        if token in file_name:
            return label
    return ""
