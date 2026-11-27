"""One line per person per date, using every roster and DAKA as the ground truth."""

import re
from collections import Counter
from datetime import date

import pandas as pd

SHIFT = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")
LEAVES = (
    ("無薪", "unpaid"),
    ("生日", "birthday"),
    ("病假", "sick"),
    ("年假", "annual"),
    ("休假", "rest"),
)
LEAVE_LABEL = {
    "unpaid": "無薪假",
    "birthday": "生日假",
    "sick": "病假",
    "annual": "年假",
    "rest": "休假",
}


def empty_summary():
    return {
        "roster_days": "",
        "days_worked": 0,
        "missing_days": 0,
        "missing_dates": "",
        "late_mins": 0,
        "late_dates": "",
        "early_mins": 0,
        "early_dates": "",
        "ot_hours": 0.0,
        "wrong_days": 0,
        "wrong_dates": "",
        "day_off_dates": "",
        "leave_text": "",
        "annual_dates": "",
        "sick_dates": "",
        "unpaid_dates": "",
        "rest_days": 0,
        "annual_days": 0,
        "sick_days": 0,
        "unpaid_days": 0,
        "birthday_days": 0,
        "rest_dates": "",
        "two_shift_dates": "",
        "no_shift_dates": "",
        "not_in_daka": False,
        "shops": "",
        "late_text": "",
        "early_text": "",
        "ot_dates": [],
        "absent_dates": "",
    }


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}( 00:00:00)?")


def _date(value):
    if isinstance(value, str) and _ISO_DAY.fullmatch(value):
        return value[:10]
    try:
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)[:10]


def _day_label(iso):
    year, month, day = iso.split("-")
    return f"{int(day)}/{int(month)}"


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


def _num(value):
    text = _text(value)
    if not text:
        return 0
    try:
        return float(text)
    except ValueError:
        return 0


def classify(roster):
    text = _text(roster)
    if not text:
        return "blank", ""
    if SHIFT.search(text):
        return "shift", text
    for word, kind in LEAVES:
        if word in text:
            return "leave", kind
    return "marker", text


def shop_code(shop):
    from payroll.core.settings import code_for_shop

    return code_for_shop(_text(shop))


def _place_ok(punch_code, codes):
    """A punch at a paired building still counts as the roster shop."""
    from payroll.core.settings import shares_site

    if not punch_code:
        return True
    if punch_code in codes:
        return True
    return any(shares_site(punch_code, code) for code in codes)


def _arrival_late(roster, clock_in):
    """Minutes after the roster start. A missing clock-out does not hide this."""
    match = SHIFT.search(_text(roster))
    if not match:
        return 0
    start = _minutes(match.group(0).split("-")[0])
    arrived = _minutes(clock_in)
    if start is None or arrived is None:
        return 0
    return max(0, arrived - start)


def _metrics(roster, clock_in, clock_out):
    """Same lateness and overtime steps as the attendance check, using DAKA times."""
    match = SHIFT.search(_text(roster))
    if not match:
        return 0, 0, 0.0, False
    start_text, end_text = match.group(0).split("-")
    start = _minutes(start_text)
    end = _minutes(end_text)
    arrived = _minutes(clock_in)
    left = _minutes(clock_out)
    if start is None or end is None or arrived is None or left is None:
        return 0, 0, 0.0, False
    if end <= start:
        end += 24 * 60
        if left <= start:
            left += 24 * 60
    late = max(0, arrived - start)
    early = 0
    left_very_early = False
    if left < end:
        gap = end - left
        if gap <= 60:
            early = gap
        else:
            left_very_early = True
    overtime = 0.0
    if left >= end and left - end >= 30:
        overtime = ((left - end) // 30) / 2
    return late, early, overtime, left_very_early


def memo_source(roster, clock_in, clock_out):
    """Why this day is in the OT memo. Blank when the day did not add hours."""
    _late, early, overtime, _left_very_early = _metrics(roster, clock_in, clock_out)
    parts = []
    if overtime:
        parts.append(f"加班 {_hour_label(overtime)}")
    if early:
        hours = ((int(early) + 29) // 30) * 0.5
        if hours:
            parts.append(f"已補 {_hour_label(hours)}")
    return "、".join(parts)


def _hour_label(hours):
    text = f"{float(hours):.1f}"
    return text[:-2] if text.endswith(".0") else text


def half_hour_units(clock_in, clock_out):
    """Hours from one clock-in to the matching clock-out, in steps of 0.5.

    07:00-16:30 is 9.5. A gap of 15 minutes or more rounds up to the next half hour.
    """
    start = _minutes(clock_in)
    end = _minutes(clock_out)
    if start is None or end is None:
        return None
    if end < start:
        end += 24 * 60
    if end == start:
        return None
    return ((end - start + 15) // 30) / 2


def scheduled_hours(roster_cell, overtime=0, early_minutes=0):
    """Roster length, plus overtime, minus early leave. An early clock-in does not add time.

    Overtime is already in half hours. Early leave is in minutes and is taken off
    in the same half-hour steps shown as 已補.
    """
    total = 0.0
    found = False
    for match in SHIFT.finditer(_text(roster_cell)):
        start, end = [part.strip() for part in match.group(0).split("-")]
        amount = half_hour_units(start, end)
        if amount:
            total += amount
            found = True
    if not found:
        return ""
    try:
        extra = float(overtime or 0)
    except (TypeError, ValueError):
        extra = 0.0
    try:
        early = int(float(early_minutes or 0))
    except (TypeError, ValueError):
        early = 0
    deduct = ((early + 29) // 30) * 0.5 if early > 0 else 0
    worked = total + extra - deduct
    if worked <= 0:
        return ""
    return _hour_label(worked)


def day_hours(roster_cell, overtime=0, early_minutes=0, clock_in="", clock_out="", status=""):
    """Roster length plus overtime minus early leave.

    A rest day has no roster length. A punch on that day is counted from the
    clock-in to the clock-out.
    """
    if "休息日有打卡" in _text(status):
        amount = half_hour_units(clock_in, clock_out)
        return _hour_label(amount) if amount else ""
    if "缺卡" in _text(status) or not _text(clock_in) or not _text(clock_out):
        return ""
    return scheduled_hours(roster_cell, overtime, early_minutes)


def _minutes(value):
    text = _text(value).replace("：", ":")
    found = re.search(r"(\d{1,2}):(\d{2})", text)
    if not found:
        return None
    return int(found.group(1)) * 60 + int(found.group(2))


def _join(dates):
    return "、".join(dates)


def _leave_when(label, roster):
    """12/11, or 12/11(AM) / 12/11(PM) when the roster marks half a day."""
    text = _text(roster)
    if re.search(r"上午|\bAM\b", text, re.I):
        return f"{label}(AM)"
    if re.search(r"下午|\bPM\b", text, re.I):
        return f"{label}(PM)"
    return label


def _shift_clock(roster, which):
    match = SHIFT.search(_text(roster))
    if not match:
        return ""
    start_text, end_text = [part.strip() for part in match.group(0).split("-")]
    return start_text if which == "start" else end_text


def _shift_start(row):
    return _minutes(_shift_clock(row.get("roster"), "start")) or 24 * 60


def _split_metrics(morning, afternoon, clock_in, clock_out):
    """Late against the morning start. Early leave and overtime against the afternoon end."""
    morning_end = _shift_clock(morning.get("roster"), "end")
    afternoon_start = _shift_clock(afternoon.get("roster"), "start")
    late, _early, _overtime, _very = _metrics(morning.get("roster"), clock_in, morning_end)
    _late, early, overtime, left_very_early = _metrics(afternoon.get("roster"), afternoon_start, clock_out)
    return late, early, overtime, left_very_early


def _open_shift(iso, name, assume_until):
    """A roster day that has not finished, so early pay can count the shift."""
    if not assume_until or name not in assume_until:
        return False
    last = assume_until[name]
    last_iso = last.isoformat() if hasattr(last, "isoformat") else str(last)[:10]
    return date.today().isoformat() <= str(iso)[:10] <= last_iso


def merge_days(facts, punches, assume_until=None):
    """Return a summary per roster name, and one evidence row per person per date.

    assume_until maps a roster name to a last working day. From today through
    that day, a shift with no complete punch counts as worked.
    """
    if facts is None or len(facts) == 0:
        return {}, pd.DataFrame()
    from payroll.attendance.daka import daka_names, punch_for
    from payroll.core.labels import STATUS, punch_label

    names_in_daka = daka_names(punches)
    grouped = {}
    for _, row in facts.iterrows():
        name = _text(row.get("name"))
        if not name:
            continue
        grouped.setdefault((name, _date(row.get("date"))), []).append(row)

    people = {}
    evidence = []
    import datetime as _dt
    today_iso = _dt.date.today().isoformat()
    for (name, date), rows in sorted(grouped.items()):
        person = people.setdefault(name, _fresh())
        punch = punch_for(punches, name, date)
        clock_in, clock_out = punch["in"], punch["out"]
        in_place = punch.get("in_place") or punch.get("place") or ""
        out_place = punch.get("out_place") or ""
        in_code = punch.get("in_code") or punch.get("code") or ""
        out_code = punch.get("out_code") or ""
        has_in, has_out = bool(clock_in), bool(clock_out)
        label = _day_label(date)
        described = []
        shifts = []
        leaves = []
        for row in rows:
            kind, detail = classify(row.get("roster"))
            shop = _text(row.get("shop"))
            described.append(f"{shop}: {_text(row.get('roster')) or '空白'}")
            if kind == "shift":
                shifts.append(row)
                person["assigned"][shop] += 1
            elif kind == "leave":
                leaves.append((row, detail))
                person["assigned"][shop] += 1
        two_shifts = len(shifts) >= 2
        jumped = False
        morning = afternoon = None
        if two_shifts:
            ordered = sorted(shifts, key=_shift_start)
            morning, afternoon = ordered[0], ordered[-1]
            morning_code = shop_code(morning.get("shop"))
            afternoon_code = shop_code(afternoon.get("shop"))
            jumped = bool(
                in_code and out_code and in_code != out_code
                and in_code == morning_code and out_code == afternoon_code
            )
            if not jumped:
                person["two_shift"].append(label)
                matched = [
                    row for row in shifts
                    if shop_code(row.get("shop")) in {in_code, punch.get("code")} and (in_code or punch.get("code"))
                ]
                chosen = matched[0] if matched else shifts[0]
            else:
                chosen = morning
        elif shifts:
            chosen = shifts[0]
        elif leaves:
            chosen = leaves[0][0]
        else:
            chosen = rows[0]
        kind, detail = classify(chosen.get("roster"))
        chosen_shop = _text(chosen.get("shop"))
        roster_cell = _text(chosen.get("roster"))
        if jumped:
            chosen_shop = f"{_text(morning.get('shop'))}、{_text(afternoon.get('shop'))}"
            roster_cell = f"{_text(morning.get('roster'))} / {_text(afternoon.get('roster'))}"
        late = early = overtime = 0
        leave_kind = ""
        if _open_shift(date, name, assume_until) and kind == "shift" and not (has_in and has_out):
            person["worked"] += 1
            person["worked_shops"][chosen_shop] += 1
            status = "先按更表"
        elif name not in names_in_daka:
            status = STATUS["not in DAKA"]
            person["not_in_daka"] = True
        elif kind == "shift" and has_in and has_out:
            if jumped:
                late, early, overtime, left_very_early = _split_metrics(morning, afternoon, clock_in, clock_out)
            elif two_shifts and in_code and out_code and in_code != out_code:
                late, early, overtime, left_very_early = _split_metrics(morning, afternoon, clock_in, clock_out)
            else:
                late, early, overtime, left_very_early = _metrics(chosen.get("roster"), clock_in, clock_out)
            if left_very_early:
                status = STATUS["missing clock-out"]
                person["missing"].append(punch_label(label, "out"))
            else:
                person["worked"] += 1
                person["worked_shops"][chosen_shop] += 1
                person["ot"] += overtime
                if overtime:
                    person["ot_dates"].append((label, overtime))
                bits = []
                if late:
                    bits.append(f"遲到 {int(late)} 分鐘")
                if early:
                    covered = ((int(early) + 29) // 30) * 0.5
                    bits.append(f"早退 {int(early)} 分鐘（已補 {_hour_label(covered)}）")
                elif overtime:
                    bits.append(f"加班 {_hour_label(overtime)}")
                status = "、".join(bits) if bits else STATUS["worked"]
            if late:
                person["late"] += late
                person["late_dates"].append(f"{label} {int(late)}分鐘")
            if early:
                person["early"] += early
                person["early_dates"].append(f"{label} {int(early)}分鐘")
            punch_code = in_code or punch.get("code") or ""
            shift_codes = {shop_code(row.get("shop")) for row in shifts} or {shop_code(chosen_shop)}
            mismatched = []
            if two_shifts and (in_code or out_code):
                if in_code and not _place_ok(in_code, shift_codes):
                    mismatched.append(label)
                if out_code and not _place_ok(out_code, shift_codes):
                    mismatched.append(label)
            elif int(_num(chosen.get("wrong_site"))) or (
                punch_code and shop_code(chosen_shop) and not _place_ok(punch_code, {shop_code(chosen_shop)})
            ):
                mismatched.append(label)
            if mismatched and not jumped:
                person["wrong"].append(label)
                if "異地" not in status:
                    status = f"{status}、異地打卡" if status else "異地打卡"
        elif kind == "shift" and str(date)[:10] > today_iso:
            status = "未到"
        elif kind == "shift" and not has_in and not has_out:
            status = STATUS["missing punch"]
            person["missing"].append(punch_label(label))
            person["absent_shifts"].append(label)
        elif kind == "shift" and not has_in:
            status = STATUS["missing clock-in"]
            person["missing"].append(punch_label(label, "in"))
        elif kind == "shift" and not has_out:
            roster_for_late = chosen.get("roster")
            if two_shifts and morning is not None:
                roster_for_late = morning.get("roster")
            late = _arrival_late(roster_for_late, clock_in)
            status = STATUS["missing clock-out"]
            person["missing"].append(punch_label(label, "out"))
            if late:
                person["late"] += late
                person["late_dates"].append(f"{label} {int(late)}分鐘")
                status = f"遲到 {int(late)} 分鐘、{status}"
        elif kind == "leave" and not has_in and not has_out:
            leave_kind = detail
            status = LEAVE_LABEL.get(detail, STATUS["leave"])
            person[detail] += 1
            source = next((item for item, kind in leaves if kind == detail), None)
            stamp = _leave_when(label, source.get("roster") if source is not None else "")
            if detail == "rest":
                person["rest_dates"].append(label)
            elif detail == "annual":
                person["annual_dates"].append(stamp)
            elif detail == "sick":
                person["sick_dates"].append(stamp)
            elif detail == "unpaid":
                person["unpaid_dates"].append(stamp)
        elif kind == "leave":
            status = STATUS["worked on day off"]
            person["worked"] += 1
            person["worked_shops"][chosen_shop] += 1
            person["day_off"].append(label)
        elif has_in or has_out:
            status = STATUS["punched with no shift"]
            person["no_shift"].append(label)
        else:
            status = STATUS["off"]
        if jumped:
            transfer = f"轉店（{_text(morning.get('shop'))}、{_text(afternoon.get('shop'))}）"
            status = f"{status}、{transfer}" if status else transfer
        elif two_shifts:
            status = f"{STATUS['two shifts']}；{status}"
        evidence.append({
            "Name": name,
            "Date": date,
            "Rosters": "; ".join(described),
            "Chosen shop": chosen_shop,
            "Roster cell": roster_cell,
            "DAKA in": clock_in,
            "DAKA out": clock_out,
            "DAKA place": in_place if not out_place or out_place == in_place else f"{in_place} → {out_place}",
            "DAKA in place": in_place,
            "DAKA out place": out_place,
            "Status": status,
            "Late": int(late) if late else 0,
            "Early": int(early) if early else 0,
            "OT": overtime or 0,
            "Leave kind": leave_kind,
        })
    summaries = {name: _finish(person) for name, person in people.items()}
    return summaries, pd.DataFrame(evidence)


def _fresh():
    return {
        "assigned": Counter(),
        "worked_shops": Counter(),
        "worked": 0,
        "missing": [],
        "late": 0,
        "late_dates": [],
        "early": 0,
        "early_dates": [],
        "ot": 0.0,
        "wrong": [],
        "day_off": [],
        "rest": 0,
        "annual": 0,
        "sick": 0,
        "unpaid": 0,
        "birthday": 0,
        "rest_dates": [],
        "annual_dates": [],
        "sick_dates": [],
        "unpaid_dates": [],
        "two_shift": [],
        "no_shift": [],
        "not_in_daka": False,
        "ot_dates": [],
        "absent_shifts": [],
    }


def _finish(person):
    if person["not_in_daka"]:
        person["missing"] = []
        person["late"] = 0
        person["late_dates"] = []
        person["early"] = 0
        person["early_dates"] = []
        person["ot"] = 0
        person["ot_dates"] = []
        person["absent_shifts"] = []
        person["wrong"] = []
        person["day_off"] = []
        person["no_shift"] = []
    assigned = [(shop, count) for shop, count in sorted(person["assigned"].items()) if count]
    leave_parts = []
    for kind, count in (
        ("rest", person["rest"]),
        ("annual", person["annual"]),
        ("sick", person["sick"]),
        ("unpaid", person["unpaid"]),
        ("birthday", person["birthday"]),
    ):
        if count:
            leave_parts.append(f"{LEAVE_LABEL[kind]} {count}")
    summary = empty_summary()
    summary.update({
        "roster_days": "、".join(f"{shop} {count}" for shop, count in assigned),
        "days_worked": person["worked"],
        "missing_days": len(person["missing"]),
        "missing_dates": _join(person["missing"]),
        "late_mins": person["late"],
        "late_dates": _join(person["late_dates"]),
        "late_text": _join(person["late_dates"]),
        "early_mins": person["early"],
        "early_dates": _join(person["early_dates"]),
        "early_text": _join(person["early_dates"]),
        "ot_hours": person["ot"],
        "ot_dates": list(person["ot_dates"]),
        "wrong_days": len(person["wrong"]),
        "wrong_dates": _join(person["wrong"]),
        "day_off_dates": _join(person["day_off"]),
        "leave_text": "、".join(leave_parts),
        "rest_days": person["rest"],
        "annual_days": person["annual"],
        "sick_days": person["sick"],
        "unpaid_days": person["unpaid"],
        "birthday_days": person["birthday"],
        "annual_dates": _join(person["annual_dates"]),
        "sick_dates": _join(person["sick_dates"]),
        "unpaid_dates": _join(person["unpaid_dates"]),
        "rest_dates": _join(person["rest_dates"]),
        "two_shift_dates": _join(person["two_shift"]),
        "no_shift_dates": _join(person["no_shift"]),
        "not_in_daka": person["not_in_daka"],
        "shops": ",".join(shop for shop, count in assigned),
        "assigned_shops": len(assigned),
        "absent_dates": _join(person["absent_shifts"]),
    })
    return summary


def problem_lines(summary):
    """Attendance problems for the Review filter. Pay decisions are added by payroll."""
    from payroll.core.labels import STATUS
    if not summary:
        return []
    if summary["not_in_daka"]:
        return [STATUS["not in DAKA"]]
    lines = []
    if summary["missing_dates"]:
        lines.append(f"缺卡 {summary['missing_dates']}")
    if summary["wrong_dates"]:
        lines.append(f"異地打卡 {summary['wrong_dates']}")
    if summary["day_off_dates"]:
        lines.append(f"休息日有打卡 {summary['day_off_dates']}")
    if summary["no_shift_dates"]:
        lines.append(f"無排班但有打卡 {summary['no_shift_dates']}")
    if summary["two_shift_dates"]:
        lines.append(f"兩份更表同日有更 {summary['two_shift_dates']}")
    if summary.get("assigned_shops", 0) >= 2:
        lines.append(f"出現在多於一份更表：{summary['roster_days']}")
    return lines
