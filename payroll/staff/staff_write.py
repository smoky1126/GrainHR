"""Write staff details back to Staff_info through Excel, and record the change.

Excel keeps the dropdown lists that come from Sheet2. openpyxl would drop them.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

from payroll.core.config import home
from payroll.staff.staff import _as_date, _text, latest_staff_file, load_staff, pay_table_path

_SECRET = {"身份證號碼", "銀行賬號"}
_DATE_FIELDS = {"入職日期", "到職日期", "離職日期", "出生日期", "合約完結日期"}
_CHECK = {
    "中文姓名": "name_zh",
    "英文姓名": "name_en",
    "員工名稱": "roster_hint",
    "職位": "position",
    "部門": "department",
    "僱傭狀況": "status",
    "就業形式": "employment",
    "性別": "gender",
    "婚姻狀況": "marital",
    "住址": "address",
    "身份證號碼": "hkid",
    "手提電話號碼": "phone",
    "銀行賬號": "bank_account",
    "銀行名稱": "bank_name",
    "緊急聯絡人": "emergency_name",
    "緊急聯絡人關係": "emergency_relation",
    "緊急聯絡人電話號碼": "emergency_phone",
    "緊急聯絡人_1": "emergency_name_2",
    "緊急聯絡人關係_1": "emergency_relation_2",
    "緊急聯絡人電話號碼_1": "emergency_phone_2",
    "合約編號": "contract_no",
    "批准信地址": "permit_address",
    "入職日期": "join_date",
    "到職日期": "join_date",
    "離職日期": "leave_date",
    "出生日期": "birth_date",
    "合約完結日期": "contract_end",
}


def _backup(path):
    folder = path.parent / "_備份"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = folder / f"{path.stem}_{stamp}{path.suffix}"
    count = 2
    while dest.exists():
        dest = folder / f"{path.stem}_{stamp}_{count}{path.suffix}"
        count += 1
    shutil.copy2(path, dest)
    copies = sorted(folder.glob(f"{path.stem}_*{path.suffix}"), key=lambda item: item.stat().st_mtime)
    while len(copies) > 30:
        copies.pop(0).unlink(missing_ok=True)
    return dest


def _log_path():
    folder = home() / "data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "staff_changes.xlsx"


def _shown(field, value):
    if field in _SECRET and _text(value):
        return "已更改"
    return _text(value)


def _append_log(rows):
    path = _log_path()
    frame = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_excel(path, engine="openpyxl")
        frame = pd.concat([old, frame], ignore_index=True)
    frame.to_excel(path, index=False)


def _current(path, employee_no, name_zh):
    staff = load_staff(path)
    matched = staff[
        staff["employee_no"].map(_text).eq(employee_no)
        & staff["name_zh"].map(_text).eq(name_zh)
    ]
    if matched.empty:
        return None
    return matched.iloc[0]


def _same(field, record, expected):
    key = _CHECK.get(field)
    if key is None or record is None:
        return True
    got = record.get(key)
    if field in _DATE_FIELDS:
        found = _as_date(got)
        return (found.isoformat() if found else "") == _text(expected)
    return _text(got) == _text(expected)


def _run_excel(payload):
    folder = home() / "_tmp"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "staff_write.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    script = Path(__file__).with_name("staff_write.ps1")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-File", str(script), "-JsonPath", str(json_path)],
            check=False, capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"請先關閉 Staff_info 檔案，然後再試。（{error}）") from error
    if done.returncode != 0:
        detail = (done.stderr or b"").decode("utf-8", errors="replace")
        detail += "\n" + (done.stdout or b"").decode("utf-8", errors="replace")
        (home() / "_tmp" / "staff_write_error.txt").write_text(detail, encoding="utf-8")
        if "請先關閉" in detail:
            raise SystemExit("請先關閉 Staff_info 檔案，然後再試。")
        line = next((item for item in reversed(detail.splitlines()) if item.strip()), "")
        raise SystemExit(line or "請先關閉 Staff_info 檔案，然後再試。")


def _sheet_columns(path, sheet):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        grid = book[sheet]
        for row in grid.iter_rows(min_row=1, max_row=15):
            names = [_text(cell.value).rstrip("*") for cell in row]
            if any(name.startswith("員工編號") for name in names):
                return {name for name in names if name}
    finally:
        book.close()
    return set()


def _apply(action, sheet, employee_no, name_zh, fields, path=None):
    path = Path(path) if path else latest_staff_file()
    employee_no = _text(employee_no)
    name_zh = _text(name_zh)
    if not employee_no or not name_zh:
        raise SystemExit("請填員工編號和中文姓名。")
    before = _current(path, employee_no, name_zh)
    if action == "add" and before is not None and _text(before.get("status")) in {"", "在職"}:
        raise SystemExit(f"{employee_no} 已有在職紀錄。")
    if action != "add" and before is None:
        raise SystemExit(f"找不到 {employee_no} {name_zh}。")
    known = _sheet_columns(path, sheet)
    if action == "resign":
        known.add("離職日期")
    clean = {
        key: "" if value is None else _text(value)
        for key, value in fields.items()
        if key in known or key in {"員工編號", "中文姓名"}
    }
    clean["員工編號"] = employee_no
    clean["中文姓名"] = name_zh
    _backup(path)
    _run_excel({
        "path": str(path.resolve()),
        "action": action,
        "sheet": sheet,
        "employee_no": employee_no,
        "name_zh": name_zh,
        "fields": clean,
    })
    after = _current(path, employee_no, name_zh)
    if after is None:
        raise SystemExit(f"寫入後找不到 {employee_no} {name_zh}。")
    for field, value in clean.items():
        if not _same(field, after, value):
            raise SystemExit(f"{field} 沒有寫進員工檔。")
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = os.environ.get("USERNAME", "")
    rows = []
    for field, value in clean.items():
        old = ""
        if before is not None and field in _CHECK:
            old = _text(before.get(_CHECK[field]))
            if field in _DATE_FIELDS:
                found = _as_date(before.get(_CHECK[field]))
                old = found.isoformat() if found else ""
        if action != "add" and old == _text(value):
            continue
        rows.append({
            "time": when, "user": user, "employee_no": employee_no, "name_zh": name_zh,
            "sheet": sheet, "action": action, "field": field,
            "old": _shown(field, old), "new": _shown(field, value),
        })
    if rows:
        _append_log(rows)
    return after


def add_staff(sheet, employee_no, name_zh, fields, path=None):
    return _apply("add", sheet, employee_no, name_zh, fields, path)


def edit_staff(sheet, employee_no, name_zh, fields, path=None):
    changed = {key: value for key, value in fields.items() if key not in {"員工編號", "中文姓名"}}
    return _apply("edit", sheet, employee_no, name_zh, changed, path)


def resign_staff(sheet, employee_no, name_zh, leave_date, path=None):
    return _apply("resign", sheet, employee_no, name_zh, {
        "僱傭狀況": "已離職",
        "離職日期": _text(leave_date),
    }, path)


def salary_history_path():
    folder = home() / "data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "salary_history.xlsx"


def _salary_log(employee_no, old, new, kind):
    path = salary_history_path()
    row = pd.DataFrame([{
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": os.environ.get("USERNAME", ""),
        "employee_no": employee_no,
        "kind": kind,
        "old": old,
        "new": new,
    }])
    if path.exists():
        row = pd.concat([pd.read_excel(path, engine="openpyxl"), row], ignore_index=True)
    row.to_excel(path, index=False)


def set_monthly_salary(book, employee_no, amount):
    path = pay_table_path(book)
    if not path.exists():
        raise SystemExit("這個人不在薪金表。")
    table = pd.read_excel(path, engine="openpyxl")
    table["employee_no"] = table["employee_no"].map(_text)
    found = table.index[table["employee_no"] == _text(employee_no)]
    if len(found) == 0:
        raise SystemExit("這個人不在薪金表。")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise SystemExit("薪金必須是大於 0 的數字。")
    if amount <= 0:
        raise SystemExit("薪金必須是大於 0 的數字。")
    index = found[0]
    old = table.at[index, "basic_salary"]
    table.at[index, "basic_salary"] = amount
    table.to_excel(path, index=False)
    _salary_log(employee_no, old, amount, "月薪")
    return amount


def set_hourly_rate(info, employee_no, rate):
    from payroll.pay.part_time import load_pt, save_pt_lines
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        raise SystemExit("時薪必須是大於 0 的數字。")
    if rate <= 0:
        raise SystemExit("時薪必須是大於 0 的數字。")
    lines, _meta = load_pt(info)
    number = _text(employee_no)
    old = None
    records = []
    seen = False
    for _, row in lines.iterrows():
        item = row.to_dict()
        if _text(item.get("employee_no")) == number:
            old = item.get("rate")
            item["rate"] = rate
            seen = True
        records.append(item)
    if not seen:
        records.append({
            "employee_no": number, "rate": rate, "scheme": "mpf",
            "extra_hours": 0, "extra_note": "", "bank": "", "account": "", "pay_this": "Y",
        })
    save_pt_lines(info, records)
    _salary_log(number, old, rate, "時薪")
    return rate
