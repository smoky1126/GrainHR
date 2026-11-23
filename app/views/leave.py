"""Leave balances for one group at a time."""

import streamlit as st

from app.components.cards import page_header
from app.components.theme import inject, show_logo
from app.context import _context, _month_label
from payroll.staff.directory import GROUPS, staff_directory


def page_leave():
    inject()
    show_logo()
    info, _readonly, _draft, staff, _table = _context(payroll=False)
    page_header("假期", _month_label(info["key"]), "年假和休假餘額。這頁只供查看。")
    try:
        rows = staff_directory(info, staff)
    except SystemExit as error:
        st.error(str(error))
        return
    labels = {key: label for key, label in GROUPS}
    counts = {key: sum(row["group"] == key for row in rows) for key, _label in GROUPS}
    options = [f"{labels[key]} {counts[key]}" for key, _label in GROUPS]
    if any(not row["group"] for row in rows):
        options.append(f"未分類 {sum(not row['group'] for row in rows)}")
    picked = st.segmented_control("組別", options, default=options[0], key="leave-group") or options[0]
    group_key = ""
    for key, _label in GROUPS:
        if picked.startswith(f"{labels[key]} "):
            group_key = key
            break
    shown = [
        {
            "員工編號": row.get("employee_no", ""),
            "姓名": row.get("name", ""),
            "年假": row.get("annual", ""),
            "休假": row.get("rest", ""),
            "年資": row.get("service", ""),
        }
        for row in rows
        if row.get("group") == group_key
    ]
    if not shown:
        st.info("這個組別沒有員工。")
        return
    st.dataframe(shown, hide_index=True, width="stretch")
