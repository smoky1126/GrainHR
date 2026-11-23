"""Roster copies: missing file, two files, a missing month sheet, and a good file."""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("PAYROLL_HOME", None)
os.environ.pop("PAYROLL_DEMO", None)

from openpyxl import Workbook

from payroll.core.config import ROSTER_SOURCES, parse_month, scratch_dir
from payroll.attendance.rosters import RosterProblem, copy_rosters


def _fill(source, sheet="10月", skip=None, extra=None, bad_sheet=None):
    for folder, pattern, shop in ROSTER_SOURCES:
        if skip and shop == skip:
            continue
        file_name = pattern.format(year=2026, mon="Oct")
        sheets = ["Sheet1"] if shop == bad_sheet else [sheet]
        _book(source / shop / f"{file_name}.xlsx", sheets)
        if shop == extra:
            _book(source / shop / f"{file_name} (1).xlsx", sheets)


def _book(path, sheets):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.active.title = sheets[0]
    for name in sheets[1:]:
        book.create_sheet(name)
    book.save(path)


def main():
    info = parse_month("2026-10")
    root = scratch_dir("rosters")
    try:
        source = root / "copies"
        destination = root / "month"
        _fill(source)
        (source / "_copied_at.txt").write_text("Copied test\n", encoding="utf-8")
        saved = copy_rosters(info, source=source, destination=destination)
        if len(saved) != len(ROSTER_SOURCES):
            raise SystemExit(f"expected {len(ROSTER_SOURCES)} rosters, copied {len(saved)}")
        _folder, pattern, shop = ROSTER_SOURCES[0]
        file_name = pattern.format(year=2026, mon="Oct")
        if not (destination / shop / f"{file_name}.xlsx").exists():
            raise SystemExit("a good roster was not copied")
        copied = (destination / shop / f"{file_name}.xlsx").read_bytes()
        original = (source / shop / f"{file_name}.xlsx").read_bytes()
        if copied != original:
            raise SystemExit("the copied roster bytes changed")
        from payroll.core.excel_io import copy_file
        again = root / "again.xlsx"
        real_copy2 = shutil.copy2

        def refuse_attributes(source_file, target_file, *args, **kwargs):
            raise OSError(5, "Input/output error")

        shutil.copy2 = refuse_attributes
        try:
            copy_file(source / shop / f"{file_name}.xlsx", again)
        finally:
            shutil.copy2 = real_copy2
        if again.read_bytes() != original:
            raise SystemExit("a Drive-style copy should still keep the workbook bytes")

        missing = root / "missing"
        _fill(missing, skip=shop)
        try:
            copy_rosters(info, source=missing, destination=root / "missing_out")
        except RosterProblem as error:
            text = str(error)
            if shop not in text or file_name not in text:
                raise SystemExit(f"missing file was not named:\n{error}")
            if (root / "missing_out").exists():
                raise SystemExit("a failed copy should not write roster files")
        else:
            raise SystemExit("a missing roster should stop the copy")

        doubled = root / "doubled"
        _fill(doubled, extra=shop)
        try:
            copy_rosters(info, source=doubled, destination=root / "doubled_out")
        except RosterProblem as error:
            if "多於一份" not in str(error):
                raise SystemExit(f"two files were not reported:\n{error}")
        else:
            raise SystemExit("two roster files should stop the copy")

        wrong_sheet = root / "sheet"
        _fill(wrong_sheet, bad_sheet=shop)
        try:
            copy_rosters(info, source=wrong_sheet, destination=root / "sheet_out")
        except RosterProblem as error:
            if "沒有工作表 10月" not in str(error):
                raise SystemExit(f"missing month sheet was not reported:\n{error}")
        else:
            raise SystemExit("a roster with no month sheet should stop the copy")
    finally:
        shutil.rmtree(root)
    print("roster checks ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
