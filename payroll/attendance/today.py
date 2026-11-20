"""One day of who should be at each shop, and the punches that actually happened.

Salary is not calculated. The attendance rules stay in payroll.attendance.days.
"""

from datetime import date, datetime

import pandas as pd

from payroll.core.config import ROSTER_COPY_DIR, ROSTER_SHEET_DIR, ROSTER_SOURCES, parse_month
from payroll.core.settings import locations as location_rows
from payroll.core.settings import punch_places
from payroll.attendance.days import SHIFT, classify, merge_days, shop_code
from payroll.attendance.daka import load_daka
from payroll.core.names import chinese
from payroll.attendance.rosters import _matches

LOCATIONS = location_rows()
PUNCH_PLACE = punch_places()


def location_for(shop):
    """Retail and production at the same site are different cards."""
    found = []
    for part in str(shop or "").split("、"):
        part = part.strip()
        for label, code in LOCATIONS:
            if part == code or part.startswith(code + "_") or part.startswith(code):
                if label not in found:
                    found.append(label)
    return found


def place_names(shop):
    found = location_for(shop)
    if found:
        return found
    code = shop_code(shop)
    label = PUNCH_PLACE.get(code) or PUNCH_PLACE.get(str(shop or "").strip())
    return [label] if label else []


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


def _cell_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except (TypeError, ValueError, OSError):
            return None
    return None


def _one_file(folder, file_name):
    matches = _matches(folder, file_name)
    if len(matches) == 1:
        return matches[0]
    return None


def google_sheets_present(day):
    """The live rosters are Google Sheet shortcuts. The app cannot read those cells."""
    info = parse_month(f"{day.year}-{day.month:02d}")
    root = ROSTER_SHEET_DIR
    found = 0
    for folder, pattern, _shop in ROSTER_SOURCES:
        file_name = pattern.format(year=info["year"], mon=info["month_token"])
        shortcut = root / folder / f"{file_name}.gsheet"
        if shortcut.exists():
            found += 1
    return found


def roster_files(day):
    """Excel copies for that month. The Drive copy is preferred, then the month folder."""
    info = parse_month(f"{day.year}-{day.month:02d}")
    found, missing = [], []
    for _folder, pattern, shop in ROSTER_SOURCES:
        file_name = pattern.format(year=info["year"], mon=info["month_token"])
        path = _one_file(ROSTER_COPY_DIR / shop, file_name)
        if path is None:
            path = _one_file(info["rosters"] / shop, file_name)
        if path is None:
            from payroll.core.history import archived_roster
            archive = archived_roster(info["year"], info["month"], shop)
            if archive is not None:
                path = _one_file(archive, file_name)
        if path is None:
            missing.append(file_name)
        else:
            found.append((shop, path, info["sheet"]))
    return info, found, missing


def facts_from_book(path, sheet, shop, day):
    """The roster cell for one date. Late and overtime are not decided here."""
    frame = pd.read_excel(path, sheet_name=sheet, header=None)
    records = frame.values.tolist()
    rows = []
    for index, row in enumerate(records):
        columns = [
            column for column, value in enumerate(row)
            if _cell_date(value) == day
        ]
        if not columns:
            continue
        nxt = records[index + 1] if index + 1 < len(records) else []
        if _text(nxt[0] if nxt else "") != "Name":
            continue
        for person in records[index + 2:]:
            name = _text(person[0] if person else "")
            if not name:
                break
            if name == "Name":
                continue
            for column in columns:
                if column >= len(person):
                    continue
                roster = _text(person[column])
                if not roster or roster in {"0", "0.0"}:
                    continue
                rows.append({
                    "shop": shop,
                    "name": name,
                    "date": day.isoformat(),
                    "roster": roster,
                })
    return rows


def _punch(name, when, punch):
    return {
        "Name": name,
        "Date": when,
        "Rosters": "",
        "Chosen shop": punch.get("in_code") or punch.get("code") or "",
        "Roster cell": "",
        "DAKA in": punch.get("in") or "",
        "DAKA out": punch.get("out") or "",
        "DAKA place": punch.get("place") or "",
        "DAKA in place": punch.get("in_place") or punch.get("place") or "",
        "DAKA out place": punch.get("out_place") or "",
        "Status": "無排班但有打卡",
        "Late": 0,
        "Early": 0,
        "OT": 0,
        "Leave kind": "",
    }


def _alias_punches(punches, roster_names):
    """Copy a punch onto the roster spelling when only the character form differs."""
    if not punches:
        return punches
    linked = {}
    for key in punches:
        if isinstance(key, tuple) and len(key) == 2:
            linked.setdefault(chinese(key[0]), []).append(key)
    names = set(punches.get("__names__", ()))
    for roster_name in roster_names:
        norm = chinese(roster_name)
        if not norm:
            continue
        keys = linked.get(norm, [])
        daka_names = {key[0] for key in keys}
        if not daka_names or roster_name in daka_names or len(daka_names) != 1:
            continue
        names.add(roster_name)
        for name, when in keys:
            punches[(roster_name, when)] = punches[(name, when)]
    punches["__names__"] = names
    return punches


def _with_unrostered(evidence, punches, day):
    stamp = day.isoformat()
    have = set(evidence["Name"].astype(str)) if len(evidence) else set()
    have_norm = {chinese(name) for name in have}
    extra = []
    for key, punch in punches.items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        name, when = key
        if when != stamp or str(name) in have or chinese(name) in have_norm:
            continue
        if not punch.get("in") and not punch.get("out"):
            continue
        extra.append(_punch(name, when, punch))
    if not extra:
        return evidence
    added = pd.DataFrame(extra)
    if not len(evidence):
        return added
    return pd.concat([evidence, added], ignore_index=True)


def load_day(day, punches=None, files=None):
    """Rows for one date, plus roster filenames that could not be opened.

    `punches` and `files` are for tests. The page leaves them empty.
    """
    info, found, missing = roster_files(day)
    if files is not None:
        found, missing = files, []
    facts = []
    for shop, path, sheet in found:
        try:
            facts.extend(facts_from_book(path, sheet, shop, day))
        except (OSError, ValueError, KeyError):
            missing.append(path.name)
    if punches is None:
        punches = {}
        if info["daka"].exists():
            try:
                punches = load_daka(info["daka"])
            except SystemExit:
                punches = {}
    frame = pd.DataFrame(facts)
    punches = _alias_punches(punches, [row["name"] for row in facts])
    _summaries, evidence = merge_days(frame, punches) if len(frame) else ({}, pd.DataFrame())
    evidence = _with_unrostered(evidence, punches, day)
    return evidence, missing


def expected(row):
    return classify(row.get("Roster cell"))[0] == "shift"


def _clocked_in(row):
    return bool(_text(row.get("DAKA in")))


def _clocked_out(row):
    return bool(_text(row.get("DAKA out")))


def _start_minutes(row):
    match = SHIFT.search(_text(row.get("Roster cell")))
    if not match:
        return None
    start = match.group(0).split("-")[0].strip().replace("：", ":")
    parts = start.split(":")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[0]) * 60 + int(parts[1])


def missed(row, day, now=None):
    """A person is absent only when the shift has started and they have not clocked in.

    Clock-in without clock-out means they are still at work. It is not a missed shift.
    """
    now = now or datetime.now()
    if not expected(row) or _clocked_in(row):
        return False
    if day > now.date():
        return False
    if day < now.date():
        return True
    start = _start_minutes(row)
    if start is None:
        return True
    return now.hour * 60 + now.minute >= start


def board_status(row, day, now=None):
    now = now or datetime.now()
    if expected(row) and _clocked_in(row) and not _clocked_out(row) and day == now.date():
        return "在工作"
    if expected(row) and not _clocked_in(row) and day == now.date() and not missed(row, day, now):
        return "未上班"
    return _text(row.get("Status"))


def for_board(frame, day, now=None):
    if frame is None or not len(frame):
        return frame
    shown = frame.copy()
    shown["Status"] = [board_status(row, day, now) for _, row in shown.iterrows()]
    return shown
