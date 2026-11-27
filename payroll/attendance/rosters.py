"""Copy the month's shop rosters from the Excel folder the Apps Script fills."""

from pathlib import Path

from openpyxl import load_workbook

from payroll.core.config import ROSTER_COPY_DIR, ROSTER_SOURCES


class RosterProblem(Exception):
    def __init__(self, messages):
        super().__init__("\n".join(messages))
        self.messages = messages


def _has_month_sheet(path, sheet_name):
    book = load_workbook(path, read_only=True)
    try:
        return any(name.strip() == sheet_name for name in book.sheetnames)
    finally:
        book.close()


def _matches(shop_dir, file_name):
    if not shop_dir.exists():
        return []
    found = []
    for path in shop_dir.glob("*.xlsx"):
        if path.name.startswith("~$"):
            continue
        if path.stem == file_name or path.stem.startswith(file_name + " "):
            found.append(path)
    return sorted(found, key=lambda path: path.name)


def copy_rosters(info, source=None, destination=None):
    """Copy the 12 shop rosters into the month folder. Stop with every problem listed."""
    source = Path(source) if source else ROSTER_COPY_DIR
    destination = Path(destination) if destination else info["rosters"]
    if not source.exists():
        raise SystemExit(
            f"找不到更表副本：{source}。請先在 script.google.com 貼上 google/copy_rosters.gs，"
            "按執行並允許一次，然後等待 Drive 同步。"
        )
    stamp = source / "_copied_at.txt"
    if stamp.exists():
        print(stamp.read_text(encoding="utf-8").strip())
    else:
        print(f"{source} 沒有複製時間。如果更表看起來舊了，請再執行 google/copy_rosters.gs。")
    year, token = info["year"], info["month_token"]
    problems = []
    planned = []
    for folder, pattern, shop in ROSTER_SOURCES:
        file_name = pattern.format(year=year, mon=token)
        matches = _matches(source / shop, file_name)
        if not matches:
            problems.append(f"{shop}：找不到更表 {file_name}")
            continue
        if len(matches) > 1:
            problems.append(f"{shop}：多於一份名為 {file_name} 的檔案")
            continue
        if not _has_month_sheet(matches[0], info["sheet"]):
            problems.append(f"{shop}：{file_name} 沒有工作表 {info['sheet']}")
            continue
        planned.append((shop, matches[0], destination / shop / f"{file_name}.xlsx"))
    if problems:
        raise RosterProblem(problems)
    saved = []
    for shop, source_file, target in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        for old in target.parent.glob("*.xlsx"):
            if not old.name.startswith("~$"):
                old.unlink()
        from payroll.core.excel_io import copy_file
        copy_file(source_file, target)
        saved.append(target)
    return saved


def roster_status(info, source=None):
    """What the app shows before Check copies the files."""
    source = Path(source) if source else ROSTER_COPY_DIR
    stamp = source / "_copied_at.txt"
    copied = ""
    if stamp.exists():
        lines = stamp.read_text(encoding="utf-8").splitlines()
        copied = lines[0] if lines else ""
    rows = []
    if not source.exists():
        for folder, pattern, shop in ROSTER_SOURCES:
            rows.append({"店鋪": shop, "狀態": "缺少", "檔案": "未有副本資料夾"})
        return copied, rows
    year, token = info["year"], info["month_token"]
    for folder, pattern, shop in ROSTER_SOURCES:
        file_name = pattern.format(year=year, mon=token)
        matches = _matches(source / shop, file_name)
        if not matches:
            state = "缺少"
        elif len(matches) > 1:
            state = "多於一份"
        elif not _has_month_sheet(matches[0], info["sheet"]):
            state = "沒有月份工作表"
        else:
            state = "已找到"
        rows.append({"店鋪": shop, "狀態": state, "檔案": file_name})
    return copied, rows


def oldest_roster_file(source=None):
    """When the inbox Excel was last written. 更新更表 copies this file, not the Google sheet."""
    source = Path(source) if source else ROSTER_COPY_DIR
    if not source.exists():
        return None
    times = []
    for path in source.rglob("*.xlsx"):
        if path.name.startswith("~$"):
            continue
        times.append(path.stat().st_mtime)
    if not times:
        return None
    from datetime import datetime
    return datetime.fromtimestamp(min(times))
