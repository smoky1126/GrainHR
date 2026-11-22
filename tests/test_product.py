"""Lock, past months, slip folders, and the logo fallback. No company files."""

import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = ROOT / "_tmp" / "product"
if HOME.exists():
    shutil.rmtree(HOME)
HOME.mkdir(parents=True)


def _fail(message):
    raise SystemExit(message)


def test_lock_is_not_rewritten_within_ten_minutes():
    from app.lock import claim

    os.environ["USERNAME"] = "tester"
    os.environ["USER"] = "tester"
    info = {"system": HOME / "lock"}
    claim(info)
    path = info["system"] / "使用中.txt"
    first = path.stat().st_mtime_ns
    claim(info)
    if path.stat().st_mtime_ns != first:
        _fail("the lock file was rewritten on the second click")
    old = (datetime.now() - timedelta(minutes=11)).isoformat(timespec="minutes")
    path.write_text(f"tester\n{old}\n", encoding="utf-8")
    claim(info)
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2 or lines[1] == old:
        _fail("a stamp older than 10 minutes should be refreshed")


def test_month_punches_uses_the_archive_when_the_month_has_no_copy():
    archive = HOME / "archive"
    data = archive / "Time_in_data"
    data.mkdir(parents=True)
    (data / "7月Example Bakery內勤報表.csv").write_text("姓名,日期\n", encoding="utf-8")
    nested = data / "2025"
    nested.mkdir()
    (nested / "3月Example Bakery內勤報表.csv").write_text("姓名,日期\n", encoding="utf-8")
    company = HOME / "company.toml"
    company.write_text(
        "[paths]\nattendance_archive = '" + archive.as_posix() + "'\n\n"
        "[daka]\ncompany = \"Example Bakery\"\n",
        encoding="utf-8",
    )
    os.environ["PAYROLL_COMPANY"] = str(company)
    from payroll.core.listings import clear_listings
    from payroll.core.settings import load
    load.cache_clear()
    clear_listings()
    from payroll.core.history import month_punches

    july = month_punches({"daka": HOME / "missing.csv", "month": 7, "year": 2026})
    if july is None or july.name != "7月Example Bakery內勤報表.csv":
        _fail(july)
    march = month_punches({"daka": HOME / "missing.csv", "month": 3, "year": 2025})
    if march is None or march.parent.name != "2025":
        _fail(march)
    own = HOME / "own.csv"
    own.write_text("姓名,日期\n", encoding="utf-8")
    if month_punches({"daka": own, "month": 7, "year": 2026}) != own:
        _fail("the month copy should be used when it exists")


def test_slip_folders_include_ma_douce_without_a_deep_search():
    from payroll.core.history import classify_slip_dirs

    root = HOME / "slips"
    full_time = root / "#241 (Sep FT)"
    douce = full_time / "MD"
    part_time = root / "#242 (Sep PT)"
    office = root / "2026 Admin Payslip" / "#196_Admin (Sep)"
    for folder in (douce, part_time, office):
        folder.mkdir(parents=True)
    labels = dict(classify_slip_dirs(
        [full_time, douce, part_time, office.parent, office], "Sep",
    ))
    if set(labels) != {"全職", "md", "兼職", "寫字樓"}:
        _fail(sorted(labels))
    if labels["md"] != douce:
        _fail(labels["md"])


def test_issued_summary_hides_office_rows_from_hr():
    import pandas as pd

    from payroll.pay.issued import visible_issued

    frame = pd.DataFrame([
        {"book": "bg", "net": 1},
        {"book": "md", "net": 2},
        {"book": "admin", "net": 99},
    ])
    shown = visible_issued(frame, "hr")
    if set(shown["book"]) != {"bg", "md"}:
        _fail(list(shown["book"]))
    if len(visible_issued(frame, "admin")) != 3:
        _fail("admin should see the office book")


def test_logo_uses_the_file_beside_company_toml():
    assets = HOME / "assets"
    assets.mkdir(exist_ok=True)
    logo = assets / "logo.jpg"
    logo.write_bytes(b"not-a-real-jpeg")
    company = HOME / "company.toml"
    if not company.exists():
        company.write_text("private = true\n", encoding="utf-8")
    os.environ["PAYROLL_COMPANY"] = str(company)
    from payroll.core.settings import load
    load.cache_clear()
    from app.components import theme
    original = theme.LOGO
    theme.LOGO = HOME / "no-logo-here.jpg"
    try:
        found = theme.logo_file()
    finally:
        theme.LOGO = original
    if found != logo:
        _fail(found)


def test_settings_reload_when_the_file_changes():
    company = HOME / "reload.toml"
    company.write_text("private = false\n", encoding="utf-8")
    os.environ["PAYROLL_COMPANY"] = str(company)
    from payroll.core.settings import is_private, load
    load.cache_clear()
    if is_private():
        _fail("expected a public example")
    company.write_text("private = true\n", encoding="utf-8")
    if not is_private():
        _fail("a saved company.toml should be read without restarting")


if __name__ == "__main__":
    test_lock_is_not_rewritten_within_ten_minutes()
    test_month_punches_uses_the_archive_when_the_month_has_no_copy()
    test_slip_folders_include_ma_douce_without_a_deep_search()
    test_issued_summary_hides_office_rows_from_hr()
    test_logo_uses_the_file_beside_company_toml()
    test_settings_reload_when_the_file_changes()
    print("product ok")
