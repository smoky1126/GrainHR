"""Copy October into demo/home so a trial does not touch the real files."""

import shutil
from pathlib import Path

from payroll.core.config import CODE_ROOT

DEMO_HOME = CODE_ROOT / "demo" / "home"


def _ignore(directory, names):
    return [name for name in names if name.startswith("~$") or name == "output"]


# These must be in the demo. An older copy only had the first payroll.
_NEEDED = (
    "data/pay_table.xlsx",
    "data/pay_table_md.xlsx",
    "data/pay_table_admin.xlsx",
    "data/balances/2026_10_open.xlsx",
    "data/balances/2026_10_open_md.xlsx",
    "data/balances/2026_10_open_admin.xlsx",
    "templates/payslip_bg.docx",
    "templates/payslip_md.docx",
    "templates/payslip_admin.xlsx",
    "templates/payslip_bg_quarter.docx",
    "templates/payslip_md_quarter.docx",
    "months/2026_10/_system/daily_facts.xlsx",
    "months/2026_10/_system/adjustments.xlsx",
    "months/2026_10/_system/adjustments_md.xlsx",
    "months/2026_10/_system/adjustments_admin.xlsx",
)


def _fill_missing(dest):
    """Copy payroll files that an older demo does not have yet."""
    for relative in _NEEDED:
        target = dest / relative
        source = CODE_ROOT / relative
        if target.exists() or not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build_demo(force=False, dest=None):
    dest = Path(dest) if dest else DEMO_HOME
    if dest.exists() and not force and all((dest / relative).exists() for relative in _NEEDED):
        return dest
    if dest.exists() and not force:
        _fill_missing(dest)
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    for name in ("data", "templates"):
        source = CODE_ROOT / name
        if source.exists():
            shutil.copytree(source, dest / name, ignore=_ignore)
    month = CODE_ROOT / "months" / "2026_10"
    if month.exists():
        shutil.copytree(month, dest / "months" / "2026_10", ignore=_ignore)
    return dest


if __name__ == "__main__":
    print(build_demo())
