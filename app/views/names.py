"""Link a roster or DAKA spelling to one employee."""

from datetime import date

import streamlit as st

from app.components.cards import page_header
from app.context import _context, _month_label, _text
from payroll.attendance.daka import daka_names, load_daka
from payroll.attendance.lateness import link_groups
from payroll.attendance.matching import unmatched_names
from payroll.core.aliases import set_name_alias
from payroll.core.excel_io import read_excel
from payroll.staff.staff import _as_date, pay_table_path


def _tables():
    found = {}
    for book in ("bg", "md", "admin"):
        path = pay_table_path(book)
        if path.exists():
            found[book] = read_excel(path)
    return found


def _roster_names(info):
    path = info["system"] / "days.xlsx"
    if not path.exists():
        return []
    days = read_excel(path)
    if "Name" not in days.columns:
        return []
    return sorted({_text(name) for name in days["Name"] if _text(name)})


def _left_this_month(record, info):
    left = _as_date(record.get("leave_date"))
    if left is None:
        return False
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    return start <= left <= end


def _people(staff, info):
    """Current staff, plus people whose resignation date is in this month."""
    rows = []
    for record in staff.to_dict("records"):
        number = _text(record.get("employee_no"))
        if not number:
            continue
        resigned = _text(record.get("status")) == "已離職"
        if resigned and not _left_this_month(record, info):
            continue
        name = _text(record.get("name_zh")) or _text(record.get("name_en")) or number
        label = f"{number} {name}"
        if resigned:
            label = f"{label}（本月離職）"
        rows.append((number, label))
    return rows


def page_names():
    info, readonly, _draft, staff, _table = _context(payroll=False)
    page_header("名字配對", _month_label(info["key"]), purpose="把更表或打卡上的名字對到一位員工。")
    st.caption("更表或 DAKA 上的寫法對不上員工檔時，在這裡記成同一個人。本月離職的同事也可以選。別名存在公司設定，下次計算會用。")
    roster_names = _roster_names(info)
    punches = load_daka(info["daka"]) if info["daka"].exists() else {}
    if staff is not None and "part_time" in getattr(staff, "columns", []):
        part_time = staff[staff["part_time"].fillna(False).astype(bool)].to_dict("records")
    else:
        part_time = []
    links = link_groups(roster_names, staff, _tables(), part_time)
    seen_daka = daka_names(punches)
    if not roster_names and not seen_daka:
        st.info("這個月還沒有更表或 DAKA，所以沒有名字要配對。")
        return
    roster_left, daka_left = unmatched_names(roster_names, seen_daka, links)
    pending = [("更表", name) for name in roster_left] + [("DAKA", name) for name in daka_left]
    if not pending:
        st.success("這個月的更表和 DAKA 名字都已配對。")
        return
    st.caption(f"還有 {len(roster_left)} 個更表名字、{len(daka_left)} 個 DAKA 名字未配對。")
    labels = [f"{kind} · {name}" for kind, name in pending]
    picked = st.selectbox("未配對的名字", labels, key="alias-name")
    source = pending[labels.index(picked)][1] if picked in labels else pending[0][1]
    people = _people(staff, info)
    if not people:
        st.info("沒有可配對的同事。")
        return
    person_labels = [label for _number, label in people]
    chosen = st.selectbox("對應員工", person_labels, key="alias-person")
    number = people[person_labels.index(chosen)][0] if chosen in person_labels else people[0][0]
    if readonly:
        st.caption("另一位同事正在使用系統，現在不能儲存。")
        return
    if st.button("儲存別名", type="primary", key="alias-save"):
        try:
            set_name_alias(source, number)
        except SystemExit as error:
            st.error(str(error))
        else:
            st.toast(f"已把 {source} 配對到 {number}。")
            st.rerun()
