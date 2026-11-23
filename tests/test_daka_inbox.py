"""File a DAKA export by month. No network."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from payroll.core.config import parse_month, scratch_dir
from payroll.attendance.daka import load_daka
from payroll.daka.daka_inbox import OFFLINE, export_now, file_inbox, pull_from_server

HEADER = "姓名,日期,上班,上班位置,下班,下班位置,上班,上班位置,下班,下班位置\n"


def _csv(folder, name, body):
    path = folder / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


class _Result:
    def __init__(self, code, out=""):
        self.returncode = code
        self.stdout = out
        self.stderr = "down"


def test_split_merge_and_paid_month():
    home = scratch_dir("daka-inbox")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        inbox = home / "daka_inbox"
        inbox.mkdir()
        _csv(
            inbox, "span.csv",
            "甲,2026-10-25,09:00,North,18:00,North,,,,\n"
            "乙,2026-10-26,10:00,South,19:00,South,,,,\n"
            "甲,2026-11-03,09:05,North,18:00,North,,,,\n",
        )
        file_inbox(inbox)
        october = parse_month("2026-10")["daka"]
        november = parse_month("2026-11")["daka"]
        october_text = october.read_text(encoding="utf-8-sig")
        if october_text.splitlines()[0] != HEADER.strip():
            raise SystemExit(f"header changed: {october_text.splitlines()[0]}")
        if "2026-11-03" in october_text or "2026-10-25" not in october_text:
            raise SystemExit("October file has the wrong days")
        if "2026-11-03" not in november.read_text(encoding="utf-8-sig"):
            raise SystemExit("November file is missing")
        punches = load_daka(october)
        if punches[("甲", "2026-10-25")]["in"] != "9:00":
            raise SystemExit(f"load_daka {punches.get(('甲', '2026-10-25'))}")
        _csv(inbox, "again.csv", "甲,2026-10-25,09:30,North,18:10,North,,,,\n")
        file_inbox(inbox)
        again = october.read_text(encoding="utf-8-sig")
        if "09:30" not in again or "乙" not in again or again.splitlines()[0] != HEADER.strip():
            raise SystemExit("merge did not replace one row and keep the other")
        paid = parse_month("2026-10")
        (paid["output"] / "payslips.docx").write_bytes(b"paid")
        _csv(inbox, "late.csv", "甲,2026-10-27,09:00,North,18:00,North,,,,\n丙,2026-11-04,09:00,North,18:00,North,,,,\n")
        filed = file_inbox(inbox)
        if "2026-10" not in filed["skipped"] or "2026-10-27" in october.read_text(encoding="utf-8-sig"):
            raise SystemExit(f"paid month was not skipped {filed}")
        if "2026-11-04" not in november.read_text(encoding="utf-8-sig"):
            raise SystemExit("November row from a mixed file was dropped")
        left = list(inbox.glob("*.csv")) + list((inbox / "_已處理").glob("*.csv"))
        if left:
            raise SystemExit(f"old exports were kept: {left}")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


def test_pull_failure_does_not_raise():
    home = scratch_dir("daka-pull")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        message = pull_from_server(run=lambda _args: _Result(1))
        if message != OFFLINE:
            raise SystemExit(f"message {message}")
        status = json.loads((home / "daka_inbox" / "_狀態.json").read_text(encoding="utf-8"))
        if status.get("ok") is False:
            raise SystemExit(f"status {status}")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


def test_export_now_offline_keeps_shared_status():
    home = scratch_dir("daka-export")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        message = export_now(run=lambda _args: _Result(255))
        if "已請伺服器匯出" not in message:
            raise SystemExit(f"message {message}")
        requests = list((home / "daka_inbox").glob("_request_*.txt"))
        if not requests:
            raise SystemExit("the offline PC did not leave a request file")
        status_file = home / "daka_inbox" / "_狀態.json"
        if status_file.exists() and json.loads(status_file.read_text(encoding="utf-8")).get("ok") is False:
            raise SystemExit("an offline PC marked the shared status failed")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


def test_old_exports_are_skipped():
    home = scratch_dir("daka-backlog")
    os.environ["PAYROLL_HOME"] = str(home)
    try:
        inbox = home / "daka_inbox"
        inbox.mkdir()
        _csv(inbox, "daka_share_20261121_090000.csv", "甲,2026-11-03,09:00,North,18:00,North,,,,\n")
        _csv(inbox, "daka_share_20261121_170000.csv", "乙,2026-11-04,09:00,North,18:00,North,,,,\n")
        _csv(inbox, "daka_share_20261121_170500.csv", "丙,2026-11-05,09:00,North,18:00,North,,,,\n")
        _csv(inbox, "phone.csv", "丁,2026-11-06,09:00,North,18:00,North,,,,\n")
        file_inbox(inbox)
        text = parse_month("2026-11")["daka"].read_text(encoding="utf-8-sig")
        if "2026-11-03" in text:
            raise SystemExit("an export older than the latest run was filed")
        for day in ("2026-11-04", "2026-11-05", "2026-11-06"):
            if day not in text:
                raise SystemExit(f"{day} from the latest run or the phone was dropped")
    finally:
        os.environ.pop("PAYROLL_HOME", None)


if __name__ == "__main__":
    test_split_merge_and_paid_month()
    test_old_exports_are_skipped()
    test_pull_failure_does_not_raise()
    test_export_now_offline_keeps_shared_status()
    print("daka inbox ok")
