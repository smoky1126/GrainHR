"""Link a roster or DAKA spelling to one employee."""

from datetime import date

import streamlit as st

from app.components.cards import page_header
from app.context import _context, _month_label, _text
from payroll.attendance.daka import daka_names, load_daka
from payroll.attendance.lateness import link_groups
from payroll.attendance.matching import unmatched_names
from payroll.core.aliases import LEFT, drop_name_alias, ignore_left_name, set_name_alias
from payroll.core.excel_io import read_excel
from payroll.core.settings import name_aliases, shop_label
from payroll.staff.staff import _as_date, pay_table_path


def _tables():
    found = {}
    for book in ("bg", "md", "admin"):
        path = pay_table_path(book)
        if path.exists():
            found[book] = read_excel(path)
    return found


def _days(info):
    path = info["system"] / "days.xlsx"
    if not path.exists():
        return None
    days = read_excel(path)
    if "Name" not in getattr(days, "columns", []):
        return None
    return days


def _roster_names(days):
    if days is None:
        return []
    return sorted({_text(name) for name in days["Name"] if _text(name)})


def name_sources(days, punches):
    """Shop names from the roster, and DAKA places, for each spelling."""
    roster = {}
    if days is not None:
        for _, row in days.iterrows():
            name = _text(row.get("Name"))
            if not name:
                continue
            roster.setdefault(name, set())
            shop = shop_label(_text(row.get("Chosen shop")))
            if shop:
                roster[name].add(shop)
    daka = {}
    for key, punch in (punches or {}).items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        name = _text(key[0])
        if not name:
            continue
        daka.setdefault(name, set())
        place = _text((punch or {}).get("in_place") or (punch or {}).get("place"))
        if place:
            daka[name].add(place)
    return roster, daka


def where_found(name, roster, daka):
    """Where this month's spelling was seen, including which shop roster."""
    parts = []
    if name in roster:
        shops = "、".join(sorted(roster.get(name) or []))
        parts.append("更表：" + (shops or "未記店鋪"))
    if name in daka:
        places = "、".join(sorted(place for place in daka.get(name) or [] if place))
        parts.append("DAKA" + (f"：{places}" if places else ""))
    return "；".join(parts)


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


def _ignored(roster_names, daka_names, roster_shops, daka_places, readonly):
    aliases = name_aliases()
    names = sorted({name for name in list(roster_names) + list(daka_names) if aliases.get(name) == LEFT})
    if not names:
        return
    with st.expander(f"已忽略的離職名字（{len(names)}）"):
        st.caption("試工一日後離職的名字在這裡。恢復之後會回到未配對。")
        for name in names:
            found = where_found(name, roster_shops, daka_places)
            label = name + (f"：{found}" if found else "")
            if readonly:
                st.write(label)
                continue
            if st.button(f"恢復 {label}", key=f"alias-restore-{name}"):
                try:
                    drop_name_alias(name)
                except SystemExit as error:
                    st.error(str(error))
                else:
                    st.toast(f"已恢復 {name}。")
                    st.rerun()


def page_names():
    info, readonly, _draft, staff, _table = _context(payroll=False)
    page_header("名字配對", _month_label(info["key"]), purpose="把更表或打卡上的名字對到一位員工。")
    st.caption("更表或 DAKA 上的寫法對不上員工檔時，在這裡記成同一個人。本月離職的同事也可以選。別名存在公司設定，下次計算會用。")
    days = _days(info)
    roster_names = _roster_names(days)
    punches = load_daka(info["daka"]) if info["daka"].exists() else {}
    roster_shops, daka_places = name_sources(days, punches)
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
        st.success("這個月沒有未配對的名字。")
        _ignored(roster_names, seen_daka, roster_shops, daka_places, readonly)
        return
    st.caption(f"還有 {len(roster_left)} 個更表名字、{len(daka_left)} 個 DAKA 名字未配對。")
    labels = []
    for kind, name in pending:
        found = where_found(name, roster_shops, daka_places)
        labels.append(f"{kind} · {name}" + (f" · {found}" if found else ""))
    picked = st.selectbox("未配對的名字", labels, key="alias-name")
    source = pending[labels.index(picked)][1] if picked in labels else pending[0][1]
    found = where_found(source, roster_shops, daka_places)
    if found:
        st.caption(f"出現位置：{found}")
    people = _people(staff, info)
    person_labels = [label for _number, label in people]
    chosen = None
    if person_labels:
        chosen = st.selectbox("對應員工", person_labels, key="alias-person")
    else:
        st.info("沒有可配對的同事。試工後離職的名字仍可標成不用配對。")
    if readonly:
        st.caption("另一位同事正在使用系統，現在不能儲存。")
    else:
        save, ignore = st.columns(2)
        if person_labels and save.button("儲存別名", type="primary", key="alias-save"):
            number = people[person_labels.index(chosen)][0] if chosen in person_labels else people[0][0]
            try:
                set_name_alias(source, number)
            except SystemExit as error:
                st.error(str(error))
            else:
                st.toast(f"已把 {source} 配對到 {number}。")
                st.rerun()
        if ignore.button("這人已離職，不用配對", key="alias-ignore"):
            try:
                ignore_left_name(source)
            except SystemExit as error:
                st.error(str(error))
            else:
                st.toast(f"已把 {source} 標成已離職，不再配對。")
                st.rerun()
    _ignored(roster_names, seen_daka, roster_shops, daka_places, readonly)
