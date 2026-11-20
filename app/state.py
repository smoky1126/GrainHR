"""Plain answers the payroll page needs. No browser here, so tests can call them."""

import re
from datetime import date, datetime

import pandas as pd

SHOP_NAMES = {
    "3F_Bread": "新蒲崗工場麵包",
    "3F_Pastry": "新蒲崗工場餅房",
    "11F": "寫字樓",
    "JD_Bread": "佐敦麵包",
    "TKS_Bread": "太古麵包",
    "TW_Bread": "荃灣麵包",
    "WC_Bread": "灣仔麵包",
    "HKU_Retail": "西環零售",
    "JD_Retail": "佐敦零售",
    "TKS_Retail": "太古零售",
    "TW_Retail": "荃灣零售",
    "WC_Retail": "灣仔零售",
}

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
    found = []
    for _, record in people.iterrows():
        if _text(record["employee_no"]) in paid or _text(record.get("status")) == "已離職":
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
    facts = pd.read_excel(facts_path)
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
        table = pd.read_excel(path)
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
        missing.append(f"{SHOP_NAMES.get(row['店鋪'], row['店鋪'])}：缺少更表")
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
    if joiner_state != "done":
        problem_state = "wait"
    elif problems is None:
        problem_state = "wait"
    else:
        approved = problems["approved"].astype(str).str.strip().str.upper().isin(["Y", "是"]) if len(problems) else []
        problem_state = "done" if len(problems) == 0 or (len(approved) and bool(approved.all())) else "todo"
    if joiner_state != "done":
        pay_state = "wait"
    elif slips_ready:
        pay_state = "done"
    else:
        pay_state = "todo"
    return {
        "daka": "done" if daka_done else "todo",
        "joiners": joiner_state,
        "joiner_count": len(joiners),
        "problems": problem_state,
        "problem_count": 0 if problems is None else len(problems),
        "pay": pay_state,
    }
