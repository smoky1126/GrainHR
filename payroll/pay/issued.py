"""Figures from salary slips that were already issued, saved once per month."""

from pathlib import Path

import pandas as pd

from payroll.core.excel_io import read_excel, save_excel
from payroll.core.history import slip_folders

COLUMNS = [
    "book", "staff_id", "slip_name", "name_zh", "name_en",
    "basic_salary", "net", "mpf_employee", "mpf_employer",
]
_BOOKS = {"全職": "bg", "md": "md", "寫字樓": "admin"}


def issued_path(info):
    return Path(info["system"]) / "issued_slips.xlsx"


def visible_issued(frame, role):
    """Office rows stay on the saved file and are hidden from HR in the app."""
    from payroll.core.access import can_see_pay

    if frame is None or not len(frame) or "book" not in getattr(frame, "columns", []):
        return frame
    if can_see_pay("admin", role):
        return frame
    return frame[frame["book"].astype(str) != "admin"].copy()


def _main_file(folder, suffix):
    files = [
        path for path in Path(folder).iterdir()
        if path.is_file() and path.suffix.lower() == suffix and not path.name.startswith("~$")
    ]
    if not files:
        return None
    preferred = [path for path in files if "_0_" in path.name]
    return sorted(preferred or files, key=lambda path: path.name)[0]


def _rows(label, folder):
    book = _BOOKS.get(label)
    if book is None:
        return []
    if book == "admin":
        path = _main_file(folder, ".xlsx")
        if path is None:
            return []
        from payroll.documents.parse_admin import parse_admin
        slips = parse_admin(path)
    else:
        path = _main_file(folder, ".docx")
        if path is None:
            return []
        from payroll.documents.parse_slips import parse_slips
        slips = parse_slips(path)
    rows = []
    for slip in slips:
        rows.append({
            "book": book,
            "staff_id": slip.get("staff_id") or "",
            "slip_name": slip.get("slip_name") or slip.get("name_zh") or "",
            "name_zh": slip.get("name_zh") or "",
            "name_en": slip.get("name_en") or "",
            "basic_salary": slip.get("basic_salary") or 0,
            "net": slip.get("net") or 0,
            "mpf_employee": slip.get("mpf_employee") or 0,
            "mpf_employer": slip.get("mpf_employer") or 0,
        })
    return rows


def build_issued(info):
    rows = []
    for label, folder in slip_folders(info["year"], info["month"]):
        try:
            rows.extend(_rows(label, folder))
        except (OSError, KeyError, ValueError, IndexError, TypeError):
            continue
    return pd.DataFrame(rows, columns=COLUMNS)


def load_issued(info):
    path = issued_path(info)
    if path.exists():
        return read_excel(path)
    frame = build_issued(info)
    if frame is None or not len(frame):
        return frame
    info["system"].mkdir(parents=True, exist_ok=True)
    save_excel(path, frame)
    return read_excel(path)
