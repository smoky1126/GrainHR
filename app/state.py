"""Plain answers the payroll page needs. No browser here, so tests can call them."""

import re
from datetime import date, datetime

import pandas as pd

from payroll.core.settings import shop_label

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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


def month_choices(today=None):
    """Payroll months on this computer, and the one HR should open."""
    from payroll.core.config import home
    from payroll.core.history import is_issued
    from payroll.core.listings import remember

    today = today or date.today()
    folder = home() / "months"

    def build():
        options = []
        if folder.exists():
            options = [
                path.name.replace("_", "-")
                for path in folder.iterdir()
                if path.is_dir() and len(path.name) == 7 and path.name[4] == "_"
            ]
        options.extend(f"{today.year}-{month:02d}" for month in range(1, today.month + 1))
        current = last_month(today)
        options.append(current)
        options = sorted(set(options))
        open_months = [key for key in options if not is_issued(key)]
        if open_months:
            current = open_months[-1]
        return options, current

    return remember(("month-choices", str(folder), today.isoformat()), folder, build)


_PROGRESS = {}


def _progress_stamp(info):
    from pathlib import Path
    from payroll.core.config import ROSTER_COPY_DIR, book_info
    paths = [
        info["daka"],
        info["system"] / "daily_facts.xlsx",
        info["system"] / "late_checked.txt",
        info["folder"] / "payroll_draft.xlsx",
    ]
    if ROSTER_COPY_DIR:
        paths.append(Path(ROSTER_COPY_DIR))
    for book in ("bg", "md", "admin"):
        paths.append(book_info(info, book)["slip_output"])
    stamps = []
    for path in paths:
        try:
            stat = Path(path).stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append((str(path), 0, 0))
    return tuple(stamps)


def month_progress(info):
    """The six checks HR finishes before a month is paid."""
    stamp = _progress_stamp(info)
    hit = _PROGRESS.get(info["key"])
    if hit and hit[0] == stamp:
        return list(hit[1])
    rows = _month_progress(info)
    _PROGRESS[info["key"]] = (stamp, rows)
    return list(rows)


def _month_progress(info):
    from payroll.core.config import book_info

    daka_ready = info["daka"].exists()
    try:
        from datetime import date as _date
        from payroll.attendance.today import roster_files
        _info, _found, missing_files = roster_files(_date(info["year"], info["month"], 1))
        rosters_ready = not missing_files
    except SystemExit:
        rosters_ready = False
    except Exception:
        rosters_ready = False
    facts = info["system"] / "daily_facts.xlsx"
    if facts.exists():
        try:
            names_ready = not unlinked_roster_names(info)
        except SystemExit:
            names_ready = False
        except Exception:
            names_ready = False
    else:
        names_ready = False
    slips = [book_info(info, book)["slip_output"].exists() for book in ("bg", "md", "admin")]
    return [
        ("DAKA 已上傳", daka_ready),
        ("更表已找到", rosters_ready),
        ("名字已配對", names_ready),
        ("遲到已核對", (info["system"] / "late_checked.txt").exists()),
        ("糧單已計算", (info["folder"] / "payroll_draft.xlsx").exists()),
        ("糧單已製作", all(slips)),
    ]


def mark_late_checked(info):
    from datetime import datetime

    from payroll.core.settings import actor

    path = info["system"] / "late_checked.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{datetime.now():%Y-%m-%d %H:%M} {actor()}\n", encoding="utf-8")
    return path


def last_month(today=None):
    today = today or date.today()
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def format_pay_date(value):
    return f"{value.day} {_MONTHS[value.month]} {value.year}"


def parse_pay_date(text):
    raw = _text(text)
    if not raw:
        return None
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def problem_people(draft):
    if draft is None or len(draft) == 0 or "review" not in draft.columns:
        return draft.iloc[0:0] if draft is not None else draft
    text = draft["review"].astype(str).str.strip()
    mask = text.ne("") & text.str.lower().ne("nan")
    if "ot_hours_detected" in draft.columns:
        hours = pd.to_numeric(draft["ot_hours_detected"], errors="coerce").fillna(0)
        mask = mask | (hours > 0)
    if "ot_suggest" in draft.columns and "ot_text" in draft.columns:
        suggest = draft["ot_suggest"].astype(str).str.strip()
        saved = draft["ot_text"].astype(str).str.strip()
        pending = suggest.ne("") & suggest.str.lower().ne("nan") & (saved.eq("") | saved.str.lower().eq("nan"))
        mask = mask | pending
    if "pay_this" in draft.columns:
        mask = mask & draft["pay_this"].astype(bool)
    return draft[mask].copy()


def new_joiners(staff, pay_table, info=None):
    from payroll.staff.staff import employed_in, paid_numbers
    paid = paid_numbers()
    if pay_table is not None and "employee_no" in pay_table.columns:
        paid.update(_text(value) for value in pay_table["employee_no"])
    paid.discard("")
    if info is None:
        people = staff[staff["active"] & ~staff["part_time"]]
    else:
        people = staff[employed_in(staff, info) & ~staff["part_time"]]
    from payroll.staff.staff import _as_date
    end = None if info is None else date(info["year"], info["month"], info["days"])
    from payroll.core.settings import no_monthly_pay
    outside = no_monthly_pay()
    found = []
    for _, record in people.iterrows():
        number = _text(record["employee_no"])
        if number in paid or number in outside or _text(record.get("status")) == "已離職":
            continue
        left = _as_date(record.get("leave_date"))
        if left is not None and (end is None or left <= end):
            continue
        found.append(record)
    return found


def default_scheme(record):
    """內地勞工 are housed by the company, so the form starts on rent."""
    return "rent" if _text(record.get("sheet")) == "內地勞工" else "mpf"


def unlinked_roster_names(info, pay_table=None):
    facts_path = info["system"] / "daily_facts.xlsx"
    if not facts_path.exists():
        return []
    from payroll.core.excel_io import read_excel
    facts = read_excel(facts_path)
    if "name" not in facts.columns:
        return []
    names = {_text(value) for value in facts["name"]}
    names.discard("")
    from payroll.staff.staff import pay_table_path
    linked = set()
    for book in ("bg", "md", "admin"):
        path = pay_table_path(book)
        if not path.exists():
            continue
        table = read_excel(path)
        if "roster_name" in table.columns:
            linked.update(_text(value) for value in table["roster_name"])
    if pay_table is not None and "roster_name" in pay_table.columns:
        linked.update(_text(value) for value in pay_table["roster_name"])
    linked.discard("")
    return sorted(names - linked)


def roster_report(info, demo=False):
    """Chinese lines for the 12 shops, and whether every roster is ready."""
    from payroll.attendance.rosters import roster_status

    source = info["rosters"] if demo else None
    copied, rows = roster_status(info, source=source)
    missing = []
    for row in rows:
        if row["狀態"] == "已找到":
            continue
        missing.append(f"{shop_label(row['店鋪']) or row['店鋪']}：缺少更表")
    return _freshness(copied, demo, not missing), missing


def _freshness(copied, demo, ready):
    if demo and ready:
        return "示範使用已儲存的十月更表。"
    match = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", copied or "")
    if not match:
        return "未有更表複製時間。請先執行一次更表複製。"
    when = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
    minutes = int((datetime.now() - when).total_seconds() // 60)
    if minutes < 1:
        return "更表最後更新：剛剛"
    if minutes < 60:
        return f"更表最後更新：{minutes} 分鐘前"
    return f"更表最後更新：{minutes // 60} 小時前"


def _daka_done(info):
    daka = info["daka"]
    facts = info["system"] / "daily_facts.xlsx"
    return daka.exists() and facts.exists() and facts.stat().st_mtime >= daka.stat().st_mtime


def step_status(info, draft=None, staff=None, pay_table=None, slips_ready=False):
    """done, todo, or wait for each of the four steps."""
    daka_done = _daka_done(info)
    joiners = []
    if daka_done and staff is not None and pay_table is not None:
        joiners = new_joiners(staff, pay_table, info)
    if not daka_done:
        joiner_state = "wait"
    elif joiners:
        joiner_state = "todo"
    else:
        joiner_state = "done"
    problems = None if draft is None else problem_people(draft)
    problems_reason = ""
    if joiner_state != "done":
        problem_state = "wait"
        problems_reason = "daka" if not daka_done else "joiners"
    elif problems is None:
        # The attendance page skips the salary calculation. That is not an unfinished earlier step.
        problem_state = "todo"
        problems_reason = "draft"
    else:
        approved = problems["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"]) if len(problems) else []
        problem_state = "done" if len(problems) == 0 or (len(approved) and bool(approved.all())) else "todo"
    if joiner_state != "done":
        pay_state = "wait"
    elif slips_ready:
        pay_state = "done"
    else:
        pay_state = "todo"
    late_done = (info["system"] / "late_checked.txt").exists()
    if not daka_done:
        late_state = "wait"
    elif late_done:
        late_state = "done"
    else:
        late_state = "todo"
    if joiner_state != "done":
        salary_state = "wait"
    elif draft is not None:
        salary_state = "done"
    else:
        salary_state = "todo"
    return {
        "daka": "done" if daka_done else "todo",
        "late": late_state,
        "joiners": joiner_state,
        "joiner_count": len(joiners),
        "problems": problem_state,
        "problems_reason": problems_reason,
        "problem_count": 0 if problems is None else len(problems),
        "salary": salary_state,
        "pay": pay_state,
    }


def pipeline_notes(info):
    """When each month file was last saved, and whether an earlier file is newer."""
    from datetime import datetime
    from payroll.core.config import book_info

    def saved(path):
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return None

    daka = saved(info["daka"])
    facts = saved(info["system"] / "daily_facts.xlsx")
    late = saved(info["system"] / "late_checked.txt")
    adjustments = saved(info["adjustments"])
    slips = [saved(book_info(info, book)["slip_output"]) for book in ("bg", "md", "admin")]
    slips = [item for item in slips if item]
    newest_slip = max(slips) if slips else None

    def text(when, earlier):
        if when is None:
            return "未有"
        label = when.strftime("%m-%d %H:%M")
        if earlier is not None and earlier > when:
            return f"{label} 需更新"
        return label

    return {
        "daka": text(facts or daka, None),
        "late": text(late, facts),
        "joiners": text(adjustments, facts),
        "problems": text(adjustments, facts),
        "salary": text(adjustments, facts),
        "pay": text(newest_slip, adjustments),
    }
