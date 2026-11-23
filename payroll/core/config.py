"""Paths and pay settings for one monthly payroll run."""

import calendar
import os
import shutil
from pathlib import Path

from payroll.core.settings import daka as daka_settings
from payroll.core.settings import path_for, roster_sources

CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = CODE_ROOT


def home():
    """Payroll files. PAYROLL_HOME points the demo at its own copy."""
    raw = os.environ.get("PAYROLL_HOME", "").strip()
    if not raw:
        return CODE_ROOT
    path = Path(raw)
    if not path.is_absolute():
        path = (CODE_ROOT / path).resolve()
    return path


def scratch_dir(name):
    """A folder inside _tmp for a test. Nothing is written outside the project."""
    folder = CODE_ROOT / "_tmp" / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder

def shop_list():
    """Place name and punch code from company.toml. Nothing about a real shop is stored here."""
    from payroll.core.settings import shops as shop_rows

    return [[label, code] for label, code in shop_rows() if label and code]

HOUR_STANDARD = 9.5
SKIPROWS = 2

MPF_RATE = 0.05
MPF_MIN_INCOME = 7100
MPF_MAX_INCOME = 30000
ATTENDANCE_BONUS = 1000

REFERENCE_CHECK = ROOT / "Oct_2026" / "10月考勤核對表.xlsx"
REFERENCE_SLIPS = ROOT / "Oct_2026" / "#243_0_production_retail.docx"
STAFF_RECORD_DIR = path_for("staff_record") or (ROOT / "fixtures_private")
_DAKA = daka_settings()
DAKA_SERVER = _DAKA.get("server") or ""
DAKA_REMOTE = _DAKA.get("remote") or ""
ROSTER_SHEET_DIR = path_for("roster_sheets") or (ROOT / "fixtures_private")
ROSTER_COPY_DIR = path_for("roster_copies") or (ROOT / "fixtures_private")

MONTH_TOKEN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# {year} and {mon} are filled in for the payroll month. Mon is Oct, Nov, Sep.
ROSTER_SOURCES = roster_sources()


def parse_month(key):
    text = str(key).strip()
    parts = text.split("-")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise SystemExit(f"月份格式必須是 2026-10，不是 {key}。")
    year, month = int(parts[0]), int(parts[1])
    if len(parts[0]) != 4 or not 1 <= month <= 12:
        raise SystemExit(f"月份格式必須是 2026-10，不是 {key}。")
    days = calendar.monthrange(year, month)[1]
    token = MONTH_TOKEN[month]
    folder = home() / "months" / f"{year}_{month:02d}"
    system = folder / "_system"
    info = {
        "key": f"{year}-{month:02d}",
        "sheet": f"{month}月",
        "year": year,
        "month": month,
        "days": days,
        "month_token": token,
        "period_text": (
            f"01/{month:02d}/{year} \u2013 {days:02d}/{month:02d}/{year} ({days} Days)"
        ),
        "bonus_month": token.upper(),
        "bonus_month_zh": f"{month}月",
        "folder": folder,
        "system": system,
        "daka": folder / "daka.csv",
        "rosters": system / "店鋪數據",
        "adjustments": system / "adjustments.xlsx",
        "output": folder,
        "allowance_source": system / "allowance_source.xlsx",
    }
    migrate_month_layout(info)
    return book_info(info, "bg")


def migrate_month_layout(info):
    """Move an older month folder so HR only sees the draft, the slips, and daka.csv."""
    folder = info["folder"]
    system = info["system"]
    old_output = folder / "output"
    old_rosters = folder / "店鋪數據"
    leftovers = [folder / "adjustments.xlsx", folder / "allowance_source.xlsx"]
    if not old_output.exists() and not old_rosters.exists() and not any(path.exists() for path in leftovers):
        return
    system.mkdir(parents=True, exist_ok=True)
    user_files = {"payroll_draft.xlsx", "payslips.docx", "allowance_summary.xlsx"}
    if old_output.exists():
        for item in list(old_output.iterdir()):
            if item.name.startswith("~$"):
                continue
            target = folder / item.name if item.name in user_files else system / item.name
            _move_into_place(item, target)
        try:
            old_output.rmdir()
        except OSError:
            pass
    for name in ("adjustments.xlsx", "allowance_source.xlsx"):
        _move_into_place(folder / name, system / name)
    if old_rosters.exists() and not info["rosters"].exists():
        old_rosters.replace(info["rosters"])


def _move_into_place(source, target):
    if not source.exists():
        return
    if not target.exists():
        try:
            source.replace(target)
            return
        except PermissionError:
            try:
                from payroll.core.excel_io import copy_file
                copy_file(source, target)
            except PermissionError:
                return
    try:
        source.unlink()
    except PermissionError:
        pass


def book_info(info, book="bg"):
    """One payroll's files. The first book keeps the original file names."""
    suffix = "" if book == "bg" else f"_{book}"
    slips = {
        "bg": ("payslip_bg.docx", "payslips.docx"),
        "md": ("payslip_md.docx", "payslips_md.docx"),
        "admin": ("payslip_admin.xlsx", "payslips_admin.xlsx"),
    }
    template, output = slips[book]
    booked = dict(info)
    booked["book"] = book
    booked["balance_suffix"] = suffix
    booked["adjustments"] = info["system"] / f"adjustments{suffix}.xlsx"
    booked["slip_template"] = home() / "templates" / template
    booked["slip_output"] = info["output"] / output
    return booked


def opening_balance_path(info):
    """Previous month's closing file, or this month's opening file if that is all we have."""
    year, month = info["year"], info["month"]
    if month == 1:
        previous_year, previous_month = year - 1, 12
    else:
        previous_year, previous_month = year, month - 1
    suffix = info.get("balance_suffix", "")
    balances = home() / "data" / "balances"
    previous = balances / f"{previous_year}_{previous_month:02d}_close{suffix}.xlsx"
    if previous.exists():
        return previous
    own = balances / f"{year}_{month:02d}_open{suffix}.xlsx"
    if own.exists():
        return own
    return None
