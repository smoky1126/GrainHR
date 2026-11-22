"""Saved months: issued slips stay put, and later months stay in the month folder."""

import os

import streamlit as st

from app.components.cards import page_header
from app.components.theme import inject, show_logo
from app.context import _context, _month_label
from payroll.core.history import attendance_workbook, is_issued, saved_files, slip_folders


def _download(path):
    st.download_button(
        f"下載 {path.name}",
        path.read_bytes(),
        file_name=path.name,
        key=f"record-{path}",
    )


def _folder_button(path):
    if os.name == "nt" and st.button(f"開啟 {path.name}", key=f"open-{path}"):
        os.startfile(path)
        return
    files = [item for item in path.iterdir() if item.is_file() and not item.name.startswith("~$")]
    if os.name == "nt" or not files:
        return
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as packed:
        for item in files:
            packed.write(item, item.name)
    st.download_button(
        f"下載 {path.name}.zip", buffer.getvalue(), file_name=f"{path.name}.zip", key=f"zip-{path}",
    )


def _audit(role):
    from payroll.core.access import visible_audit
    from payroll.core.config import home
    from payroll.staff.staff import pay_table_path
    path = home() / "data" / "payroll_audit.xlsx"
    if not path.exists():
        return
    import pandas as pd
    frame = pd.read_excel(path, engine="openpyxl")
    office_ids = set()
    table = pay_table_path("admin")
    if table.exists():
        office = pd.read_excel(table, engine="openpyxl")
        if "staff_id" in office.columns:
            office_ids = {str(value).strip() for value in office["staff_id"]}
    shown = visible_audit(frame, role, office_ids)
    if shown is None or not len(shown):
        return
    with st.expander("薪金調整紀錄"):
        st.dataframe(shown, hide_index=True, width="stretch")


def page_records():
    from app.access import current_role

    inject()
    show_logo()
    info, _readonly, _draft, _staff, _table = _context()
    page_header("月份紀錄", _month_label(info["key"]))
    from app.access import see_pay
    from payroll.core.access import hide_office_file
    if is_issued(info["key"]):
        st.caption("一月至十月的糧單、更表和考勤核對表保持原樣。這裡只打開已保存的檔案。")
    else:
        st.caption("這個月之後的出勤、更表和糧單會留在這個月的資料夾，之後仍可在這裡打開。")
    check = attendance_workbook(info["year"], info["month"])
    st.markdown("**考勤**")
    if check is None:
        st.caption("沒有找到這個月的考勤核對表。")
    else:
        _download(check)
    st.markdown("**這個月保存的檔案**")
    kept = [path for path in saved_files(info) if not hide_office_file(path.name, "admin" if see_pay("admin") else "hr")]
    if not kept:
        st.caption("GrainHR 還沒有這個月的計算檔。")
    for path in kept:
        _download(path)
    st.markdown("**糧單**")
    folders = slip_folders(info["year"], info["month"])
    if not folders:
        st.caption("沒有找到這個月的糧單資料夾。")
    for label, folder in folders:
        if hide_office_file(label, "admin" if see_pay("admin") else "hr"):
            continue
        files = [path for path in folder.iterdir() if path.is_file() and not path.name.startswith("~$")]
        with st.container(border=True):
            st.markdown(f"**{label}**")
            st.caption(f"{len(files)} 個檔案")
            _folder_button(folder)
            for path in sorted(files):
                if path.suffix.lower() in {".docx", ".xlsx"}:
                    _download(path)
    _audit(current_role())
