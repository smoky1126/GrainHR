"""Who is employed, from the staff file, and what they are paid, from the pay table."""

import os
import re
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from payroll.core.config import STAFF_RECORD_DIR, book_info, home, parse_month
from payroll.core.names import chinese

warnings.filterwarnings("ignore", message="Data Validation extension")

def pay_table_path(book="bg"):
    suffix = "" if book == "bg" else f"_{book}"
    return home() / "data" / f"pay_table{suffix}.xlsx"


# Office theme colours. Grey rows in the staff file are accent3 or light2, tinted.
_THEME = [
    "000000", "FFFFFF", "44546A", "E7E6E6", "4472C4",
    "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
]
STAFF_SHEETS = ("BG & MD", "內地勞工")

PAY_COLUMNS = [
    "employee_no", "staff_id", "slip_name", "roster_name", "basic_salary", "scheme",
    "rent_rate", "rent_base", "rent_amount", "water", "electricity", "bonus_eligible", "rest_days_month",
    "allowance_desc", "allowance_amount", "transport_amount", "health_amount", "allowance_note", "allowance_section",
]


def _text(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


_STAFF_STAMP = re.compile(r"^Staff_info_(\d{8}|\d{6})$")


def staff_file_day(path):
    """Date stamped in Staff_info_YYYYMMDD, or the first of the month for YYYYMM."""
    match = _STAFF_STAMP.match(Path(path).stem)
    if not match:
        return None
    raw = match.group(1)
    try:
        if len(raw) == 8:
            return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
        return date(int(raw[0:4]), int(raw[4:6]), 1)
    except ValueError:
        return None


def staff_version_path(folder, day=None):
    day = day or date.today()
    return Path(folder) / f"Staff_info_{day:%Y%m%d}.xlsx"


def pick_staff_file(files):
    ranked = []
    for path in files:
        path = Path(path)
        if path.name.startswith("~$"):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        ranked.append(((staff_file_day(path) or date.min, mtime), path))
    if not ranked:
        raise SystemExit("沒有 Staff_info_*.xlsx")
    return max(ranked)[1]


def latest_staff_file():
    override = os.environ.get("PAYROLL_STAFF", "").strip()
    if override:
        path = Path(override)
        if not path.exists():
            raise SystemExit(f"找不到員工檔：{path}")
        return path
    if not STAFF_RECORD_DIR.exists():
        raise SystemExit(f"找不到員工資料夾：{STAFF_RECORD_DIR}")

    def build():
        files = list(STAFF_RECORD_DIR.glob("Staff_info_*.xlsx"))
        if not files:
            raise SystemExit(f"{STAFF_RECORD_DIR} 沒有 Staff_info_*.xlsx")
        return pick_staff_file(files)

    from payroll.core.listings import remember
    return remember(("staff-file", str(STAFF_RECORD_DIR)), STAFF_RECORD_DIR, build)


def _header_row(raw):
    for index, row in raw.iterrows():
        for value in row:
            if str(value).strip().startswith("員工編號"):
                return index
    raise SystemExit("員工檔沒有「員工編號」標題。")


def _read_sheet(path, sheet):
    from payroll.core.excel_io import read_excel
    raw = read_excel(path, sheet_name=sheet, header=None)
    header_index = _header_row(raw)
    headers = []
    seen = {}
    for value in raw.iloc[header_index]:
        name = str(value).strip().rstrip("*")
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    data = raw.iloc[header_index + 1:].copy()
    data.columns = headers
    data = data.dropna(how="all")
    join_column = "入職日期" if "入職日期" in data.columns else "到職日期"
    keep = ["員工編號", "員工名稱", "中文姓名", "英文姓名", "職位", "部門",
            join_column, "離職日期", "僱傭狀況", "就業形式",
            "性別", "出生日期", "婚姻狀況", "住址", "身份證號碼", "手提電話號碼",
            "銀行賬號", "銀行名稱",
            "緊急聯絡人", "緊急聯絡人關係", "緊急聯絡人電話號碼",
            "緊急聯絡人_1", "緊急聯絡人關係_1", "緊急聯絡人電話號碼_1",
            "合約完結日期", "合約編號", "批准信地址"]
    for column in keep:
        if column not in data.columns:
            data[column] = "" if column != "離職日期" else pd.NaT
    out = data[keep].copy()
    out = out.rename(columns={join_column: "入職日期"})
    out["sheet"] = sheet
    return out


_OPTION_COLUMNS = {
    0: "性別",
    1: "銀行名稱",
    3: "部門",
    5: "就業形式",
    6: "僱傭狀況",
    7: "婚姻狀況",
}


def staff_options(path=None):
    """Dropdown lists on Sheet2, in the same order as the staff file."""
    from payroll.core.excel_io import read_excel
    path = Path(path) if path else latest_staff_file()
    raw = read_excel(path, sheet_name="Sheet2", header=None)
    options = {name: [] for name in _OPTION_COLUMNS.values()}
    for _, row in raw.iterrows():
        for index, name in _OPTION_COLUMNS.items():
            if index >= len(row):
                continue
            text = _text(row.iloc[index])
            if text and text not in options[name]:
                options[name].append(text)
    return options


def next_employee_no(staff, prefix):
    """The next free number for one staff-number prefix from company.toml."""
    prefix = _text(prefix).upper()
    used = []
    for value in staff["employee_no"]:
        text = _text(value).upper()
        if text.startswith(prefix) and text[len(prefix):].isdigit():
            used.append(int(text[len(prefix):]))
    return f"{prefix}{(max(used) if used else 0) + 1:03d}"


_loaded = {}
_grey = {}


def clear_staff_cache():
    _loaded.clear()
    _grey.clear()
    from payroll.core.excel_io import clear_reads
    clear_reads()


def _copy_staff(frame):
    copied = frame.copy()
    copied.attrs = dict(getattr(frame, "attrs", {}))
    return copied


def load_staff(path=None):
    from payroll.core.excel_io import file_stamp
    given = path is not None
    path = Path(path) if given else latest_staff_file()

    def _stamp(target):
        try:
            return file_stamp(target)
        except OSError:
            return None

    stamp = _stamp(path)
    if stamp is None and not given:
        from payroll.core.listings import clear_listings
        clear_listings()
        path = latest_staff_file()
        stamp = _stamp(path)
    if stamp is None:
        raise SystemExit(f"找不到員工檔：{Path(path).name}。請稍後再打開這一頁。")
    key = str(path.resolve()) if path.exists() else str(path)
    found = _loaded.get(key)
    if stamp and found and found[0] == stamp:
        return _copy_staff(found[1])
    try:
        frames = [_read_sheet(path, sheet) for sheet in STAFF_SHEETS]
    except PermissionError:
        raise SystemExit(f"請先儲存並關閉 {path.name}，然後再執行。")
    staff = pd.concat(frames, ignore_index=True)
    staff["employee_no"] = staff["員工編號"].map(_text)
    staff = staff[staff["employee_no"] != ""]
    staff["name_zh"] = staff["中文姓名"].map(_text)
    staff["name_en"] = staff["英文姓名"].map(_text)
    staff["roster_hint"] = staff["員工名稱"].map(_text)
    staff["position"] = staff["職位"].map(_text)
    staff["department"] = staff["部門"].map(_text)
    staff["join_date"] = staff["入職日期"]
    staff["leave_date"] = staff["離職日期"]
    staff["status"] = staff["僱傭狀況"].map(_text)
    staff["employment"] = staff["就業形式"].map(_text)
    staff["gender"] = staff["性別"].map(_text)
    staff["birth_date"] = staff["出生日期"]
    staff["marital"] = staff["婚姻狀況"].map(_text)
    staff["address"] = staff["住址"].map(_text)
    staff["hkid"] = staff["身份證號碼"].map(_text)
    staff["phone"] = staff["手提電話號碼"].map(_text)
    staff["bank_account"] = staff["銀行賬號"].map(_text)
    staff["bank_name"] = staff["銀行名稱"].map(_text)
    staff["emergency_name"] = staff["緊急聯絡人"].map(_text)
    staff["emergency_relation"] = staff["緊急聯絡人關係"].map(_text)
    staff["emergency_phone"] = staff["緊急聯絡人電話號碼"].map(_text)
    staff["emergency_name_2"] = staff["緊急聯絡人_1"].map(_text)
    staff["emergency_relation_2"] = staff["緊急聯絡人關係_1"].map(_text)
    staff["emergency_phone_2"] = staff["緊急聯絡人電話號碼_1"].map(_text)
    staff["contract_end"] = staff["合約完結日期"]
    staff["contract_no"] = staff["合約編號"].map(_text)
    staff["permit_address"] = staff["批准信地址"].map(_text)
    staff["active"] = staff["status"].eq("在職")
    staff["part_time"] = staff["employment"].str.contains("兼職", na=False)
    staff["_zh"] = staff["name_zh"].map(chinese)
    duplicates = sorted(
        staff.loc[staff["active"], "employee_no"]
        .value_counts()
        .loc[lambda counts: counts > 1]
        .index
    )
    staff.attrs["source"] = str(path)
    staff.attrs["duplicate_ids"] = duplicates
    staff.attrs["grey_active"] = grey_but_employed(path)
    if stamp:
        _loaded[key] = (stamp, staff)
    return _copy_staff(staff)


def _as_date(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()
        except Exception:
            pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "nat", "none"}:
        return None
    try:
        parsed = pd.to_datetime(text)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def contract_end_date(record):
    """Last working day of a mainland contract: the day before 合約完結日期.

    The date in the staff file is the anniversary of the start date, so a
    contract from 28/11/2024 to 28/11/2026 is paid to 27/11/2026.
    """
    if _text(record.get("sheet")) != "內地勞工":
        return None
    ends = _as_date(record.get("contract_end"))
    return ends - timedelta(days=1) if ends is not None else None


def employed_window(record, info):
    """First and last day this person is employed in the month, or None."""
    start = date(info["year"], info["month"], 1)
    end = date(info["year"], info["month"], info["days"])
    joined = _as_date(record.get("join_date"))
    left = _as_date(record.get("leave_date"))
    contract = contract_end_date(record)
    ends = [day for day in (left, contract) if day is not None]
    cutoff = min(ends) if ends else None
    if cutoff is not None and cutoff < start:
        return None
    if joined is not None and joined > end:
        return None
    # A blank status is not "left". Only 已離職, with no date, drops the month.
    if cutoff is None and _text(record.get("status")) not in {"", "在職"}:
        return None
    first = start if joined is None or joined < start else joined
    last = end if cutoff is None or cutoff > end else cutoff
    if first > last:
        return None
    return first, last


def employed_in(staff, info):
    flags = [employed_window(record, info) is not None for _, record in staff.iterrows()]
    return pd.Series(flags, index=staff.index)


def _tint(hex_color, tint):
    tint = float(tint or 0)
    channels = []
    for index in (0, 2, 4):
        value = int(hex_color[index:index + 2], 16) / 255
        if tint < 0:
            value = value * (1 + tint)
        else:
            value = value * (1 - tint) + tint
        channels.append(round(value * 255))
    return channels


def _is_grey(color):
    if color is None or not color.type:
        return False
    if color.type == "rgb":
        rgb = str(color.rgb or "")
        if len(rgb) == 8:
            rgb = rgb[2:]
        if len(rgb) != 6:
            return False
        base = rgb
    elif color.type == "theme" and color.theme is not None and 0 <= int(color.theme) < len(_THEME):
        base = _THEME[int(color.theme)]
    else:
        return False
    red, green, blue = _tint(base, getattr(color, "tint", 0) or 0)
    if max(red, green, blue) - min(red, green, blue) > 24:
        return False
    average = (red + green + blue) / 3
    return 90 <= average <= 235


def grey_but_employed(path=None):
    """在職 rows painted with the same solid grey already used on 已離職 rows."""
    from openpyxl import load_workbook
    from payroll.core.excel_io import file_stamp

    path = Path(path) if path else latest_staff_file()
    try:
        stamp = file_stamp(path)
    except OSError:
        stamp = None
    cache_key = str(path.resolve()) if path.exists() else str(path)
    cached = _grey.get(cache_key)
    if stamp and cached and cached[0] == stamp:
        return list(cached[1])
    book = load_workbook(path, data_only=True)
    found = []
    for sheet in book.worksheets:
        header = None
        for row in sheet.iter_rows(min_row=1, max_row=15):
            if any(str(cell.value or "").strip().startswith("員工編號") for cell in row):
                header = {cell.column: str(cell.value or "").strip().rstrip("*") for cell in row}
                header_row = row[0].row
                break
        if header is None:
            continue
        columns = {name: column for column, name in header.items() if name}
        status_col = columns.get("僱傭狀況")
        number_col = columns.get("員工編號")
        name_col = columns.get("中文姓名")
        if not status_col or not number_col:
            continue
        body = list(sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row))
        leave_grey = set()
        for row in body:
            if _text(row[status_col - 1].value) != "已離職":
                continue
            for key, count in _row_grey_counts(row).items():
                if count >= 2:
                    leave_grey.add(key)
        if not leave_grey:
            continue
        for row in body:
            number = _text(row[number_col - 1].value)
            if not number or _text(row[status_col - 1].value) != "在職":
                continue
            counts = _row_grey_counts(row)
            if any(counts.get(key, 0) >= 2 for key in leave_grey):
                name = _text(row[name_col - 1].value) if name_col else ""
                found.append({"employee_no": number, "name": name or number})
    book.close()
    if stamp:
        _grey[cache_key] = (stamp, list(found))
    return list(found)


def _fill_key(color):
    if color is None or not color.type:
        return None
    if color.type == "rgb":
        rgb = str(color.rgb or "")
        if len(rgb) == 8:
            rgb = rgb[2:]
        return ("rgb", rgb.upper()) if len(rgb) == 6 else None
    if color.type == "theme" and color.theme is not None:
        return ("theme", int(color.theme), round(float(getattr(color, "tint", 0) or 0), 2))
    return None


def _row_grey_counts(row):
    """How many cells in the row use each grey. One cell is not a greyed-out row."""
    counts = {}
    for cell in row[:20]:
        fill = cell.fill
        if fill is None or not fill.fill_type or not _is_grey(fill.fgColor):
            continue
        key = _fill_key(fill.fgColor)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


_paid_cache = {"stamp": None, "numbers": frozenset()}


def paid_numbers():
    """Employee numbers already on any payroll."""
    from payroll.core.excel_io import file_stamp
    stamps = []
    paths = []
    for book in ("bg", "md", "admin"):
        path = pay_table_path(book)
        paths.append(path)
        try:
            stamps.append(file_stamp(path))
        except OSError:
            stamps.append(None)
    stamp = tuple(stamps)
    if stamp == _paid_cache["stamp"]:
        return set(_paid_cache["numbers"])
    numbers = set()
    for path, found in zip(paths, stamps):
        if found is None:
            continue
        table = pd.read_excel(path, dtype={"employee_no": str})
        if "employee_no" not in table.columns:
            continue
        numbers.update(_text(value) for value in table["employee_no"])
    numbers.discard("")
    _paid_cache["stamp"] = stamp
    _paid_cache["numbers"] = frozenset(numbers)
    return numbers


def _meta_text(meta, *names):
    if meta is None or meta.empty:
        return ""
    row = meta.iloc[0]
    for name in names:
        if name not in meta.columns:
            continue
        text = _text(row[name])
        if text.lower() != "nan":
            return text
    return ""


_meta_cache = {}


def _meta_frame(path):
    from payroll.core.excel_io import file_stamp
    try:
        stamp = file_stamp(path)
    except OSError:
        return None
    found = _meta_cache.get(str(path))
    if found and found[0] == stamp:
        return found[1]
    meta = pd.read_excel(path, sheet_name="meta")
    _meta_cache[str(path)] = (stamp, meta)
    return meta


def read_refs(info):
    """Salary and allowance autopay numbers for this payroll."""
    path = info["adjustments"]
    if not path.exists():
        return "", ""
    meta = _meta_frame(path)
    return (
        _meta_text(meta, "salary_reference", "salary_ref"),
        _meta_text(meta, "allowance_reference", "allowance_ref"),
    )


def set_refs(info, salary, allowance):
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    meta.loc[0, "salary_reference"] = _text(salary)
    meta.loc[0, "allowance_reference"] = _text(allowance)
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)
    _meta_cache.pop(str(info["adjustments"]), None)


def read_batch(info):
    path = info["adjustments"]
    if not path.exists():
        return None
    meta = _meta_frame(path)
    if meta.empty or "batch" not in meta.columns:
        return None
    value = meta.iloc[0]["batch"]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _id_prefix(book):
    path = pay_table_path(book)
    if not path.exists():
        return 197 if book == "admin" else 243
    table = pd.read_excel(path, dtype={"staff_id": str})
    for value in table["staff_id"] if "staff_id" in table.columns else []:
        text = _text(value)
        if "-" in text and text.split("-", 1)[0].isdigit():
            return int(text.split("-", 1)[0])
    return 197 if book == "admin" else 243


def suggested_batch(info):
    """This month's slip batch. Last month's number, plus 2 (plus 1 for admin)."""
    current = read_batch(info)
    if current:
        return current
    year, month = info["year"], info["month"]
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    try:
        previous = book_info(parse_month(f"{year}-{month:02d}"), info.get("book", "bg"))
    except SystemExit:
        previous = None
    if previous is not None and previous["adjustments"].exists():
        earlier = read_batch(previous)
        if earlier:
            step = 1 if info.get("book") == "admin" else 2
            return earlier + step
    return _id_prefix(info.get("book", "bg"))


def set_batch(info, number):
    lines = pd.read_excel(info["adjustments"], sheet_name="lines")
    meta = pd.read_excel(info["adjustments"], sheet_name="meta")
    meta.loc[0, "batch"] = int(number)
    with pd.ExcelWriter(info["adjustments"], engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)


def _match_person(person, staff):
    target = chinese(_text(person.get("name_zh")))
    if not target:
        return None
    hits = staff[staff["_zh"] == target]
    active = hits[hits["active"]]
    chosen = active if not active.empty else hits
    if len(chosen) == 1:
        return chosen.iloc[0]
    return None


def ensure_pay_table(staff=None, book="bg"):
    path = pay_table_path(book)
    if path.exists():
        from payroll.core.excel_io import read_excel
        table = read_excel(path, dtype={"employee_no": str, "staff_id": str})
        table["employee_no"] = table["employee_no"].map(_text)
        table["staff_id"] = table["staff_id"].map(_text)
        return table
    if book != "bg":
        from payroll.core.labels import BOOKS
        raise SystemExit(f"找不到{BOOKS.get(book, book)}薪金表：{path}")
    master_path = home() / "data" / "staff_master.xlsx"
    if not master_path.exists():
        raise SystemExit(
            f"找不到薪金表：{pay_table_path(book)}。十月可以由 data/staff_master.xlsx 建立。"
        )
    if staff is None:
        staff = load_staff()
    from payroll.core.excel_io import read_excel
    master = read_excel(master_path)
    rows = []
    for _, person in master.iterrows():
        match = _match_person(person, staff)
        if match is None:
            raise SystemExit(
                f"無法用中文姓名把 {_text(person.get('slip_name'))} 連結到員工檔。"
            )
        rows.append({
            "employee_no": match["employee_no"],
            "staff_id": _text(person.get("staff_id")),
            "slip_name": _text(person.get("slip_name")),
            "roster_name": _text(person.get("roster_name")),
            "basic_salary": person.get("basic_salary"),
            "scheme": _text(person.get("scheme")) or "mpf",
            "rent_rate": person.get("rent_rate"),
            "rent_base": _text(person.get("rent_base")) or "basic",
            "water": person.get("water"),
            "bonus_eligible": person.get("bonus_eligible"),
            "rest_days_month": person.get("rest_days_month"),
            "allowance_desc": _text(person.get("allowance_desc")),
            "allowance_amount": person.get("allowance_amount") or 0,
            "allowance_note": _text(person.get("allowance_note")),
            "allowance_section": _text(person.get("allowance_section")),
        })
    table = pd.DataFrame(rows, columns=PAY_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_excel(path, index=False)
    return table


def blank_adjustment(person):
    return {
        "staff_id": _text(person.get("staff_id")),
        "slip_name": _text(person.get("slip_name")),
        "unpaid_days": "",
        "absent_days": 0,
        "statutory_days": "",
        "sick_days": "",
        "annual_taken": "",
        "birthday_days": "",
        "taken_rest": "",
        "taken_dates": "",
        "absent_mins": 0,
        "absent_text": "",
        "ot_text": "",
        "ot_pay": "",
        "ot_choice": "",
        "ot_hours_paid": "",
        "other_income": 0,
        "stated_extra": 0,
        "manual_delta": 0,
        "salary_deduct_days": 0,
        "salary_deduct_minutes": 0,
        "unused_annual_days": "",
        "final_transport": 0,
        "final_health": 0,
        "bonus_override": "",
        "rest_override": "",
        "water_override": "",
        "electricity_override": "",
        "note": "",
        "approved": "",
        "salary_reference": "",
        "allowance_reference": "",
        "absence_choices": "",
        "sick_hours": "",
        "bonus_leaver": "",
    }


def next_staff_id(table):
    """Same prefix as the current slips, one number higher. 243-40 becomes 243-41."""
    prefix = "243"
    highest = 0
    for value in table["staff_id"] if "staff_id" in table.columns else []:
        text = _text(value)
        if "-" not in text:
            continue
        left, right = text.split("-", 1)
        if right.isdigit():
            prefix = left or prefix
            highest = max(highest, int(right))
    return f"{prefix}-{highest + 1}"


def _common_rest_days(table):
    if "rest_days_month" not in table.columns or table.empty:
        return 0
    numbers = pd.to_numeric(table["rest_days_month"], errors="coerce").dropna()
    if numbers.empty:
        return 0
    return float(numbers.mode().iloc[0])


def add_new_joiner(info, employee_no, name, salary, scheme, roster_name, book="bg"):
    """Add a person to one payroll and give them the next slip number."""
    from payroll.core.labels import SCHEME_STORED, store
    from payroll.pay.review import apply_review

    from app.lock import ensure_owner
    ensure_owner(info)
    table = ensure_pay_table(book=book)
    table["employee_no"] = table["employee_no"].map(_text)
    table["staff_id"] = table["staff_id"].map(_text)
    try:
        salary = float(salary)
    except (TypeError, ValueError):
        salary = 0
    if salary <= 0:
        raise SystemExit(f"{name}：基本薪金必須是大於 0 的數字")
    scheme = store(SCHEME_STORED, scheme)
    if scheme not in {"mpf", "rent", "none"}:
        raise SystemExit(f"{name}：計薪方式必須是本地員工、內地勞工或不扣強積金")
    employee_no = _text(employee_no)
    name = _text(name)
    roster_name = _text(roster_name)
    fields = {
        "slip_name": name,
        "roster_name": roster_name,
        "basic_salary": salary,
        "scheme": scheme,
        "rent_rate": 0.1 if scheme == "rent" else 0,
        "rent_base": "basic",
        "water": 0,
        "bonus_eligible": 1,
        "rest_days_month": _common_rest_days(table),
        "allowance_desc": "",
        "allowance_amount": 0,
        "allowance_note": "",
        "allowance_section": "",
    }
    existing = table.index[table["employee_no"] == employee_no]
    old_salary = ""
    if len(existing):
        index = existing[0]
        old_salary = table.at[index, "basic_salary"]
        staff_id = _text(table.at[index, "staff_id"]) or next_staff_id(table)
        table.at[index, "staff_id"] = staff_id
        for key, value in fields.items():
            table.at[index, key] = value
    else:
        staff_id = next_staff_id(table)
        table = pd.concat([table, pd.DataFrame([{
            "employee_no": employee_no,
            "staff_id": staff_id,
            **fields,
        }])], ignore_index=True)
    table = table.reindex(columns=PAY_COLUMNS)
    path = pay_table_path(book)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_excel(path, index=False)
    from payroll.pay.review import log_changes
    month = info.get("key", "") if isinstance(info, dict) else ""
    log_changes(month, staff_id, [("basic_salary", old_salary, salary), ("slip_name", "", name)])
    if info is not None:
        ensure_adjustments(info, table)
        apply_review(info, [{"staff_id": staff_id, "slip_name": name}])
    return staff_id


def ensure_adjustments(info, pay_table):
    path = info["adjustments"]
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = pd.DataFrame([blank_adjustment(person) for _, person in pay_table.iterrows()])
    meta = pd.DataFrame([{"pay_date": "", "salary_reference": "", "allowance_reference": ""}])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        lines.to_excel(writer, sheet_name="lines", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)
    return path
