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

    def build():
        folder = root / f"{_TOKENS[month]}_{year}"
        return folder if folder.exists() else None

    from payroll.core.listings import remember
    return remember(("archive", str(root), year, month), root, build)


def month_punches(info):
    """The punch file for one month. GrainHR's copy wins, then the archived DAKA export."""
    own = info["daka"]
    if own.exists():
        return own
    root = path_for("attendance_archive")
    if root is None:
        return None
    from payroll.core.settings import daka as daka_settings
    company = str(daka_settings().get("company") or "").strip()
    if not company:
        return None
    name = f"{info['month']}月{company}內勤報表.csv"
    data = root / "Time_in_data"
    direct = data / name
    if direct.exists():
        return direct
    nested = data / str(info["year"]) / name
    if nested.exists():
        return nested
    return None


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


def _child_dirs(folder):
    if folder is None or not folder.exists():
        return []
    try:
        return [path for path in folder.iterdir() if path.is_dir() and not path.name.startswith("~$")]
    except OSError:
        return []


def classify_slip_dirs(folders, token):
    """Label slip folders. The second company's folder name comes from company.toml."""
    from payroll.core.settings import second_folder

    mark = second_folder()
    found = []
    seen = set()
    for path in folders:
        name = path.name
        label = ""
        if f"({token} FT)" in name:
            label = "全職"
        elif f"({token} PT)" in name:
            label = "兼職"
        elif f"Admin ({token})" in name:
            label = "寫字樓"
        elif mark and name == mark and f"({token} FT)" in path.parent.name:
            label = "md"
        if not label:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        found.append((label, path))
    order = {"全職": 0, "md": 1, "兼職": 2, "寫字樓": 3}
    return sorted(found, key=lambda item: (order.get(item[0], 9), item[1].name))


def slip_folders(year, month):
    """Full-time, second-company, part-time, and office slip folders for one issued month."""
    root = path_for("accounting")
    if root is None:
        return []
    year_dir = Path(root) / str(year)
    if not year_dir.exists():
        return []
    token = _TOKENS[month]

    def build():
        candidates = []
        for path in _child_dirs(year_dir):
            candidates.append(path)
            if "Admin Payslip" in path.name or f"({token} FT)" in path.name:
                candidates.extend(_child_dirs(path))
        return classify_slip_dirs(candidates, token)

    from payroll.core.listings import remember
    return remember(("slips", str(year_dir), token), year_dir, build)


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
