"""Office-pay leaks, formula text, login failures, and the pay change log."""

import io
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.errors import StreamlitSecretNotFoundError

from app.auth import classify_secrets
from app.components.chips import _chip_html
from payroll.core.excel_io import guard_xlsx, safe_cell, safe_frame
from payroll.documents.slips import ps_literal
from payroll.pay.run import allowed_books


def _fail(message):
    raise SystemExit(message)


def test_zip_keeps_out_files_that_were_not_listed():
    from app.views.records import zip_named
    folder = ROOT / "_tmp" / "security-zip"
    folder.mkdir(parents=True, exist_ok=True)
    shop = folder / "payslips.docx"
    office = folder / "payslips_admin.xlsx"
    shop.write_bytes(b"shop")
    office.write_bytes(b"office")
    packed = zipfile.ZipFile(io.BytesIO(zip_named([shop])))
    names = packed.namelist()
    if names != ["payslips.docx"]:
        _fail(names)


def test_the_server_will_not_make_office_slips_for_hr():
    saved = os.environ.get("GRAINHR_SERVER")
    try:
        os.environ.pop("GRAINHR_SERVER", None)
        if allowed_books(("bg", "admin"), role="hr") != ("bg", "admin"):
            _fail("a PC copy should still make every book it was asked for")
        os.environ["GRAINHR_SERVER"] = "1"
        if allowed_books(("bg", "md", "admin"), role="hr") != ("bg", "md"):
            _fail(allowed_books(("bg", "md", "admin"), role="hr"))
        if allowed_books(("bg", "admin"), role="none") != ("bg",):
            _fail("an unlisted server user was allowed to make office slips")
        if allowed_books(None, role="admin") != ("bg", "md", "admin"):
            _fail(allowed_books(None, role="admin"))
    finally:
        if saved is None:
            os.environ.pop("GRAINHR_SERVER", None)
        else:
            os.environ["GRAINHR_SERVER"] = saved


def test_formula_text_is_not_a_formula():
    import pandas as pd
    if safe_cell("=1+1") != "'=1+1" or safe_cell("12") != "12":
        _fail(safe_cell("=1+1"))
    frame = safe_frame(pd.DataFrame([{"name": "+cmd", "amount": 10}]))
    if frame.loc[0, "name"] != "'+cmd" or frame.loc[0, "amount"] != 10:
        _fail(frame.to_dict("records"))
    folder = ROOT / "_tmp" / "security-xlsx"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "cells.xlsx"
    pd.DataFrame([{"name": "=1+1"}]).to_excel(path, index=False)
    guard_xlsx(path)
    from openpyxl import load_workbook
    cell = load_workbook(path).active["A2"]
    if cell.data_type == "f" or not cell.quotePrefix:
        _fail((cell.value, cell.data_type, cell.quotePrefix))


def test_html_and_powershell_cannot_break_out():
    html = _chip_html('<img onerror="x">', "ok")
    if "<img" in html or "&lt;img" not in html:
        _fail(html)
    quoted = ps_literal(r"C:\pay\O'Brien.docx")
    if quoted != r"'C:\pay\O''Brien.docx'":
        _fail(quoted)


def test_a_broken_secrets_file_is_not_treated_as_no_login():
    if classify_secrets(lambda: True) != "on" or classify_secrets(lambda: False) != "off":
        _fail("a readable secrets file was classified wrongly")

    def missing():
        raise StreamlitSecretNotFoundError("none", error_id="no-secrets-found")

    def broken():
        raise StreamlitSecretNotFoundError("bad", error_id="failed-parsing-secrets-file")

    def unexpected():
        raise RuntimeError("boom")

    if classify_secrets(missing) != "off" or classify_secrets(broken) != "broken":
        _fail("a damaged secrets file would leave the app open")
    if classify_secrets(unexpected) != "broken":
        _fail(classify_secrets(unexpected))


def test_server_unknown_user_is_not_an_admin():
    from payroll.core.settings import role_for
    saved = os.environ.get("GRAINHR_SERVER")
    try:
        os.environ["GRAINHR_SERVER"] = "1"
        if role_for("not-a-real-user") != "none":
            _fail(role_for("not-a-real-user"))
    finally:
        if saved is None:
            os.environ.pop("GRAINHR_SERVER", None)
        else:
            os.environ["GRAINHR_SERVER"] = saved


def test_a_salary_change_records_who_did_it():
    import pandas as pd
    from payroll.core.config import home
    from payroll.pay.review import log_changes
    os.environ["PAYROLL_HOME"] = str(ROOT / "_tmp" / "security-audit")
    home().mkdir(parents=True, exist_ok=True)
    path = home() / "data" / "payroll_audit.xlsx"
    if path.exists():
        path.unlink()
    log_changes("2026-10", "S1", [("basic_salary", "100", "120")])
    log_changes("2026-10", "S1", [("basic_salary", "120", "120")])
    found = pd.read_excel(path, engine="openpyxl")
    row = found.iloc[0]
    if len(found) != 1 or str(row["new"]) != "120" or not str(row["user"]):
        _fail(found.to_dict("records"))


if __name__ == "__main__":
    test_zip_keeps_out_files_that_were_not_listed()
    test_the_server_will_not_make_office_slips_for_hr()
    test_formula_text_is_not_a_formula()
    test_html_and_powershell_cannot_break_out()
    test_a_broken_secrets_file_is_not_treated_as_no_login()
    test_server_unknown_user_is_not_an_admin()
    test_a_salary_change_records_who_did_it()
    print("security ok")
