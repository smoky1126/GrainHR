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

from app.context import DEMO, _context, _daka_chip, _month_label, _pull_daka, _save_upload, _text
from app.views.overview import _mark

def step_daka(info, status, demo, readonly, staff=None, upload_info=None):
    upload_info = upload_info or info
    other_month = upload_info["key"] != info["key"]
    daka = info["daka"]
    fresh, missing = roster_report(info, demo)
    if status["daka"] == "done":
        _mark("1. 放入 DAKA", "done", "出勤已核對。")
    elif not daka.exists():
        _mark("1. 放入 DAKA", "todo", "請放入本月的 DAKA 出勤檔。")
    elif missing:
        _mark("1. 放入 DAKA", "todo", missing[0])
        for line in missing[1:]:
            st.write(line)
    elif st.session_state.get("check_error"):
        _mark("1. 放入 DAKA", "todo", st.session_state["check_error"])
    else:
        _mark("1. 放入 DAKA", "todo", "正在核對出勤。")
    st.caption(fresh)
    _daka_chip()
    st.caption("手機匯出：在 DAKA 按匯出，儲存到 Files，再放到 Google Drive 的 HR System/dev_testing/daka_inbox。")
    grey = [] if staff is None else list(staff.attrs.get("grey_active") or [])
    if grey:
        names = "、".join(item["name"] for item in grey)
        st.warning(
            f"員工檔有 {len(grey)} 行是灰色但寫在職：{names}。請改為已離職並填上離職日期。"
        )
    if other_month:
        st.caption(f"DAKA 會存入 {upload_info['month']}月，只核對出勤，不會出糧。")
    upload = st.file_uploader("DAKA 出勤檔（CSV）", type=["csv"], disabled=readonly)
    if upload is not None and not readonly:
        token = (upload.name, upload.size, upload_info["key"])
        if st.session_state.get("daka_token") != token:
            _save_upload(upload_info, upload, refresh_payroll=not other_month)
            st.session_state["daka_token"] = token
            if other_month:
                st.session_state.pop("day_join", None)
            st.rerun()
    if other_month or status["daka"] == "done":
        return
    ready = daka.exists() and not missing and not readonly
    stamp = daka.stat().st_mtime if daka.exists() else None
    if ready and st.session_state.get("auto_checked") != stamp:
        try:
            run_check(info, open_workbook=False, fetch=not demo)
        except PermissionError:
            st.session_state["check_error"] = "請先關閉 Excel 中的考勤核對表，然後再試。"
        except SystemExit as error:
            st.session_state["check_error"] = str(error)
        else:
            st.session_state["check_error"] = ""
            st.session_state.pop("draft", None)
        st.session_state["auto_checked"] = stamp
        st.rerun()
    if (missing or st.session_state.get("check_error")) and not readonly and st.button("再試"):
        st.session_state["auto_checked"] = None
        st.session_state["check_error"] = ""
        st.rerun()

def _days_for(info, roster_name):
    path = info["system"] / "days.xlsx"
    if not path.exists() or not _text(roster_name):
        return None
    if "days_frame" not in st.session_state:
        st.session_state["days_frame"] = pd.read_excel(path)
    frame = st.session_state["days_frame"]
    if frame is None or "Name" not in frame.columns:
        return None
    return frame[frame["Name"].astype(str) == roster_name]

from payroll.core.settings import shops as shop_rows

_SHOPS = shop_rows()

def _row_shop(row, code):
    roster = " ".join(str(row.get(column) or "") for column in ("Chosen shop", "Rosters"))
    places = " ".join(
        str(row.get(column) or "")
        for column in ("DAKA in place", "DAKA out place", "DAKA place")
    )
    text = f"{roster} {places}"
    if code == "Pastry":
        return "Pastry" in roster
    if code == "11F":
        return "11F" in text or "11/F" in text or "Office" in text
    if code == "SPK":
        if "Pastry" in roster:
            return False
        return "3F" in roster or "SPK" in roster or "SPK" in places
    return f"{code}_" in text or f" {code}" in f" {text}" or text.startswith(code)

def _month_starts(start, end):
    cursor = date(start.year, start.month, 1)
    stop = date(end.year, end.month, 1)
    months = []
    while cursor <= stop:
        months.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months

def _range_bounds(picked, fallback):
    if isinstance(picked, (tuple, list)):
        dates = [item for item in picked if item is not None]
    elif picked is None:
        dates = []
    else:
        dates = [picked]
    if len(dates) >= 2:
        start, end = dates[0], dates[-1]
    elif len(dates) == 1:
        start = end = dates[0]
    else:
        start = end = fallback
    if start > end:
        start, end = end, start
    return start, end

def _upload_view(info, start, end, whole):
    """A file belongs to one month. A range that crosses a month is saved into the later one."""
    if whole:
        return info
    later = _month_starts(start, end)[-1]
    key = f"{later.year}-{later.month:02d}"
    return info if key == info["key"] else parse_month(key)

def _load_month_days(info, view, demo):
    """The payroll month uses the stored table. Another month only joins attendance."""
    if view["key"] == info["key"]:
        path = info["system"] / "days.xlsx"
        if not path.exists():
            return None, f"{view['month']}月還沒有出勤紀錄。請先放入 DAKA。"
        return pd.read_excel(path), None
    if demo:
        return None, f"示範只有十月的副本，沒有 {view['month']}月。請用薪酬系統查真實出勤。"
    if not view["daka"].exists():
        return None, f"{view['month']}月還沒有 DAKA。請在上面放入。系統只核對出勤，不會出糧。"
    if not view["rosters"].exists():
        return None, f"{view['month']}月還沒有更表，所以暫時不能核對。"
    token = (str(view["daka"]), view["daka"].stat().st_mtime)
    cache = st.session_state.get("day_join")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state["day_join"] = cache
    days_path = view["system"] / "days.xlsx"
    if cache.get(view["key"]) == token and days_path.exists():
        return pd.read_excel(days_path), None
    from payroll.attendance.attendance import run_attendance
    from payroll.attendance.daka import load_daka
    from payroll.attendance.days import merge_days

    facts = run_attendance(
        view["daka"], view["rosters"], view["sheet"],
        view["system"] / f"{view['sheet']}考勤核對表.xlsx",
        view["system"] / "daily_facts.xlsx",
    )
    _summaries, days = merge_days(facts, load_daka(view["daka"]))
    days.to_excel(days_path, index=False)
    cache[view["key"]] = token
    return days, None

def _days_for_range(info, start, end, whole, demo):
    if whole:
        return _load_month_days(info, info, demo)
    frames = []
    notes = []
    for month_start in _month_starts(start, end):
        key = f"{month_start.year}-{month_start.month:02d}"
        view = info if key == info["key"] else parse_month(key)
        frame, note = _load_month_days(info, view, demo)
        if note:
            notes.append(note)
        if frame is not None and len(frame):
            frames.append(frame)
    if not frames:
        return None, notes[0] if notes else "沒有出勤紀錄。"
    days = pd.concat(frames, ignore_index=True)
    if "Date" in days.columns:
        dates = pd.to_datetime(days["Date"], errors="coerce")
        days = days[(dates.dt.date >= start) & (dates.dt.date <= end)]
    note = " ".join(dict.fromkeys(notes)) if notes else None
    return days, note

def _day_counts(shown):
    status = shown["Status"].astype(str) if "Status" in shown.columns else pd.Series([""] * len(shown), index=shown.index)
    late = int((pd.to_numeric(shown["Late"], errors="coerce").fillna(0) > 0).sum()) if "Late" in shown.columns else 0
    early = int((pd.to_numeric(shown["Early"], errors="coerce").fillna(0) > 0).sum()) if "Early" in shown.columns else 0
    absent = int(status.str.contains("全天缺卡").sum())
    missing = int(status.str.contains("缺卡").sum()) - absent
    return late, early, max(missing, 0), absent

def page_attendance():
    _pull_daka()
    info, readonly, draft, staff, table = _context(steps=True)
    status = step_status(info, draft, staff, table)
    page_header("出勤", _month_label(info["key"]))
    yesterday = date.today() - timedelta(days=1)
    with st.container(border=True):
        controls = st.columns([1, 3])
        whole = controls[0].checkbox("整月", value=False)
        picked = controls[1].date_input(
            "查看日期", value=(yesterday, yesterday), disabled=whole, key="attendance-range",
        )
    start, end = _range_bounds(picked, yesterday)
    view = _upload_view(info, start, end, whole)
    step_daka(info, status, DEMO, readonly, staff, upload_info=view)
    days, note = _days_for_range(info, start, end, whole, DEMO)
    if days is None:
        st.info(note or "沒有出勤紀錄。")
        return
    if note:
        st.info(note)
    if "Name" not in days.columns or not len(days):
        st.info("沒有出勤紀錄。" if whole else "這段日期沒有出勤紀錄。")
        return
    names = ["全部", *sorted({_text(name) for name in days["Name"] if _text(name)})]
    with st.container(border=True):
        picked = st.columns(2)
        chosen = picked[0].selectbox("員工", names)
        shop_label = picked[1].selectbox("店鋪", [label for label, _code in _SHOPS])
    shop_code = dict(_SHOPS)[shop_label]
    shown = days if chosen == "全部" else days[days["Name"].astype(str) == chosen]
    if shop_code:
        shown = shown[shown.apply(lambda row: _row_shop(row, shop_code), axis=1)]
    late, early, missing, absent = _day_counts(shown)
    chips([
        (f"遲到 {late}", "todo" if late else "muted"),
        (f"早退 {early}", "block" if early else "muted"),
        (f"缺卡 {missing}", "todo" if missing else "muted"),
        (f"缺勤 {absent}", "block" if absent else "muted"),
    ])
    legend()
    if "Late" in shown.columns and "Date" in shown.columns and len(shown):
        from app.components.charts import bars
        late_rows = shown.copy()
        late_rows["遲到分鐘"] = pd.to_numeric(late_rows["Late"], errors="coerce").fillna(0)
        by_day = late_rows.groupby(late_rows["Date"].astype(str), as_index=False)["遲到分鐘"].sum()
        if len(by_day):
            st.altair_chart(bars(by_day, "Date", "遲到分鐘", title="每日遲到分鐘"), use_container_width=True)
            st.caption("這段日期的遲到分鐘合計。")
    narrow = (not whole) or bool(shop_code) or chosen != "全部"
    frame = shown if narrow else shown.head(400)
    st.dataframe(
        _day_style(frame),
        hide_index=True,
        width="stretch",
        column_config={
            "姓名": st.column_config.TextColumn("姓名", width="medium", pinned=True),
            "日期": st.column_config.TextColumn("日期", width="small", pinned=True),
            "更表": st.column_config.TextColumn("更表", width="medium"),
            "採用店鋪": st.column_config.TextColumn("採用店鋪", width="small"),
            "更表內容": st.column_config.TextColumn("更表內容", width="medium"),
            "上班": st.column_config.TextColumn("上班", width="small"),
            "下班": st.column_config.TextColumn("下班", width="small"),
            "遲到": st.column_config.NumberColumn("遲到", width="small"),
            "早退": st.column_config.NumberColumn("早退", width="small"),
            "加班": st.column_config.NumberColumn("加班", width="small"),
        },
    )
