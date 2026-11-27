"""Pay one person who resigns before the rest of the month is finished.

The slip is made now. early_paid.xlsx is the mark that keeps the month-end
run from paying them again.
"""

import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from payroll.staff.staff import _as_date, _text

EARLY_NOTE = "已提前出糧，月結不再發放。"
COLUMNS = [
    "time", "user", "kind", "book", "employee_no", "staff_id", "name",
    "leave_date", "pay_date", "net", "slip",
]
_MONTHS = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def format_pay_date(value):
    return f"{value.day} {_MONTHS[value.month]} {value.year}"


def early_path(info):
    system = info.get("system") if isinstance(info, dict) else None
    if not system:
        return None
    return Path(system) / "early_paid.xlsx"


def load_early(info):
    path = early_path(info)
    if path is None or not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        frame = pd.read_excel(path, engine="openpyxl")
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit("讀不到提前出糧紀錄：early_paid.xlsx。請先關閉這個檔。") from error
    if frame is None or frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def early_keys(info):
    """Staff ids and employee numbers already paid early this month."""
    frame = load_early(info)
    ids = set()
    numbers = set()
    if frame.empty:
        return ids, numbers
    if "staff_id" in frame.columns:
        ids = {_text(value) for value in frame["staff_id"] if _text(value)}
    if "employee_no" in frame.columns:
        numbers = {_text(value) for value in frame["employee_no"] if _text(value)}
    return ids, numbers


def early_employee_nos(info):
    _ids, numbers = early_keys(info)
    return numbers


def latest_early(info):
    """The last early-pay row for each employee number."""
    found = {}
    for _, row in load_early(info).iterrows():
        number = _text(row.get("employee_no"))
        if number:
            found[number] = row
    return found


def issued_people(info):
    """People already paid early, including those not yet marked resigned."""
    found = []
    for number, row in latest_early(info).items():
        found.append({
            "kind": _text(row.get("kind")) or "full",
            "book": _text(row.get("book")) or "bg",
            "employee_no": number,
            "staff_id": _text(row.get("staff_id")),
            "name": _text(row.get("name")) or number,
            "leave_date": _as_date(row.get("leave_date")),
            "join_date": None,
        })
    found.sort(key=lambda person: (person["leave_date"] or date.min, person["name"]))
    return found


def early_cards(info):
    """Resignation cards, plus anyone whose early slip was already compiled."""
    people = month_leavers(info)
    seen = {person["employee_no"] for person in people}
    for person in issued_people(info):
        if person["employee_no"] not in seen:
            people.append(person)
            seen.add(person["employee_no"])
    return people


def include_in_month_pay(on_payroll, staff_id, employee_no, paid_ids, paid_numbers):
    """False once this person was paid early, so the month-end slips skip them."""
    if not on_payroll:
        return False
    if _text(staff_id) and _text(staff_id) in paid_ids:
        return False
    if _text(employee_no) and _text(employee_no) in paid_numbers:
        return False
    return True


def leaving_this_month(record, info):
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    left = _as_date(record.get("leave_date"))
    if left is None or left < start or left > end:
        return False
    return _text(record.get("status")) == "已離職"


def previous_allowance(info, staff_id):
    """The allowance paid on last month's draft, or None when that file is absent."""
    from payroll.core.config import parse_month
    import pandas as pd

    year, month = int(info["year"]), int(info["month"])
    if month == 1:
        key = f"{year - 1}-12"
    else:
        key = f"{year}-{month - 1:02d}"
    path = parse_month(key)["folder"] / "payroll_draft.xlsx"
    if not path.exists():
        return None
    wanted = _text(staff_id)
    try:
        book = pd.ExcelFile(path)
    except (OSError, ValueError):
        return None
    for sheet in book.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet)
        if "糧單編號" not in frame.columns or "津貼" not in frame.columns:
            continue
        hit = frame[frame["糧單編號"].map(_text) == wanted]
        if hit.empty:
            continue
        try:
            amount = float(hit.iloc[0]["津貼"])
        except (TypeError, ValueError):
            return None
        if amount != amount:
            return None
        return amount
    return None


_PRIOR_NOTES = ("本月離職", "本月入職", "未到最後工作日的更表")


def early_hold(row):
    """Amount problems for one early slip. Confirming the slip covers the rest.

    The month review page stays locked until new staff are finished, so this
    person cannot be approved there yet.
    """
    review = _text(row.get("review"))
    if "請選擇發放或不發放" in review:
        return "請先選擇勤工獎發放或不發放。"
    pending = _text(row.get("absence_pending"))
    if pending:
        return f"請先確認缺勤：{pending}。"
    return ""


def needs_approval(row, prior=False):
    """The same gate as a normal slip: approve this person before paying them.

    A calculation made before the last day always carries a short note. That
    note alone does not block the slip. Real problems still do.
    """
    review = _text(row.get("review"))
    if prior and review:
        kept = [part for part in review.split("；") if part and not part.startswith(_PRIOR_NOTES)]
        review = "；".join(kept)
    if "請選擇發放或不發放" in review:
        return "請先在審核選擇勤工獎發放或不發放。"
    if _text(row.get("absence_pending")):
        return "請先在審核確認缺勤。"
    approved = _text(row.get("approved")).upper() in {"Y", "是"}
    if not approved and review and review.lower() != "nan":
        return "請先在審核批准這個人。"
    suggest = _text(row.get("ot_suggest"))
    saved = _text(row.get("ot_text"))
    if suggest and suggest.lower() != "nan" and (not saved or saved.lower() == "nan") and not approved:
        return "請先在審核批准這個人。"
    return ""


def _current_record(staff, employee_no, info):
    from payroll.staff.staff import employed_window
    rows = staff[staff["employee_no"].map(_text) == employee_no]
    for _, record in rows.iterrows():
        if _text(record.get("status")) == "已離職":
            continue
        if employed_window(record, info) is not None:
            return record
    return None


def open_people(info):
    """Employed people who can be calculated before the resignation is written."""
    from payroll.core.excel_io import read_table
    from payroll.pay.run import allowed_books
    from payroll.staff.staff import contract_end_date, load_staff, pay_table_path

    staff = load_staff()
    resigned = {person["employee_no"] for person in month_leavers(info)}
    paid = early_employee_nos(info)
    found = []
    seen = set()
    for book in allowed_books(("bg", "md", "admin")):
        table = read_table(pay_table_path(book))
        if table is None or "employee_no" not in getattr(table, "columns", []):
            continue
        for _, person in table.iterrows():
            number = _text(person.get("employee_no"))
            if not number or number in seen or number in resigned or number in paid:
                continue
            record = _current_record(staff, number, info)
            if record is None:
                continue
            seen.add(number)
            found.append({
                "kind": "full",
                "book": book,
                "employee_no": number,
                "staff_id": _text(person.get("staff_id")),
                "name": _text(person.get("slip_name")) or _text(record.get("name_zh")) or number,
                "leave_date": None,
                "join_date": _as_date(record.get("join_date")),
                "contract_end": contract_end_date(record),
            })
    from payroll.pay.part_time import pt_company
    if "part_time" in staff.columns:
        for _, record in staff.iterrows():
            if not bool(record.get("part_time")):
                continue
            number = _text(record.get("employee_no"))
            if not number or number in seen or number in resigned or number in paid:
                continue
            if _current_record(staff, number, info) is None:
                continue
            seen.add(number)
            found.append({
                "kind": "part",
                "book": pt_company(record),
                "employee_no": number,
                "staff_id": "",
                "name": _text(record.get("name_zh")) or _text(record.get("name_en")) or number,
                "leave_date": None,
                "join_date": _as_date(record.get("join_date")),
                "contract_end": None,
            })
    found.sort(key=lambda person: person["name"])
    return found


def _resolve(info, employee_no, book, kind, last_day):
    person = None
    try:
        person = _find(info, employee_no, book, kind)
    except SystemExit:
        person = None
    if person is None:
        matches = [
            item for item in open_people(info)
            if item["employee_no"] == _text(employee_no)
            and (not book or item["book"] == book)
            and (not kind or item["kind"] == kind)
        ]
        person = matches[0] if matches else None
    if person is None:
        raise SystemExit("這個人不是這個月可以出糧的同事，或不在你可出的糧單。")
    person = dict(person)
    if last_day is not None:
        person["leave_date"] = last_day
    if person.get("leave_date") is None:
        raise SystemExit("請選最後工作日。")
    return person


def leaver_draft(info, book, plan):
    """One draft for a book, each person in plan cut off on their own last day."""
    from payroll.core.config import book_info
    from payroll.pay.run import _draft_from_facts

    booked = book_info(info, book)
    booked["leave_until"] = dict(plan)
    return booked, _draft_from_facts(booked)


def leaver_row(draft, person, allow_closed=False):
    if draft is None or len(draft) == 0:
        raise SystemExit("請先核對出勤，才能計算這個人的薪金。")
    hit = draft[draft["employee_no"].map(_text) == person["employee_no"]]
    staff_id = _text(person.get("staff_id"))
    if staff_id and "staff_id" in hit.columns:
        narrowed = hit[hit["staff_id"].map(_text) == staff_id]
        if len(narrowed):
            hit = narrowed
    if hit.empty:
        raise SystemExit("這個人不在本月糧單。")
    row = hit.iloc[0]
    if not allow_closed and not bool(row.get("pay_this")):
        raise SystemExit("這個人本月不發薪。")
    return row


def _full_calculation(info, person, allow_closed=False):
    booked, draft = leaver_draft(info, person["book"], {person["employee_no"]: person["leave_date"]})
    return booked, draft, leaver_row(draft, person, allow_closed)


def _part_calculation(info, person):
    from payroll.pay.part_time import build_pt, clip_days
    from payroll.staff.staff import load_staff

    rows = build_pt(info, load_staff())
    row = next((item for item in rows if item["employee_no"] == person["employee_no"]), None)
    if row is None:
        raise SystemExit("這個人不在本月兼職糧單。")
    if row["pay_this"] != "Y":
        raise SystemExit("這個人本月不發薪。")
    clipped = clip_days(row, person["leave_date"], row, info)
    if float(clipped["total_hours"]) <= 0:
        raise SystemExit("這個人到離職日沒有工時。請先核對出勤。")
    return clipped, row


def preview_early(info, employee_no, last_day, book=None, kind=None):
    """The calculated row for a chosen last day, before the payment is issued."""
    person = _resolve(info, employee_no, book, kind, last_day)
    if person["kind"] == "part":
        clipped, _row = _part_calculation(info, person)
        return person, None, clipped, ""
    _booked, _draft, row = _full_calculation(info, person)
    return person, row, None, early_hold(row)


def quote_early(info, employee_no, last_day, book=None, kind=None):
    """The amount for a last day, including roster days that have not been punched yet."""
    person = _resolve(info, employee_no, book, kind, last_day)
    prior = person["leave_date"] >= date.today()
    if person["kind"] == "part":
        clipped, _row = _part_calculation(info, person)
        net = clipped["transfer"]
        period = ""
        reason = ""
    else:
        _booked, _draft, row = _full_calculation(info, person)
        net = row.get("net")
        period = _text(row.get("period"))
        reason = early_hold(row)
    try:
        amount = float(net)
    except (TypeError, ValueError):
        amount = 0.0
    return {
        "key": info.get("key", ""),
        "employee_no": person["employee_no"],
        "book": person["book"],
        "kind": person["kind"],
        "name": person["name"],
        "last": person["leave_date"].isoformat(),
        "net": amount,
        "period": period,
        "reason": reason,
        "prior": prior,
    }


def _match_leaver(staff, employee_no, info):
    rows = staff[staff["employee_no"].map(_text) == employee_no]
    chosen = None
    for _, record in rows.iterrows():
        if leaving_this_month(record, info):
            chosen = record
    return chosen


def month_leavers(info):
    """People who left during this month and can be paid before month-end."""
    from payroll.core.excel_io import read_table
    from payroll.pay.run import allowed_books
    from payroll.staff.staff import load_staff, pay_table_path

    staff = load_staff()
    found = []
    seen = set()
    for book in allowed_books(("bg", "md", "admin")):
        table = read_table(pay_table_path(book))
        if table is None or "employee_no" not in getattr(table, "columns", []):
            continue
        for _, person in table.iterrows():
            number = _text(person.get("employee_no"))
            if not number or number in seen:
                continue
            record = _match_leaver(staff, number, info)
            if record is None:
                continue
            seen.add(number)
            found.append({
                "kind": "full",
                "book": book,
                "employee_no": number,
                "staff_id": _text(person.get("staff_id")),
                "name": _text(person.get("slip_name")) or _text(record.get("name_zh")) or number,
                "leave_date": _as_date(record.get("leave_date")),
                "join_date": _as_date(record.get("join_date")),
            })
    from payroll.pay.part_time import pt_company
    if "part_time" in staff.columns:
        for _, record in staff.iterrows():
            if not bool(record.get("part_time")):
                continue
            number = _text(record.get("employee_no"))
            if not number or number in seen or not leaving_this_month(record, info):
                continue
            seen.add(number)
            found.append({
                "kind": "part",
                "book": pt_company(record),
                "employee_no": number,
                "staff_id": "",
                "name": _text(record.get("name_zh")) or _text(record.get("name_en")) or number,
                "leave_date": _as_date(record.get("leave_date")),
                "join_date": _as_date(record.get("join_date")),
            })
    found.sort(key=lambda person: (person["leave_date"], person["name"]))
    return found


def _already(info, person):
    paid_ids, paid_numbers = early_keys(info)
    if person["employee_no"] in paid_numbers:
        return True
    staff_id = _text(person.get("staff_id"))
    return bool(staff_id) and staff_id in paid_ids


def revise_issued_net(info, employee_no, net):
    """Replace the recorded amount after an issued slip is edited. It is still one payment."""
    from payroll.core.excel_io import save_excel

    frame = load_early(info)
    if frame.empty or "employee_no" not in frame.columns:
        return
    number = _text(employee_no)
    matches = [index for index, value in frame["employee_no"].items() if _text(value) == number]
    if not matches:
        return
    try:
        amount = float(net)
    except (TypeError, ValueError):
        return
    if pd.isna(amount):
        return
    frame.at[matches[-1], "net"] = amount
    save_excel(early_path(info), frame.reindex(columns=COLUMNS))


def record_early(info, person, pay_date, net, slip):
    if _already(info, person):
        raise SystemExit("已經提前出糧，不會再發一次。")
    from payroll.core.excel_io import save_excel
    from payroll.core.settings import actor

    frame = load_early(info)
    left = person.get("leave_date")
    left_text = left.isoformat() if hasattr(left, "isoformat") else _text(left)
    pay_text = format_pay_date(pay_date) if hasattr(pay_date, "day") else _text(pay_date)
    try:
        amount = float(net)
    except (TypeError, ValueError):
        amount = 0.0
    if pd.isna(amount):
        amount = 0.0
    row = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": actor(),
        "kind": person.get("kind", ""),
        "book": person.get("book", ""),
        "employee_no": person["employee_no"],
        "staff_id": _text(person.get("staff_id")),
        "name": person.get("name", ""),
        "leave_date": left_text,
        "pay_date": pay_text,
        "net": amount,
        "slip": str(slip),
    }
    frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    save_excel(early_path(info), frame.reindex(columns=COLUMNS))


def _find(info, employee_no, book, kind):
    number = _text(employee_no)
    matches = []
    for person in month_leavers(info):
        if person["employee_no"] != number:
            continue
        if book and person["book"] != book:
            continue
        if kind and person["kind"] != kind:
            continue
        matches.append(person)
    if not matches:
        raise SystemExit("這個人不是這個月離職的同事，或不在你可出的糧單。")
    return matches[0]


def _safe_name(name, fallback):
    cleaned = re.sub(r"[<>:\"/\\|?*']", "", _text(name)).strip()
    return cleaned or fallback


def _issue_full(info, person, pay_date):
    booked, draft, row = _full_calculation(info, person)
    reason = early_hold(row)
    if reason:
        raise SystemExit(reason)
    staff_id = _text(row.get("staff_id"))
    if not staff_id:
        raise SystemExit("這個人沒有糧單編號，不能製作糧單。")
    booked["pay_date_override"] = format_pay_date(pay_date)
    if person["book"] == "admin":
        from payroll.documents.slips_admin import write_person_slip
        path = write_person_slip(booked, draft, staff_id)
    else:
        path = _shop_pdf(booked, row)
    return path, row.get("net")


def _shop_pdf(info, row):
    """Shop and production slips use the same PDF as an office slip."""
    from payroll.documents.slip_pdf import write_office_pdf
    from payroll.staff.staff import read_batch

    staff_id = _text(row.get("staff_id"))
    name = _text(row.get("slip_name")).split()[0] or staff_id
    batch = read_batch(info) or staff_id.split("-")[0]
    suffix = staff_id.split("-")[-1]
    folder = Path(info["output"]) / "個別"
    folder.mkdir(parents=True, exist_ok=True)
    return write_office_pdf(folder / f"#{batch}_{suffix}_{_safe_name(name, staff_id)}.pdf", row, info)


def _issue_part(info, person):
    from payroll.pay.part_time import pt_reference, summary_book

    clipped, row = _part_calculation(info, person)
    data = summary_book(info, person["book"], [clipped], pt_reference(info, person["book"]))
    folder = Path(info["output"]) / "個別"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"PT_{person['employee_no']}_{_safe_name(person['name'], person['employee_no'])}.xlsx"
    path.write_bytes(data)
    return path, clipped["transfer"], row


def _mark_part_unpaid(info, row):
    from payroll.pay.part_time import save_pt_lines
    save_pt_lines(info, [{
        "employee_no": row["employee_no"],
        "rate": row["rate"],
        "scheme": row["scheme"],
        "extra_hours": row["extra_hours"],
        "extra_note": row.get("extra_note", ""),
        "bank": row.get("bank", ""),
        "account": row.get("account", ""),
        "pay_this": "N",
    }])


def issue_early(info, employee_no, pay_date, book=None, kind=None, last_day=None):
    """Make one person's slip now and record it so month-end skips them.

    last_day can be today or later. Shifts up to that day that have not been
    punched yet are counted from the roster.
    """
    from app.lock import ensure_owner
    from payroll.core.history import is_issued
    from payroll.pay.review import log_changes

    ensure_owner(info)
    if is_issued(info["key"]):
        raise SystemExit("這個月已經出糧，不能再提前發薪。")
    if pay_date is None:
        raise SystemExit("請選出糧日期。")
    person = _resolve(info, employee_no, book, kind, last_day)
    if _already(info, person):
        raise SystemExit("已經提前出糧，不會再發一次。")
    part_row = None
    if person["kind"] == "part":
        path, net, part_row = _issue_part(info, person)
    else:
        path, net = _issue_full(info, person, pay_date)
    record_early(info, person, pay_date, net, path)
    if part_row is not None:
        try:
            _mark_part_unpaid(info, part_row)
        except SystemExit as error:
            raise SystemExit(
                "糧單已做好。兼職表未能改成不出糧，請在兼職薪金把這個人設為不出糧。"
            ) from error
    log_changes(info.get("key", ""), person["employee_no"], [("early_pay", "", format_pay_date(pay_date))])
    return path
