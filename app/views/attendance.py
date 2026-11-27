"""Attendance for a chosen range, and who was late in the payroll month."""

import html
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

from app.components.cards import kpi, page_header
from app.components.chips import chips, legend
from app.components.tables import style_days as _day_style
from app.context import DEMO, _context, _daka_chip, _month_label, _pull_daka, _text, refresh_rosters
from app.state import roster_report, step_status
from app.views.overview import _mark
from payroll.attendance.lateness import add_punch_counts, late_summary, link_groups, shops_by_name
from payroll.core.config import parse_month
from payroll.core.money import LATE_GRACE_MINUTES
from payroll.core.settings import shops as shop_rows
from payroll.pay.run import run_check
from payroll.staff.directory import GROUPS
from payroll.staff.staff import pay_table_path

_SHOPS = shop_rows()
_LATE_LABELS = {
    "group_label": "組別",
    "employee_no": "員工編號",
    "name": "姓名",
    "times": "遲到次數",
    "minutes": "遲到分鐘",
    "over_grace": f"超過{LATE_GRACE_MINUTES}分鐘",
    "dates": "遲到日期",
    "affects_bonus": "勤工獎",
    "ot_hours": "加班時數",
    "ot_dates": "加班日期",
}


def step_daka(info, status, demo, readonly, staff=None):
    from payroll.core.history import is_issued
    if is_issued(info["key"]):
        _mark("1. 已出糧", "done", "這個月的糧單已經發出，不會再計算。")
        return
    daka = info["daka"]
    fresh, missing = roster_report(info, demo)
    if status["daka"] == "done":
        _mark("1. DAKA 同步", "done", "出勤已核對。")
    elif not daka.exists():
        _mark("1. DAKA 同步", "todo", "本月的 DAKA 還沒有同步。")
    elif missing:
        _mark("1. DAKA 同步", "todo", missing[0])
        for line in missing[1:]:
            st.write(line)
    elif st.session_state.get("check_error"):
        _mark("1. DAKA 同步", "todo", st.session_state["check_error"])
    else:
        _mark("1. DAKA 同步", "todo", "正在核對出勤。")
    st.caption(fresh)
    from payroll.attendance.rosters import oldest_roster_file
    oldest = oldest_roster_file()
    if oldest is not None:
        st.caption(
            f"更表檔案日期：{oldest:%Y-%m-%d %H:%M}。"
            "更新更表只抄這個副本，不會直接讀 Google 更表。"
        )
    _daka_chip()
    if st.button("更新更表", key="attendance-roster", disabled=readonly):
        if refresh_rosters(info):
            st.rerun()
    grey = [] if staff is None else list(staff.attrs.get("grey_active") or [])
    if grey:
        names = "、".join(item["name"] for item in grey)
        st.warning(
            f"員工檔有 {len(grey)} 行是灰色但寫在職：{names}。請改為已離職並填上離職日期。"
        )
    if status["daka"] == "done":
        return
    ready = daka.exists() and not missing and not readonly
    stamp = daka.stat().st_mtime if daka.exists() else None
    if ready and st.session_state.get("auto_checked") != stamp:
        try:
            run_check(info, open_workbook=False, fetch=not demo)
        except PermissionError:
            st.session_state["check_error"] = "請先關閉 Excel 中的考勤核對表，然後再試。"
        except OSError:
            st.session_state["check_error"] = "更表暫時讀不到。請稍後再按「再試」。"
        except SystemExit as error:
            st.session_state["check_error"] = str(error)
        else:
            st.session_state["check_error"] = ""
            st.session_state.pop("draft", None)
        st.session_state["auto_checked"] = stamp
        st.rerun()
    if (missing or st.session_state.get("check_error")) and not readonly and st.button("再試", key="attendance-retry"):
        st.session_state["auto_checked"] = None
        st.session_state["check_error"] = ""
        st.rerun()


def _days_for(info, roster_name):
    path = info["system"] / "days.xlsx"
    if not path.exists() or not _text(roster_name):
        return None
    from payroll.core.excel_io import read_excel
    frame = read_excel(path)
    if frame is None or "Name" not in frame.columns:
        return None
    return frame[frame["Name"].astype(str) == roster_name]


def _row_shop(row, code):
    from payroll.core.settings import code_for_shop, shares_site

    roster = " ".join(str(row.get(column) or "") for column in ("Chosen shop", "Rosters"))
    places = " ".join(
        str(row.get(column) or "")
        for column in ("DAKA in place", "DAKA out place", "DAKA place")
    )
    blob = f"{roster} {places}"
    if not code:
        return False
    row_code = code_for_shop(blob)
    if row_code == code:
        return True
    if shares_site(code, row_code):
        return False
    return code in blob


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


def _with_archive(view):
    """Use the saved punch export and roster folder when this month was not run in GrainHR."""
    from pathlib import Path

    from payroll.core.history import archive_folder, month_punches

    view = dict(view)
    punches = month_punches(view)
    if punches is not None:
        view["daka"] = punches
    if not Path(view["rosters"]).exists():
        folder = archive_folder(view["year"], view["month"])
        shops = None if folder is None else folder / "店鋪數據"
        if shops is not None and shops.exists():
            view["rosters"] = shops
    return view


def _load_month_days(info, view, demo):
    """The open month uses its saved table. A paid month is built once from the archive."""
    import zipfile
    from contextlib import nullcontext
    from pathlib import Path

    from payroll.core.excel_io import read_table
    from payroll.core.history import is_issued

    days_path = Path(view["system"]) / "days.xlsx"
    saved = read_table(days_path)
    if saved is not None:
        return saved, None
    if days_path.exists():
        try:
            days_path.unlink()
        except OSError:
            return None, f"{view['month']}月的出勤檔讀不到。請改到月份紀錄查看糧單。"
    issued = is_issued(view["key"])
    if view["key"] == info["key"] and not issued:
        return None, f"{view['month']}月還沒有出勤紀錄。DAKA 還沒有同步。"
    if demo:
        return None, f"示範只有十月的副本，沒有 {view['month']}月。請用薪酬系統查真實出勤。"
    view = _with_archive(view)
    if not Path(view["daka"]).exists():
        if issued:
            return None, f"{view['month']}月已出糧，但找不到打卡檔。檔案應在出勤封存的 Time_in_data。"
        return None, f"{view['month']}月還沒有 DAKA。等同步之後再看。系統只核對出勤，不會出糧。"
    if not Path(view["rosters"]).exists():
        return None, f"{view['month']}月還沒有更表，所以暫時不能核對。"
    from payroll.attendance.attendance import run_attendance
    from payroll.attendance.daka import load_daka
    from payroll.attendance.days import merge_days

    label = f"第一次打開{view['month']}月，正在整理出勤，大約半分鐘"
    try:
        spinner = st.spinner(label)
    except Exception:
        spinner = nullcontext()
    try:
        with spinner:
            view["system"].mkdir(parents=True, exist_ok=True)
            facts = run_attendance(
                view["daka"], view["rosters"], view["sheet"],
                view["system"] / f"{view['sheet']}考勤核對表.xlsx",
                view["system"] / "daily_facts.xlsx",
            )
            _summaries, days = merge_days(facts, load_daka(view["daka"]))
            days.to_excel(days_path, index=False, engine="openpyxl")
    except (OSError, ValueError, zipfile.BadZipFile):
        return None, f"{view['month']}月的出勤檔讀不到。請改到月份紀錄查看糧單。"
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
    late_minutes = pd.to_numeric(shown["Late"], errors="coerce").fillna(0) if "Late" in shown.columns else pd.Series(0, index=shown.index)
    late = int((late_minutes > 0).sum())
    late_over = int((late_minutes > LATE_GRACE_MINUTES).sum())
    early = int((pd.to_numeric(shown["Early"], errors="coerce").fillna(0) > 0).sum()) if "Early" in shown.columns else 0
    absent = int(status.str.contains("全天缺卡").sum())
    missing = int(status.str.contains("缺卡").sum()) - absent
    return late, late_over, early, max(missing, 0), absent


def _empty(title, detail):
    st.markdown(
        f'<div class="gh-empty"><strong>{html.escape(title)}</strong>{html.escape(detail)}</div>',
        unsafe_allow_html=True,
    )


def _choose(key, options, default):
    """Keep a widget value only when it is still one of the options."""
    if not options:
        return default
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default in options else options[0]
    return st.session_state[key]


def _with_hours(shown):
    """工時 is the roster length, plus overtime, minus early leave."""
    from payroll.attendance.days import day_hours

    labels = []
    for _, row in shown.iterrows():
        status = _text(row.get("Status"))
        labels.append(day_hours(
            row.get("Roster cell"), row.get("OT"), row.get("Early"),
            row.get("DAKA in"), row.get("DAKA out"), status,
        ))
    stamped = shown.copy()
    stamped["工時"] = labels
    return stamped


def _page_rows(frame, key):
    size = 100
    if len(frame) <= size:
        return frame
    pages = (len(frame) - 1) // size + 1
    page = int(st.number_input("頁", min_value=1, max_value=pages, value=1, step=1, key=key))
    start = (page - 1) * size
    st.caption(f"第 {page} / {pages} 頁，每頁 {size} 行。")
    return frame.iloc[start:start + size]


def _day_table(frame):
    st.dataframe(
        _day_style(frame),
        hide_index=True,
        width="stretch",
        alt="出勤日期、更表和打卡時間",
        column_config={
            "姓名": st.column_config.TextColumn("姓名", width="medium", pinned=True),
            "日期": st.column_config.TextColumn("日期", width="small", pinned=True),
            "更表": st.column_config.TextColumn("更表", width="medium"),
            "採用店鋪": st.column_config.TextColumn("採用店鋪", width="small"),
            "更表內容": st.column_config.TextColumn("更表內容", width="medium"),
            "上班": st.column_config.TextColumn("上班", width="small"),
            "下班": st.column_config.TextColumn("下班", width="small"),
            "工時": st.column_config.TextColumn(
                "工時", width="medium",
                help="平常是更表時數加加班，減早退。休息日有打卡則按上班到下班計算。",
            ),
            "遲到": st.column_config.NumberColumn("遲到", width="small"),
            "早退": st.column_config.NumberColumn("早退", width="small"),
            "加班": st.column_config.NumberColumn("加班", width="small"),
        },
    )


@st.fragment
def _daily_record(info, status, staff, readonly):
    yesterday = date.today() - timedelta(days=1)
    with st.container(border=True):
        controls = st.columns([1, 3], vertical_alignment="bottom")
        whole = controls[0].checkbox("整月", key="attendance-whole")
        picked = controls[1].date_input(
            "查看日期", value=(yesterday, yesterday), disabled=whole, key="attendance-range",
            format="YYYY-MM-DD",
        )
    start, end = _range_bounds(picked, yesterday)
    step_daka(info, status, DEMO, readonly, staff)
    days, note = _days_for_range(info, start, end, whole, DEMO)
    if days is None:
        from app.components.cards import empty_state
        from payroll.core.history import is_issued
        if is_issued(info["key"]):
            empty_state(
                "這個月沒有出勤紀錄",
                note or "已出糧，只供查看。",
                "前往月份紀錄",
                "screens/records.py",
            )
        else:
            empty_state("沒有出勤紀錄", note or "DAKA 還沒有同步。")
        return
    if note:
        st.info(note)
    if "Name" not in days.columns or not len(days):
        _empty("沒有出勤紀錄", "這段日期還沒有打卡，或 DAKA 還沒有同步。")
        return
    names = ["全部", *sorted({_text(name) for name in days["Name"] if _text(name)})]
    shop_labels = [label for label, _code in _SHOPS]
    with st.container(border=True):
        picked_filters = st.columns(2)
        _choose("attendance-person", names, "全部")
        _choose("attendance-shop", shop_labels, shop_labels[0])
        chosen = picked_filters[0].selectbox("員工", names, key="attendance-person")
        shop_label = picked_filters[1].selectbox("店鋪", shop_labels, key="attendance-shop")
    shop_code = dict(_SHOPS)[shop_label]
    shown = days if chosen == "全部" else days[days["Name"].astype(str) == chosen]
    if shop_code:
        shown = shown[shown.apply(lambda row: _row_shop(row, shop_code), axis=1)]
    late, late_over, early, missing, absent = _day_counts(shown)
    if late_over:
        late_tone = "block"
    elif late:
        late_tone = "todo"
    else:
        late_tone = "muted"
    chips([
        (f"遲到 {late}", late_tone),
        (f"早退 {early}", "block" if early else "muted"),
        (f"缺卡 {missing}", "todo" if missing else "muted"),
        (f"缺勤 {absent}", "block" if absent else "muted"),
    ])
    legend()
    if not len(shown):
        _empty("沒有符合的出勤", "試下改日期、員工或店鋪。")
        return
    if whole and not shop_code and chosen == "全部":
        st.caption(f"整月全部員工，共 {len(shown)} 行。")
    _day_table(_page_rows(_with_hours(shown), "attendance-page"))


def _pay_tables():
    token = []
    paths = []
    for book in ("bg", "md", "admin"):
        path = pay_table_path(book)
        paths.append((book, path))
        token.append(path.stat().st_mtime_ns if path.exists() else 0)
    token = tuple(token)
    cache = st.session_state.get("late-pay-tables")
    if cache and cache[0] == token:
        return cache[1]
    tables = {}
    for book, path in paths:
        if path.exists():
            from payroll.core.excel_io import read_excel
            tables[book] = read_excel(path, dtype={"employee_no": str, "roster_name": str})
    st.session_state["late-pay-tables"] = (token, tables)
    return tables


def _part_time_people(staff):
    if staff is None or "part_time" not in staff.columns:
        return []
    people = staff[staff["part_time"].fillna(False).astype(bool)]
    return people.to_dict("records")


def _group_choice(summary):
    counts = summary["group"].value_counts().to_dict() if len(summary) else {}
    keys = ["all"]
    options = [f"全部 {len(summary)}"]
    for key, label in GROUPS:
        count = int(counts.get(key, 0))
        if not count:
            continue
        keys.append(key)
        options.append(f"{label} {count}")
    other = int(counts.get("", 0))
    if other:
        keys.append("")
        options.append(f"未分類 {other}")
    if len(options) < 2:
        st.session_state["late-group-key"] = "all"
        return "all"
    saved = st.session_state.get("late-group-key", "all")
    if saved not in keys:
        saved = "all"
    label = options[keys.index(saved)]
    if st.session_state.get("late-group") not in options:
        st.session_state["late-group"] = label
    picked = st.segmented_control("組別", options, key="late-group") or label
    choice = keys[options.index(picked)] if picked in options else "all"
    st.session_state["late-group-key"] = choice
    return choice


def _paint_bonus(frame):
    def paint(row):
        styles = [""] * len(row)
        if _text(row.get("勤工獎")) == "影響勤工獎" and "勤工獎" in row.index:
            styles[list(row.index).index("勤工獎")] = "color: #C0392B; font-weight: 700"
        return styles
    return frame.style.apply(paint, axis=1)


def _late_bytes(shown):
    from payroll.core.excel_io import safe_frame
    view = shown.drop(columns=["group", "roster_names"], errors="ignore").rename(columns=_LATE_LABELS)
    buffer = BytesIO()
    safe_frame(view).to_excel(buffer, index=False)
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment
    book = load_workbook(buffer)
    sheet = book.active
    for cell in sheet[1]:
        if cell.value not in {"遲到日期", "加班日期"}:
            continue
        sheet.column_dimensions[cell.column_letter].width = 72
        for row in sheet.iter_rows(min_row=2, min_col=cell.column, max_col=cell.column):
            row[0].alignment = Alignment(wrap_text=True, vertical="top")
    packed = BytesIO()
    book.save(packed)
    return packed.getvalue()


def _export_late(shown, month_key):
    st.download_button(
        "下載遲到統計",
        data=lambda: _late_bytes(shown),
        file_name=f"遲到統計_{month_key}.xlsx",
        key="late-export",
        on_click="ignore",
    )


def _person_label(row, index):
    return " ".join(part for part in (_text(row["employee_no"]), _text(row["name"])) if part) or f"{index}"


def _show_late_notes(dates):
    """One block per late day. The sentence wraps, and the four clocks sit on the next line."""
    blocks = [block.strip() for block in _text(dates).split("\n\n") if block.strip()]
    if not blocks:
        return
    notes = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        body = f"<div>{html.escape(lines[0])}</div>"
        for line in lines[1:]:
            body += f'<div class="gh-late-next">{html.escape(line)}</div>'
        notes.append(f'<div class="gh-late-note">{body}</div>')
    st.markdown("".join(notes), unsafe_allow_html=True)


def _late_checked(info):
    path = info["system"] / "late_checked.txt"
    if path.exists():
        st.caption(f"上次核對：{path.read_text(encoding='utf-8').strip()}")
    if st.button("已核對遲到", key="late-checked"):
        from app.state import mark_late_checked
        mark_late_checked(info)
        st.toast("已記錄本月的遲到核對。")
        st.rerun()


@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def _counted_days(days, daka, daka_stamp):
    from payroll.attendance.daka import punch_logs
    del daka_stamp
    logs = punch_logs(daka)
    return add_punch_counts(days, {key: len(value) for key, value in logs.items()}, logs)


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def _late_table(days, links, hide):
    return late_summary(days, links, hide_within_grace=hide)


def _late_report(info, staff):
    st.caption(
        f"單次遲到超過 {LATE_GRACE_MINUTES} 分鐘會沒有勤工獎。"
        f"{LATE_GRACE_MINUTES} 分鐘或以下仍然有。寫字樓、兼職和內地勞工沒有勤工獎。"
        "打卡次數是當天的上班和下班記錄。平時打卡 4 次而當天少於 4 次會標明。"
        "打滿 4 次仍然遲到時，四次的上班和下班時間都會列出，方便核對是不是第一次上班遲了。"
    )
    days, note = _load_month_days(info, info, DEMO)
    if days is None:
        from app.components.cards import empty_state
        from payroll.core.history import is_issued
        if is_issued(info["key"]):
            empty_state(
                "這個月沒有出勤紀錄",
                note or "已出糧，只供查看。",
                "前往月份紀錄",
                "screens/records.py",
            )
        else:
            empty_state("沒有出勤紀錄", note or "DAKA 還沒有同步。")
        return
    if note:
        st.info(note)
    if "Name" not in days.columns or not len(days):
        _empty("這個月沒有出勤紀錄", "DAKA 同步之後，這裡會列出遲到的同事。")
        return
    _late_checked(info)
    if info["daka"].exists():
        days = _counted_days(days, info["daka"], info["daka"].stat().st_mtime_ns)
    late_names = sorted({
        _text(name) for name, minutes in zip(days["Name"], pd.to_numeric(days["Late"], errors="coerce").fillna(0))
        if _text(name) and minutes > 0
    })
    links = link_groups(late_names, staff, _pay_tables(), _part_time_people(staff), shops_by_name(days))
    # The toggle and the search already wrote their values before this run.
    hide = bool(st.session_state.get("late-hide-small"))
    summary = _late_table(days, links, hide)
    with st.container(border=True):
        choice = _group_choice(summary)
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.toggle(f"隱藏 {LATE_GRACE_MINUTES} 分鐘或以下", key="late-hide-small")
            st.text_input("搜尋姓名或員工編號", key="late-query", width="stretch")
    query = _text(st.session_state.get("late-query"))
    if choice != "all":
        summary = summary[summary["group"].astype(str).eq(choice)]
    needle = _text(query).lower()
    if needle:
        summary = summary[summary.apply(
            lambda row: needle in f"{row['employee_no']} {row['name']}".lower(), axis=1,
        )]
    people = len(summary)
    times = int(summary["times"].sum()) if people else 0
    minutes = int(summary["minutes"].sum()) if people else 0
    over = int(summary["affects_bonus"].astype(str).eq("影響勤工獎").sum()) if people else 0
    cards = (
        ("遲到人數", people, "有遲到的同事", "todo" if people else "ok"),
        ("遲到次數", times, "一人一日計一次", "info"),
        ("遲到分鐘", minutes, "全部加起來", "info"),
        (f"逾{LATE_GRACE_MINUTES}分鐘", over, "單次超過會沒有勤工獎", "block" if over else "ok"),
    )
    columns = st.columns(4)
    for column, (label, value, note_text, tone) in zip(columns, cards):
        with column:
            kpi(label, value, note_text, tone)
    if not people:
        _empty("沒有符合的遲到", "可以改組別，或關掉「隱藏 5 分鐘或以下」。")
        return
    view = summary.drop(columns=["group", "roster_names", "dates", "ot_dates"]).rename(columns=_LATE_LABELS)
    peak = max(int(summary["minutes"].max()), 1)
    st.dataframe(
        _paint_bonus(view),
        hide_index=True,
        width="stretch",
        alt="各員工本月遲到次數和分鐘",
        column_config={
            "姓名": st.column_config.TextColumn("姓名", pinned=True),
            "員工編號": st.column_config.TextColumn("員工編號", width="small"),
            "遲到分鐘": st.column_config.ProgressColumn(
                "遲到分鐘", min_value=0, max_value=peak, format="%d", color="#C8963E", width="medium",
            ),
            "加班時數": st.column_config.NumberColumn(
                "加班時數", width="small", format="%.1f",
                help="零售同事本月的加班。遲到有可能是用這些時間補鐘。",
            ),
            "勤工獎": st.column_config.TextColumn(
                "勤工獎", width="small",
                help=f"兼職、內地勞工和寫字樓沒有勤工獎。其他人單次超過 {LATE_GRACE_MINUTES} 分鐘就沒有。",
            ),
        },
    )
    _export_late(summary, info["key"])
    labels = []
    seen = {}
    for index, row in summary.iterrows():
        label = _person_label(row, index)
        if label in seen:
            label = f"{label} {len(seen)}"
        seen[label] = index
        labels.append(label)
    _choose("late-person", labels, labels[0])
    picked_person = st.selectbox("查看一人", labels, key="late-person")
    person = summary.loc[seen[picked_person]]
    st.caption(f"{_text(person['name'])} 的遲到日期。一句太長會換到下一行；打滿 4 次時，四個時間在下一行。")
    _show_late_notes(person["dates"])
    if _text(person.get("group")) == "bg_retail" and _text(person.get("ot_dates")):
        st.caption("這位零售同事本月有加班。遲到有可能是用這些時間補鐘。")
        _show_late_notes(person["ot_dates"])


def page_attendance():
    _pull_daka()
    info, readonly, draft, staff, _table = _context(steps=True, edit=True, build=False)
    status = step_status(info, draft, staff, _table)
    page_header("出勤紀錄", _month_label(info["key"]), purpose="核對打卡、更表、遲到和加班。已出糧的月份只供查看。")
    daily, late = st.tabs(["每日紀錄", "遲到統計"], on_change="rerun", key="attendance-tabs")
    if daily.open:
        with daily:
            _daily_record(info, status, staff, readonly)
    if late.open:
        with late:
            _late_report(info, staff)
