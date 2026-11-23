"""Who was late this month, and which staff group they belong to.

A minute late is still late. One lateness longer than LATE_GRACE_MINUTES is
what removes the attendance bonus. These functions only read rows that the
attendance check has already scored.
"""

import re

import pandas as pd

from payroll.core.money import LATE_GRACE_MINUTES
from payroll.core.names import match_roster_name
from payroll.pay.part_time import link_facts
from payroll.staff.directory import GROUP_LABEL, staff_group

_PT_MARK = re.compile(r"[\(（]\s*PT\s*[\)）]", re.I)
_PART_TIME_GROUP = {"bg_prod": "bg_pt", "bg_retail": "bg_pt", "md_ft": "md_pt"}
# Full-time production and retail earn the attendance bonus. Part-time, mainland, and office staff do not.
_BONUS_GROUPS = {"bg_prod", "bg_retail", "md_ft"}

SUMMARY_COLUMNS = [
    "group", "group_label", "employee_no", "name", "times", "minutes",
    "over_grace", "dates", "affects_bonus", "ot_hours", "ot_dates", "roster_names",
]
_RETAIL = "bg_retail"
_DAY_COLUMNS = [
    "日期", "更表時間", "上班打卡", "遲到", "打卡次數",
    "第1次上班", "第1次下班", "第2次上班", "第2次下班",
]


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


def _iso(value):
    text = _text(value)
    if not text:
        return ""
    try:
        return pd.to_datetime(text).strftime("%Y-%m-%d")
    except Exception:
        return text[:10]


def _day_label(iso):
    parts = str(iso).split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[2])}/{int(parts[1])}"
    return str(iso)


def _records(frame):
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        if frame.empty:
            return []
        return [row for _, row in frame.iterrows()]
    return list(frame)


def _active_rank(record):
    active = record.get("active")
    if active is True or _text(active) in {"1", "True", "true"}:
        return 1
    return 0


def _staff_index(staff):
    found = {}
    for record in sorted(_records(staff), key=_active_rank):
        number = _text(record.get("employee_no"))
        if number:
            found[number] = record
    return found


def _tables(pay_tables):
    if not pay_tables:
        return []
    if isinstance(pay_tables, dict):
        return list(pay_tables.values())
    return list(pay_tables)


def shops_by_name(days):
    """Chosen shop for each roster name, in the order the rows appear."""
    found = {}
    if days is None or not len(days) or "Name" not in days.columns:
        return found
    for _, row in days.iterrows():
        name = _text(row.get("Name"))
        shop = _text(row.get("Chosen shop"))
        if not name or not shop:
            continue
        bucket = found.setdefault(name, [])
        if shop not in bucket:
            bucket.append(shop)
    return found


def _shop_group(shop):
    from payroll.core.settings import shop_groups

    text = _text(shop)
    for group, tokens in shop_groups():
        if any(token in text for token in tokens):
            return group
    return ""


def _fallback_group(name, shops):
    counts = {}
    for shop in shops or []:
        group = _shop_group(shop)
        if group:
            counts[group] = counts.get(group, 0) + 1
    if not counts:
        return ""
    group = max(counts, key=lambda key: (counts[key], key))
    if _PT_MARK.search(_text(name)):
        return _PART_TIME_GROUP.get(group, group)
    return group


def _apply(link, number, staff_by_number):
    link["employee_no"] = number
    record = staff_by_number.get(number)
    if record is None:
        return
    link["name"] = _text(record.get("name_zh")) or _text(record.get("name_en")) or link["name"]
    link["group"] = staff_group(
        record.get("department"), record.get("employment"), record.get("position"), record.get("sheet"),
    ) or ""


def link_groups(roster_names, staff, pay_tables, pt_people, name_shops=None):
    """Link each roster name to an employee number and a staff group.

    The first source that names exactly one person wins: the pay tables,
    then the part-time name match, then the roster-name match. A name that
    still has no person takes its group from the shop on the shift.
    """
    links = {}
    for name in roster_names:
        text = _text(name)
        if text and text not in links:
            links[text] = {"employee_no": "", "group": "", "name": text}
    staff_by_number = _staff_index(staff)
    from_pay = {}
    conflict = set()
    for table in _tables(pay_tables):
        if table is None or not len(table) or "roster_name" not in getattr(table, "columns", []):
            continue
        for _, row in table.iterrows():
            roster = _text(row.get("roster_name"))
            number = _text(row.get("employee_no"))
            if not roster or not number or roster not in links:
                continue
            previous = from_pay.get(roster)
            if previous and previous != number:
                conflict.add(roster)
            else:
                from_pay[roster] = number
    for roster in conflict:
        from_pay.pop(roster, None)
    for roster, number in from_pay.items():
        _apply(links[roster], number, staff_by_number)

    remaining = [name for name, link in links.items() if not link["employee_no"]]
    if remaining and pt_people:
        assigned = link_facts(list(pt_people), remaining)
        inverted = {}
        for number, facts in assigned.items():
            for fact in facts:
                inverted.setdefault(_text(fact), []).append(_text(number))
        for roster, numbers in inverted.items():
            unique = {number for number in numbers if number}
            if roster in links and not links[roster]["employee_no"] and len(unique) == 1:
                _apply(links[roster], unique.pop(), staff_by_number)

    remaining = [name for name, link in links.items() if not link["employee_no"]]
    if remaining and staff_by_number:
        claims = {}
        for record in staff_by_number.values():
            number = _text(record.get("employee_no"))
            matched = match_roster_name(
                _text(record.get("name_zh")) or _text(record.get("roster_hint")),
                _text(record.get("name_en")) or _text(record.get("roster_hint")),
                _text(record.get("name_zh")),
                remaining,
            )
            if matched:
                claims.setdefault(matched, set()).add(number)
        for roster, numbers in claims.items():
            if len(numbers) == 1 and not links[roster]["employee_no"]:
                _apply(links[roster], numbers.pop(), staff_by_number)

    from payroll.core.settings import name_aliases
    aliases = name_aliases()
    for roster, link in links.items():
        if link["employee_no"]:
            continue
        target = aliases.get(roster, "")
        if target in staff_by_number:
            _apply(link, target, staff_by_number)

    shops = name_shops or {}
    for roster, link in links.items():
        if link["employee_no"]:
            continue
        link["group"] = _fallback_group(roster, shops.get(roster))
    return links


def add_punch_counts(days, counts, logs=None):
    """Copy the day table and add how many DAKA clocks each row has.

    `logs` maps a person and date to the ordered (上班 or 下班, time) pairs.
    A full four-clock day keeps that text so HR can see every time.
    """
    from payroll.attendance.daka import format_clocks
    out = days.copy()
    found = []
    texts = []
    for _, row in out.iterrows():
        key = (_text(row.get("Name")), _iso(row.get("Date")))
        clocks = list((logs or {}).get(key) or [])
        found.append(int(counts.get(key) or 0) or len(clocks))
        texts.append(format_clocks(clocks) if len(clocks) == 4 else "")
    out["Punch count"] = found
    out["Punch log"] = texts
    return out


def _count(value):
    text = _text(value)
    if not text:
        return None
    try:
        number = int(float(text))
    except ValueError:
        return None
    return number if number > 0 else None


def _usually_four(days):
    """Roster names whose DAKA days are usually four clocks."""
    if days is None or not len(days) or "Punch count" not in days.columns:
        return set()
    found = {}
    for _, row in days.iterrows():
        name = _text(row.get("Name"))
        count = _count(row.get("Punch count"))
        if name and count:
            found.setdefault(name, []).append(count)
    names = set()
    for name, values in found.items():
        tally = {}
        for count in values:
            tally[count] = tally.get(count, 0) + 1
        ranked = sorted(tally.items(), key=lambda item: (-item[1], -item[0]))
        if ranked[0][0] == 4 and (len(ranked) == 1 or ranked[1][1] < ranked[0][1]):
            names.add(name)
    return names


def _split_log(log):
    """The four DAKA times, in column order. Missing clocks stay blank."""
    times = ["", "", "", ""]
    parts = [part.strip() for part in _text(log).split("、") if part.strip()]
    for index, part in enumerate(parts[:4]):
        bits = part.split()
        times[index] = bits[-1] if bits else ""
    return times


def _hours(value):
    text = _text(value)
    if not text:
        return 0.0
    try:
        number = float(text)
    except ValueError:
        return 0.0
    if number != number:
        return 0.0
    return number


def _hour_text(hours):
    text = f"{float(hours):.1f}"
    return text[:-2] if text.endswith(".0") else text


def _overtime_by_name(days):
    """Extra hours worked this month, by roster name. Same-day rows keep the larger amount."""
    found = {}
    if days is None or not len(days) or "OT" not in days.columns:
        return found
    for _, row in days.iterrows():
        hours = _hours(row.get("OT"))
        name = _text(row.get("Name"))
        day = _iso(row.get("Date"))
        if not name or not day or hours <= 0:
            continue
        current = found.setdefault(name, {}).get(day)
        if current is None or hours > current["hours"]:
            found[name][day] = {
                "hours": hours,
                "roster": _text(row.get("Roster cell")),
                "clock_out": _text(row.get("DAKA out")),
            }
    return found


def _overtime_note(day, record):
    parts = [f"{_day_label(day)} 加班 {_hour_text(record['hours'])}小時"]
    if record["roster"]:
        parts.append(f"更表 {record['roster']}")
    if record["clock_out"]:
        parts.append(f"下班 {record['clock_out']}")
    return "，".join(parts)


def _date_fact(day, record, short):
    """The late-day note. Four clock times go on the next line so the note can wrap."""
    parts = [_day_label(day)]
    if record["roster"]:
        parts.append(f"更表 {record['roster']}")
    if record["clock_in"]:
        parts.append(f"打卡 {record['clock_in']}")
    punches = record.get("punches")
    if punches:
        count = f"{punches}次"
        if short:
            count += "（平時 4 次）"
        parts.append(count)
    parts.append(f"{record['minutes']}分")
    line = " ".join(parts)
    if punches == 4 and record.get("log"):
        return f"{line}\n{record['log']}"
    return line


def person_late_table(days, hide_within_grace=False):
    """One row per late day: roster time, clock-in, and how many clocks DAKA has."""
    empty = pd.DataFrame(columns=_DAY_COLUMNS)
    if days is None or not len(days) or "Late" not in days.columns:
        return empty
    four = _usually_four(days)
    frame = days.copy()
    frame["_late"] = pd.to_numeric(frame["Late"], errors="coerce").fillna(0)
    frame = frame[frame["_late"] > (LATE_GRACE_MINUTES if hide_within_grace else 0)]
    if "Date" in frame.columns:
        frame = frame.sort_values("Date")
    rows = []
    for _, row in frame.iterrows():
        punches = _count(row.get("Punch count"))
        name = _text(row.get("Name"))
        short = name in four and punches is not None and punches < 4
        shown = ""
        if punches:
            shown = f"{punches}，平時 4" if short else str(punches)
        times = _split_log(row.get("Punch log")) if punches == 4 else ["", "", "", ""]
        rows.append({
            "日期": _iso(row.get("Date")),
            "更表時間": _text(row.get("Roster cell")),
            "上班打卡": _text(row.get("DAKA in")),
            "遲到": int(round(float(row["_late"]))),
            "打卡次數": shown,
            "第1次上班": times[0],
            "第1次下班": times[1],
            "第2次上班": times[2],
            "第2次下班": times[3],
        })
    if not rows:
        return empty
    return pd.DataFrame(rows, columns=_DAY_COLUMNS)


def late_summary(days, links, hide_within_grace=False):
    """One row per person. Days of 5 minutes or less can be left out."""
    empty = pd.DataFrame(columns=SUMMARY_COLUMNS)
    if days is None or not len(days) or "Name" not in days.columns or "Late" not in days.columns:
        return empty
    frame = days.copy()
    frame["_late"] = pd.to_numeric(frame["Late"], errors="coerce").fillna(0)
    frame = frame[frame["_late"] > 0]
    if hide_within_grace:
        frame = frame[frame["_late"] > LATE_GRACE_MINUTES]
    if not len(frame):
        return empty
    links = links or {}
    four = _usually_four(days)
    overtime = _overtime_by_name(days)
    buckets = {}
    for _, row in frame.iterrows():
        roster = _text(row.get("Name"))
        if not roster:
            continue
        link = links.get(roster) or {}
        number = _text(link.get("employee_no"))
        key = number or f"name:{roster}"
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "group": _text(link.get("group")),
                "employee_no": number,
                "name": _text(link.get("name")) or roster,
                "rosters": [],
                "days": {},
            }
            buckets[key] = bucket
        if roster not in bucket["rosters"]:
            bucket["rosters"].append(roster)
        if not bucket["group"] and _text(link.get("group")):
            bucket["group"] = _text(link.get("group"))
        day = _iso(row.get("Date"))
        if not day:
            continue
        minutes = int(round(float(row["_late"])))
        record = {
            "minutes": minutes,
            "roster": _text(row.get("Roster cell")),
            "clock_in": _text(row.get("DAKA in")),
            "punches": _count(row.get("Punch count")),
            "log": _text(row.get("Punch log")),
            "name": roster,
        }
        previous = bucket["days"].get(day)
        if previous is None or minutes >= previous["minutes"]:
            bucket["days"][day] = record
    rows = []
    for bucket in buckets.values():
        ordered = sorted(bucket["days"].items())
        if not ordered:
            continue
        values = [record["minutes"] for _day, record in ordered]
        over = sum(1 for minutes in values if minutes > LATE_GRACE_MINUTES)
        facts = []
        for day, record in ordered:
            short = record["name"] in four and record["punches"] is not None and record["punches"] < 4
            facts.append(_date_fact(day, record, short))
        extra = {}
        if bucket["group"] == _RETAIL:
            for roster in bucket["rosters"]:
                for day, record in overtime.get(roster, {}).items():
                    current = extra.get(day)
                    if current is None or record["hours"] > current["hours"]:
                        extra[day] = record
        extra_lines = [_overtime_note(day, record) for day, record in sorted(extra.items())]
        extra_hours = sum(record["hours"] for record in extra.values())
        rows.append({
            "group": bucket["group"],
            "group_label": GROUP_LABEL.get(bucket["group"], "未分類"),
            "employee_no": bucket["employee_no"],
            "name": bucket["name"],
            "times": len(values),
            "minutes": sum(values),
            "over_grace": over,
            "dates": "\n\n".join(facts),
            "affects_bonus": "影響勤工獎" if over and bucket["group"] in _BONUS_GROUPS else "",
            "ot_hours": extra_hours,
            "ot_dates": "\n\n".join(extra_lines),
            "roster_names": tuple(bucket["rosters"]),
        })
    rows.sort(key=lambda row: (-row["minutes"], row["group_label"], row["name"]))
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
