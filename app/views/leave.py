"""Leave balances for everyone, read only."""

import streamlit as st

from app.components.cards import page_header
from app.components.theme import inject, show_logo
from app.context import _context, _month_label
from payroll.staff.directory import staff_directory


def page_leave():
    inject()
    show_logo()
    info, _readonly, _draft, staff, _table = _context()
    page_header("假期", _month_label(info["key"]), "年假和休假餘額。這頁只供查看。")
    rows = staff_directory(info, staff)
    shown = []
    for row in rows:
        shown.append({
            "員工編號": row.get("employee_no", ""),
            "姓名": row.get("name", ""),
            "組別": row.get("group_label", ""),
            "年假": row.get("annual", ""),
            "休假": row.get("rest", ""),
            "年資": row.get("service", ""),
        })
    if not shown:
        st.info("沒有員工資料。")
        return
    st.dataframe(shown, hide_index=True, width="stretch")
