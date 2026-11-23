"""Saved months: issued slips stay put, and later months stay in the month folder."""

import io
import zipfile
from pathlib import Path

import streamlit as st

from app.components.cards import empty_state, page_header
from app.components.theme import inject, show_logo
from app.context import _context, _month_label
from payroll.core.excel_io import read_excel
from payroll.core.history import attendance_workbook, is_issued, saved_files, slip_folders

def _title(label):
    from payroll.core.settings import books
    if label == "md":
        return books().get("md") or "MD"
    if label == "全職":
        return "全職"
    return label


def _files(folder):
    try:
        found = [
            path for path in Path(folder).iterdir()
            if path.is_file() and not path.name.startswith("~$")
        ]
    except OSError:
        return []
    return sorted(found, key=lambda path: path.name)


def _download(path, key):
    target = Path(path)

    def read():
        return target.read_bytes()

    st.download_button(
        f"下載 {target.name}",
        data=read,
        file_name=target.name,
        key=key,
        on_click="ignore",
        icon=":material/download:",
        help="按下後才讀取檔案，頁面不會重新載入。",
    )


def zip_named(paths):
    """Pack these files only. A sibling in the same folder stays out."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as packed:
        for item in paths:
            path = Path(item)
            if path.is_file() and not path.name.startswith("~$"):
                packed.write(path, path.name)
    return buffer.getvalue()


def _zip_button(paths, key, name):
    chosen = list(paths)

    def read():
        return zip_named(chosen)

    st.download_button(
        "下載全部",
        data=read,
        file_name=f"{name}.zip",
        key=key,
        on_click="ignore",
        icon=":material/folder_zip:",
        help="按下後才把畫面上這幾份檔案打包。",
    )


def _size(paths):
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    if total >= 1024 * 1024:
        return f"{total / (1024 * 1024):.1f} MB"
    if total >= 1024:
        return f"{total / 1024:.0f} KB"
    return f"{total} B"


def _file_card(title, paths, key):
    if not paths:
        return
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(f"{len(paths)} 個檔案 · {_size(paths)}")
        documents = [path for path in paths if path.suffix.lower() in {".docx", ".xlsx"}]
        pdfs = [path for path in paths if path.suffix.lower() == ".pdf"]
        others = [path for path in paths if path not in documents and path not in pdfs]
        for path in documents + others:
            _download(path, f"{key}-{path.name}")
        if pdfs:
            box = st.expander(f"個別糧單（{len(pdfs)}）", on_change="rerun")
            if box.open:
                with box:
                    for path in pdfs:
                        _download(path, f"{key}-pdf-{path.name}")
        if len(paths) > 1:
            _zip_button(paths, f"{key}-zip", title)


def _audit(role):
    from payroll.core.access import visible_audit
    from payroll.core.config import home
    from payroll.staff.staff import pay_table_path

    box = st.expander("薪金調整紀錄", on_change="rerun")
    if not box.open:
        return
    with box:
        path = home() / "data" / "payroll_audit.xlsx"
        if not path.exists():
            st.caption("沒有薪金調整紀錄。")
            return
        frame = read_excel(path, engine="openpyxl")
        office_ids = set()
        table = pay_table_path("admin")
        if table.exists():
            office = read_excel(table, engine="openpyxl")
            if "staff_id" in office.columns:
                office_ids = {str(value).strip() for value in office["staff_id"]}
        shown = visible_audit(frame, role, office_ids)
        if shown is None or not len(shown):
            st.caption("沒有可以顯示的調整。")
            return
        st.dataframe(shown, hide_index=True, width="stretch", alt="薪金調整紀錄")


def page_records():
    from app.access import current_role, see_pay
    from payroll.core.access import hide_office_file

    inject()
    show_logo()
    info, _readonly, _draft, _staff, _table = _context()
    issued = is_issued(info["key"])
    page_header(
        "月份紀錄",
        _month_label(info["key"]),
        purpose="查看這個月已保存的出勤、更表和糧單。",
    )
    if issued:
        st.caption("這個月已經出糧。這裡只打開已保存的檔案，不會重新計算。")
    else:
        st.caption("這個月的出勤、更表和糧單會留在這個月的資料夾。")
    role = "admin" if see_pay("admin") else current_role()
    check = attendance_workbook(info["year"], info["month"])
    kept = [
        path for path in saved_files(info)
        if not hide_office_file(path.name, role)
    ]
    _file_card("考勤和計算檔", ([check] if check else []) + kept, f"kept-{info['key']}")
    folders = slip_folders(info["year"], info["month"])
    shown = False
    for label, folder in folders:
        title = _title(label)
        if hide_office_file(label, role) or hide_office_file(title, role):
            continue
        files = _files(folder)
        if not files:
            continue
        shown = True
        _file_card(title, files, f"{info['key']}-{label}")
    if check is None and not kept and not shown:
        empty_state(
            "這個月還沒有保存的檔案",
            "出糧完成後，糧單和考勤會出現在這裡。",
            "前往出糧",
            "pages/payout.py",
        )
    _audit(current_role())
