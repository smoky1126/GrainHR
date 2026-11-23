"""The first screen: one day, one card per shop."""

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.components.tables import style_days
from app.components.theme import inject, show_logo
from payroll.core.config import ROSTER_SOURCES
from payroll.daka.daka_inbox import read_status
from payroll.attendance.today import (
    expected, for_board, google_sheets_present, load_day, location_for, missed, roster_files,
)
from payroll.core.settings import locations as location_rows

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
        _pull_daka()
    status = read_status()
    notice = st.session_state.get("daka_notice") or ""
    if forced and not notice and not st.session_state.get("daka_requested"):
        exported = _export_time(status)
        if exported:
            notice = f"已是最新。這份匯出是 {exported}，在這之後的打卡還未包括。"
            st.session_state["daka_notice"] = notice
    if not notice and status and status.get("ok") is False:
        notice = status.get("message") or ""
    return status.get("pulled_at") or "未同步", _export_time(status), notice


@st.fragment(run_every=15)
def _wait_for_export():
    """Watch for the export a shared-drive request asked for, then reload the page."""
    from payroll.daka.daka_inbox import file_inbox

    asked = st.session_state.get("daka_requested")
    if not asked:
        return
    exported = _export_time(read_status())
    if exported and exported >= asked:
        file_inbox()
        st.session_state.pop("daka_requested", None)
        st.session_state["daka_notice"] = f"已更新。這份匯出是 {exported}。"
        st.rerun(scope="app")


@st.fragment(run_every=60)
def _watch_daka():
    """Reload when any PC's refresh or the hourly run brings a newer export."""
    from payroll.daka.daka_inbox import file_inbox

    exported = _export_time(read_status())
    if exported and exported > (st.session_state.get("daka_shown") or ""):
        file_inbox()
        st.session_state["daka_shown"] = exported
        st.rerun(scope="app")


def _board_stamp(day):
    """Cheap fingerprint of the roster copies and the DAKA file. Excel is not opened."""
    info, found, missing = roster_files(day)
    marks = []
    daka = info["daka"]
    if daka.exists():
        marks.append(daka.stat().st_mtime_ns)
    for _shop, path, _sheet in found:
        try:
            marks.append(path.stat().st_mtime_ns)
        except OSError:
            marks.append(0)
    return (day.isoformat(), tuple(missing), tuple(marks))


def _load_board(day):
    """Read the day's roster and punches once, then reuse them until a file changes."""
    stamp = _board_stamp(day)
    cached = st.session_state.get("today-cache")
    if cached and cached[0] == stamp:
        evidence, missing = cached[1], cached[2]
    else:
        evidence, missing = load_day(day)
        st.session_state["today-cache"] = (stamp, evidence, missing)
    return for_board(evidence, day), missing


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


def _minutes(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return 0 if pd.isna(number) else number


def _counts(frame, day):
    if not len(frame):
        return 0, 0, 0, 0
    due = int(frame.apply(expected, axis=1).sum())
    late = int((pd.to_numeric(frame["Late"], errors="coerce").fillna(0) > 0).sum())
    overtime = int((pd.to_numeric(frame["OT"], errors="coerce").fillna(0) > 0).sum())
    absent = int(frame.apply(lambda row: missed(row, day), axis=1).sum())
    return due, late, overtime, absent


def _match(frame, test):
    if frame is None or not len(frame):
        return frame
    return frame[frame.apply(test, axis=1)]


def _buckets(frame, day):
    """The four cards. Each one opens the names, roster facts, and punch evidence."""
    due = _match(frame, expected)
    absent = _match(frame, lambda row: missed(row, day))
    arrived = _match(frame, lambda row: expected(row) and not missed(row, day))
    late = _match(frame, lambda row: _minutes(row.get("Late")) > 0)
    return (
        ("due", "應出勤", due, "info"),
        ("here", "已到", arrived, "ok"),
        ("late", "遲到", late, "block"),
        ("miss", "缺勤", absent, "block"),
    )


def _fact(row):
    from payroll.core.settings import shop_label
    shop = shop_label(row.get("Chosen shop"))
    roster = str(row.get("Roster cell") or "").strip()
    listed = str(row.get("Rosters") or "").strip()
    fact = " · ".join(part for part in (shop, roster) if part and part.lower() != "nan")
    if listed and listed.lower() != "nan" and listed not in fact:
        fact = f"{fact}（{listed}）" if fact else listed
    return fact or "—"


def _evidence(row):
    parts = []
    clock_in = str(row.get("DAKA in") or "").strip()
    clock_out = str(row.get("DAKA out") or "").strip()
    in_place = str(row.get("DAKA in place") or "").strip()
    out_place = str(row.get("DAKA out place") or "").strip()
    if clock_in and clock_in.lower() != "nan":
        parts.append(f"上班 {clock_in}" + (f" {in_place}" if in_place and in_place.lower() != "nan" else ""))
    if clock_out and clock_out.lower() != "nan":
        parts.append(f"下班 {clock_out}" + (f" {out_place}" if out_place and out_place.lower() != "nan" else ""))
    late = _minutes(row.get("Late"))
    if late:
        parts.append(f"遲到 {int(late)} 分鐘")
    early = _minutes(row.get("Early"))
    if early:
        parts.append(f"早退 {int(early)} 分鐘")
    overtime = _minutes(row.get("OT"))
    if overtime:
        parts.append(f"加班 {overtime:g} 小時")
    status = str(row.get("Status") or "").strip()
    if status and status.lower() != "nan" and status not in " ".join(parts):
        parts.append(status)
    return "；".join(parts) or "沒有打卡"


def _evidence_table(people):
    rows = [
        {"姓名": row.get("Name") or "—", "更表": _fact(row), "打卡紀錄": _evidence(row)}
        for _, row in people.iterrows()
    ]
    return pd.DataFrame(rows)


def _show_bucket(people):
    if people is None or not len(people):
        st.info("這個分類沒有人。")
        return
    st.dataframe(
        _evidence_table(people),
        hide_index=True,
        width="stretch",
        column_config={
            "姓名": st.column_config.TextColumn("姓名", width="medium", pinned=True),
            "更表": st.column_config.TextColumn("更表", width="large"),
            "打卡紀錄": st.column_config.TextColumn("打卡紀錄", width="large"),
        },
    )


def _kpi_tabs(frame, day):
    buckets = _buckets(frame, day)
    known = {code for code, _label, _people, _tone in buckets}
    choice = st.session_state.get("today-bucket", "due")
    if choice not in known:
        choice = "due"
    columns = st.columns(4)
    for column, (code, label, people, tone) in zip(columns, buckets):
        with column:
            count = 0 if people is None else len(people)
            kind = tone if count else "muted"
            marked = " gh-kpi-on" if choice == code else ""
            st.markdown(
                f'<div class="pay-kpi pay-kpi-{kind} gh-kpi-face{marked}">'
                f'<span class="pay-kpi-label">{label}</span>'
                f'<span class="pay-kpi-value">{count}</span></div>',
                unsafe_allow_html=True,
            )
            if st.button(label, key=f"today-kpi-{code}", width="stretch") and choice != code:
                st.session_state["today-bucket"] = code
                st.rerun()
    return next(people for code, _label, people, _tone in buckets if code == choice)


def _greeting():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.lock import _user
    from payroll.core.settings import display_name, timezone_name

    try:
        hour = datetime.now(ZoneInfo(timezone_name())).hour
    except Exception:
        hour = datetime.now().hour
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


_ROSTER_SCAN = {"folder": "", "at": 0.0, "when": None}


def _newest_roster(folder):
    """The newest roster file. The folder walk is reused for a minute."""
    import time
    now = time.time()
    key = str(folder)
    if _ROSTER_SCAN["folder"] == key and now - _ROSTER_SCAN["at"] < 60:
        return _ROSTER_SCAN["when"]
    newest = None
    files = [path for path in folder.rglob("*") if path.is_file() and not path.name.startswith("~$")]
    if files:
        newest = datetime.fromtimestamp(max(path.stat().st_mtime for path in files))
    _ROSTER_SCAN.update(folder=key, at=now, when=newest)
    return newest


def _freshness(updated, exported):
    from datetime import datetime
    from pathlib import Path

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
        newest = _newest_roster(Path(folder))
    items.append(("更表", newest))
    staff_time = None
    record = STAFF_RECORD_DIR
    if record and Path(record).exists():
        books = [path for path in Path(record).glob("Staff_info_*.xlsx") if not path.name.startswith("~$")]
        if books:
            staff_time = datetime.fromtimestamp(max(path.stat().st_mtime for path in books))
    items.append(("員工檔", staff_time))
    chips = []
    for label, when in items:
        text, tone, exact = _relative(when)
        kind = tone if tone in {"ok", "warn", "bad", "muted"} else "muted"
        chips.append(
            f'<span class="gh-badge gh-badge-{kind}" title="{html.escape(str(exact or ""), quote=True)}">'
            f'{html.escape(str(label))} · {html.escape(str(text))}</span>'
        )
    if exported:
        chips.append(f'<span class="gh-badge gh-badge-muted">匯出 · {html.escape(str(exported))}</span>')
    st.markdown(f'<div class="gh-strip">{"".join(chips)}</div>', unsafe_allow_html=True)


def _month_progress():
    from app.state import month_choices, month_progress
    from payroll.core.config import parse_month
    import os

    if os.environ.get("PAYROLL_DEMO") == "1":
        key = "2026-10"
    else:
        _options, key = month_choices()
    try:
        info = parse_month(key)
        rows = month_progress(info)
    except (OSError, SystemExit):
        return
    year, month = key.split("-")
    with st.container(border=True):
        st.markdown(f"**本月出糧進度** · {year}年{int(month)}月")
        st.dataframe(
            pd.DataFrame([{"項目": label, "狀態": "完成" if done else "未做"} for label, done in rows]),
            hide_index=True,
            width="stretch",
            alt="本月出糧進度",
        )


@st.fragment
def render():
    from app.components.clock import live_clock

    from app.components.cards import first_tip
    inject()
    show_logo()
    first_tip("today", "這裡看今天誰應出勤、誰已打卡。換月份請用左邊的「月份」。")
    _banner()
    today = date.today()
    if "board-date" not in st.session_state:
        st.session_state["board-date"] = today
    updated, exported, notice = _notice()
    st.session_state["daka_shown"] = exported
    if st.session_state.get("daka_requested"):
        _wait_for_export()
    else:
        _watch_daka()
    head = st.columns([1.6, 1.2], vertical_alignment="center")
    with head[0]:
        st.markdown(f'<h1 class="gh-greet">{_greeting()}</h1><p class="gh-date">今日出勤</p>', unsafe_allow_html=True)
    with head[1]:
        live_clock()
    _freshness(updated, exported)
    _month_progress()
    with st.container(horizontal=True, vertical_alignment="bottom"):
        if st.button("今天", key="today-now"):
            st.session_state["board-date"] = today
            st.rerun()
        if st.button("昨天", key="today-yesterday"):
            st.session_state["board-date"] = today - timedelta(days=1)
            st.rerun()
        picked = st.date_input("日期", key="board-date", format="YYYY-MM-DD")
        if st.button("立即更新", key="today-refresh"):
            st.session_state["today-force"] = True
            st.rerun()
        if st.button("更新更表", key="today-roster"):
            from app.context import refresh_rosters
            from payroll.core.config import parse_month
            month = parse_month(f"{picked.year}-{picked.month:02d}")
            if refresh_rosters(month):
                st.rerun()
    if notice:
        st.warning(notice)
    query = st.text_input("搜尋姓名", key="today-query").strip()
    frame, missing = _load_board(picked)
    if query and len(frame):
        frame = frame[frame["Name"].astype(str).str.contains(query, regex=False)]
    _due, late, overtime, absent = _counts(frame, picked)
    arrived = max(_due - absent, 0)
    on_time = max(arrived - late, 0)
    overview = st.columns([1.55, 0.85], vertical_alignment="center")
    with overview[0]:
        selected = _kpi_tabs(frame, picked)
    with overview[1]:
        if _due:
            from app.components.charts import doughnut
            mix = pd.DataFrame({
                "情況": ["準時", "遲到", "缺勤"],
                "人數": [on_time, late, absent],
            })
            st.altair_chart(
                doughnut(mix, "情況", "人數", "今日出勤", colors=["#2E7D5B", "#D98E04", "#C0392B"]),
                width="stretch",
            )
        st.caption(f"加班 {overtime} 人。準時 {on_time} 人，遲到 {late} 人，缺勤 {absent} 人。")
    _show_bucket(selected)
    none_found = len(missing) == len(ROSTER_SOURCES)
    if none_found and google_sheets_present(picked):
        st.info(
            f"{picked.month}月的更表在 Google 試算表裡。程式只能讀 Excel 副本，所以還不能判斷誰缺勤。"
            "請到 script.google.com 執行一次 copyRosters，等 Drive 同步後再打開這一頁。"
        )
    elif none_found:
        st.info("更表副本還沒有，不能判斷誰缺勤。")
    places = []
    for label, _codes in location_rows():
        people = _rows(frame, label)
        absent_files = [] if none_found else [name for name in missing if _file_place(name) == label]
        if not len(people) and not absent_files:
            continue
        if query and not len(people):
            continue
        places.append((label, people, absent_files))
    if places:
        options = [f"{label} {len(people)}" for label, people, _files in places]
        choice = st.segmented_control("地點", options, default=options[0], key="today-place") or options[0]
        label, people, absent_files = places[options.index(choice)] if choice in options else places[0]
        for name in absent_files:
            st.caption(f"找不到更表 {name}")
        if len(people):
            st.dataframe(style_days(people), hide_index=True, width="stretch")
        else:
            st.info(f"{label} 沒有人。")


def _file_place(file_name):
    from payroll.core.settings import file_places
    rules = file_places()
    for token, label in rules:
        if token in file_name:
            return label
    return ""
