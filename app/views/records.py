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
    if st.button(f"開啟 {path.name}", key=f"open-{path}"):
        os.startfile(path)


def page_records():
    from app.lock import _user
    from payroll.core.settings import role_for

    inject()
    show_logo()
    info, _readonly, _draft, _staff, _table = _context()
    page_header("月份紀錄", _month_label(info["key"]))
    viewer = role_for(_user()) == "viewer"
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
    if viewer:
        return
    st.markdown("**這個月保存的檔案**")
    kept = saved_files(info)
    if not kept:
        st.caption("GrainHR 還沒有這個月的計算檔。")
    for path in kept:
        _download(path)
    st.markdown("**糧單**")
    folders = slip_folders(info["year"], info["month"])
    if not folders:
        st.caption("沒有找到這個月的糧單資料夾。")
    for label, folder in folders:
        files = [path for path in folder.iterdir() if path.is_file() and not path.name.startswith("~$")]
        with st.container(border=True):
            st.markdown(f"**{label}**")
            st.caption(f"{len(files)} 個檔案")
            _folder_button(folder)
            for path in sorted(files):
                if path.suffix.lower() in {".docx", ".xlsx"}:
                    _download(path)
