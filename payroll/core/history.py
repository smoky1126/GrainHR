"""Issued months stay as they were. Later months are saved under months/."""

from pathlib import Path

from payroll.core.settings import issued_through, path_for

_TOKENS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def is_issued(key):
    """January through the configured month are already paid and must not be recalculated."""
    limit = issued_through()
    return bool(limit) and str(key) <= limit


def archive_folder(year, month):
    root = path_for("attendance_archive")
    if root is None:
        return None
    folder = root / f"{_TOKENS[month]}_{year}"
    return folder if folder.exists() else None


def attendance_workbook(year, month):
    folder = archive_folder(year, month)
    if folder is None:
        return None
    exact = folder / f"{month}月考勤核對表.xlsx"
    if exact.exists():
        return exact
    matches = [
        path for path in folder.glob(f"{month}月考勤核對表*.xlsx")
        if not path.name.startswith("~$")
    ]
    return sorted(matches)[0] if matches else None


def archived_roster(year, month, shop):
    folder = archive_folder(year, month)
    if folder is None:
        return None
    shop_dir = folder / "店鋪數據" / shop
    return shop_dir if shop_dir.exists() else None


def slip_folders(year, month):
    """Full-time, part-time, and office slip folders for one issued month."""
    root = path_for("accounting")
    if root is None:
        return []
    year_dir = Path(root) / str(year)
    if not year_dir.exists():
        return []
    token = _TOKENS[month]
    found = []
    folders = [path for path in year_dir.rglob("*") if path.is_dir()]
    for path in folders:
        name = path.name
        if f"({token} FT)" in name:
            found.append(("全職", path))
        elif f"({token} PT)" in name:
            found.append(("兼職", path))
        elif f"Admin ({token})" in name:
            found.append(("寫字樓", path))
    return found


def saved_files(info):
    """Files GrainHR has kept for this month."""
    folder = info["folder"]
    names = (
        "daka.csv",
        "payroll_draft.xlsx",
        "payslips.docx",
        "payslips_md.docx",
        "payslips_admin.xlsx",
        "allowance_summary.xlsx",
    )
    kept = [folder / name for name in names if (folder / name).exists()]
    check = info["system"] / f"{info['sheet']}考勤核對表.xlsx"
    if check.exists():
        kept.append(check)
    return kept
