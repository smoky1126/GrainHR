"""Staff master: eight groups, one profile, and the edit dialogs."""

from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st

from app.components.cards import page_header
from app.components.format import hk
from payroll.staff.directory import GROUPS, staff_directory
from payroll.staff.staff import _as_date, _text, next_employee_no, staff_options
from payroll.staff.staff_write import (
    add_staff, edit_staff, resign_staff, salary_history_path, set_hourly_rate, set_monthly_salary,
)
from payroll.staff.staff_write import _log_path

from payroll.core.history import is_issued
from payroll.core.settings import prefixes

_PREFIX = prefixes()
_PERSONAL = (
    ("gender", "性別"), ("birth_date", "出生日期"), ("marital", "婚姻狀況"),
    ("hkid", "身份證號碼"), ("phone", "手提電話"), ("address", "住址"),
    ("bank_name", "銀行"), ("bank_account", "銀行賬號"),
    ("emergency_name", "緊急聯絡人"), ("emergency_relation", "關係"), ("emergency_phone", "聯絡電話"),
    ("emergency_name_2", "緊急聯絡人 2"), ("emergency_relation_2", "關係 2"), ("emergency_phone_2", "聯絡電話 2"),
    ("contract_no", "合約編號"), ("permit_address", "批准信地址"),
)


def _sheet_for(group):
    return "內地勞工" if group in {"bg_esl", "md_esl"} else "BG & MD"


def _iso(value):
    found = _as_date(value)
    return found.isoformat() if found else ""


def _choices(options, name, current=""):
    values = list(options.get(name, []))
    if current and current not in values:
        values.insert(0, current)
    return [""] + values


def _locked_note(readonly, demo):
    if demo:
        st.caption("示範模式只顯示員工檔，不能修改。")
        return True
    if readonly:
        st.caption("另一位同事正在使用系統，現在不能修改員工檔。")
        return True
    return False


def _save(action):
    with st.spinner("正在寫入員工檔…"):
        action()
    stamp = date.today().strftime("%Y%m%d")
    st.toast(f"已寫入員工檔，版本是 Staff_info_{stamp}。")
    st.rerun()


def _role():
    from app.lock import _user
    from payroll.core.settings import role_for
    return role_for(_user())


def _see_private():
    return _role() in {"admin", "hr"}


def _office_open(group):
    from app.access import see_pay
    return see_pay(group)


def _history(employee_no, see_private=True):
    from payroll.core.excel_io import read_excel
    frames = []
    path = _log_path()
    if path.exists():
        changes = read_excel(path, engine="openpyxl")
        changes = changes[changes["employee_no"].map(_text) == employee_no]
        if not changes.empty:
            if not see_private and "field" in changes.columns:
                hidden = {"銀行賬號", "銀行名稱"}
                changes = changes[~changes["field"].map(_text).isin(hidden)]
            if not changes.empty:
                frames.append(changes.assign(來源="員工檔"))
    pay = salary_history_path()
    if see_private and pay.exists():
        salary = read_excel(pay, engine="openpyxl")
        salary = salary[salary["employee_no"].map(_text) == employee_no]
        if not salary.empty:
            frames.append(salary.assign(來源="薪金"))
    if not frames:
        st.caption("這個人還沒有修改紀錄。")
        return
    st.dataframe(pd.concat(frames, ignore_index=True), hide_index=True, width="stretch")


def _profile(row, info, locked):
    """Show one person. Returns which dialog button was pressed on this run."""
    st.subheader(f"{row['employee_no']} {row['name_zh'] or row['name_en']}")
    work, pay, personal, history = st.tabs(["工作", "薪金及假期", "個人資料", "修改記錄"])
    action = None
    with work:
        left, right = st.columns(2)
        left.write(f"職位：{row['position'] or '—'}")
        left.write(f"部門：{row['department'] or '—'}")
        left.write(f"就業形式：{row['employment'] or '—'}")
        left.write(f"入職日期：{_iso(row['join_date']) or '—'}")
        right.write(f"在職：{row['service_days'] or '—'}")
        right.write(f"離職日期：{_iso(row['leave_date']) or '—'}")
        right.write(f"合約完結：{_iso(row['contract_end']) or '—'}")
        right.write(f"狀況：{row['status']}")
        if st.button("修改資料", key="staff-edit", disabled=locked):
            action = "edit"
        if row["status"] == "在職" and st.button("離職", key="staff-resign", disabled=locked):
            action = "resign"
    with pay:
        left, right = st.columns(2)
        office_open = _office_open(row.get("group"))
        if office_open:
            if row["pay_basis"] == "時薪":
                left.metric("時薪", "—" if row["salary"] is None else hk(row["salary"]))
            else:
                left.metric("月薪", "—" if row["salary"] is None else hk(row["salary"]))
        else:
            left.caption("寫字樓薪金只顯示給管理員。")
        left.metric("本年年假", "—" if row["annual_entitled"] is None else f"{row['annual_entitled']} 日")
        left.metric("本年已用年假", "—" if row["annual_taken"] is None else f"{row['annual_taken']:g} 日")
        right.metric("剩餘年假", "—" if row["annual"] is None else f"{row['annual']:g} 日")
        right.metric("剩餘休假", "—" if row["rest"] is None else f"{row['rest']:g} 日")
        if office_open and st.button(
            "調整薪金", key="staff-salary",
            disabled=locked or is_issued(info["key"]),
        ):
            action = "salary"
        if is_issued(info["key"]):
            st.caption("這個月已經出糧，不能改這個月的薪金。員工資料和離職仍可修改。")
    with personal:
        for key, label in _PERSONAL:
            if not _office_open(row.get("group")) and key in {"bank_name", "bank_account"}:
                continue
            value = row.get(key)
            shown = _iso(value) if key == "birth_date" else _text(value)
            if shown:
                st.write(f"{label}：{shown}")
    with history:
        _history(row["employee_no"], see_private=_office_open(row.get("group")))
    return action


def _field_map(group):
    join = "到職日期" if group in {"bg_esl", "md_esl"} else "入職日期"
    return [
        ("員工名稱", "text"), ("英文姓名", "text"), ("性別", "性別"), ("出生日期", "date"),
        ("婚姻狀況", "婚姻狀況"), ("住址", "text"), ("身份證號碼", "text"), ("手提電話號碼", "text"),
        ("職位", "text"), ("就業形式", "就業形式"), (join, "date"), ("部門", "部門"),
        ("銀行名稱", "銀行名稱"), ("銀行賬號", "text"),
        ("緊急聯絡人", "text"), ("緊急聯絡人關係", "text"), ("緊急聯絡人電話號碼", "text"),
        ("合約編號", "text"), ("批准信地址", "text"), ("合約完結日期", "date"),
    ]


def _row_value(row, column):
    mapping = {
        "員工名稱": "roster_hint", "英文姓名": "name_en", "性別": "gender", "出生日期": "birth_date",
        "婚姻狀況": "marital", "住址": "address", "身份證號碼": "hkid", "手提電話號碼": "phone",
        "職位": "position", "就業形式": "employment", "入職日期": "join_date", "到職日期": "join_date",
        "部門": "department", "銀行名稱": "bank_name", "銀行賬號": "bank_account",
        "緊急聯絡人": "emergency_name", "緊急聯絡人關係": "emergency_relation",
        "緊急聯絡人電話號碼": "emergency_phone", "合約編號": "contract_no",
        "批准信地址": "permit_address", "合約完結日期": "contract_end",
    }
    key = mapping.get(column, "")
    return row.get(key) if key else ""


@st.dialog("新增員工")
def _add_dialog(group, staff):
    options = staff_options()
    sheet = _sheet_for(group)
    suggested = next_employee_no(staff, _PREFIX.get(group, "A"))
    number = st.text_input("員工編號", value=suggested)
    name = st.text_input("中文姓名")
    fields = _collect(options, group, {}, "add", hide_bank=not _office_open(group))
    if st.button("確定新增", type="primary"):
        if _text(number) == "" or _text(name) == "":
            st.error("請填員工編號和中文姓名。")
            return
        try:
            _save(lambda: add_staff(sheet, number, name, fields))
        except SystemExit as error:
            st.error(str(error))


@st.dialog("修改資料")
def _edit_dialog(row, staff):
    options = staff_options()
    fields = _collect(options, row["group"], row, "edit", hide_bank=not _office_open(row.get("group")))
    original = {_name: _original(row, _name) for _name, _kind in _field_map(row["group"])}
    if st.button("確定修改", type="primary"):
        changed = {key: value for key, value in fields.items() if value != original.get(key, "")}
        if not changed:
            st.rerun()
        try:
            _save(lambda: edit_staff(row["sheet"] or _sheet_for(row["group"]), row["employee_no"], row["name_zh"], changed))
        except SystemExit as error:
            st.error(str(error))


def _original(row, column):
    value = _row_value(row, column)
    if column in {"出生日期", "入職日期", "到職日期", "合約完結日期"}:
        return _iso(value)
    return _text(value)


def _collect(options, group, row, prefix, hide_bank=False):
    fields = {}
    hidden = {"銀行名稱", "銀行賬號"}
    for column, kind in _field_map(group):
        if hide_bank and column in hidden:
            continue
        current = _original(row, column) if row else ""
        key = f"staff-{prefix}-{column}"
        if kind == "text":
            fields[column] = st.text_input(column, value=current, key=key)
        elif kind == "date":
            picked = st.date_input(
                column, value=date.fromisoformat(current) if current else None, key=key, format="YYYY-MM-DD",
            )
            fields[column] = picked.isoformat() if isinstance(picked, date) else ""
        else:
            choices = _choices(options, kind, current)
            fields[column] = st.selectbox(
                column, choices, index=choices.index(current) if current in choices else 0, key=key,
            )
    return fields


@st.dialog("離職")
def _resign_dialog(row):
    picked = st.date_input("離職日期", value=date.today(), format="YYYY-MM-DD")
    if st.button("確定離職", type="primary"):
        try:
            _save(lambda: resign_staff(
                row["sheet"] or _sheet_for(row["group"]), row["employee_no"], row["name_zh"], picked.isoformat(),
            ))
        except SystemExit as error:
            st.error(str(error))


@st.dialog("調整薪金")
def _salary_dialog(row, info):
    label = "新時薪" if row["pay_basis"] == "時薪" else "新月薪"
    amount = st.number_input(label, min_value=0.0, step=1.0, format="%.2f")
    if st.button("確定", type="primary"):
        try:
            with st.spinner("正在寫入薪金…"):
                if row["pay_basis"] == "時薪":
                    set_hourly_rate(info, row["employee_no"], amount)
                else:
                    set_monthly_salary(row["book_key"], row["employee_no"], amount)
            st.session_state.pop("draft", None)
            st.toast("已更新薪金。")
            st.rerun()
        except SystemExit as error:
            st.error(str(error))


def _export(rows):
    from payroll.core.access import scrub_office_row
    frame = pd.DataFrame([scrub_office_row(row, _role()) for row in rows])
    secret = set()
    keep = [column for column in (
        "employee_no", "name_zh", "name_en", "group_label", "position", "department",
        "status", "join_date", "leave_date", "service_days", "salary", "pay_basis",
        "annual_entitled", "annual_taken", "annual", "rest",
        "phone", "bank_name",
    ) if column in frame.columns and column not in secret]
    from payroll.core.excel_io import safe_frame
    buffer = BytesIO()
    safe_frame(frame[keep]).to_excel(buffer, index=False)
    st.download_button("下載員工總表", buffer.getvalue(), file_name="員工總表.xlsx", key="staff-export")


def render(info, readonly, staff, demo, month_label):
    page_header("員工總表", month_label, purpose="查看員工資料。寫字樓薪金只顯示給管理員。")
    locked = _locked_note(readonly, demo)
    st.caption(
        "入職、離職、職位和個人資料寫回員工檔。月薪和時薪寫入所選月份的薪金表。"
        "本年年假：第一年 10 日，第二年 12 日，之後 14 日。"
        "剩餘年假和剩餘休假來自結餘。本年已用年假來自假期紀錄。"
    )
    try:
        rows = staff_directory(info, staff)
    except SystemExit as error:
        st.error(str(error))
        return
    through = max((row["leave_through"] for row in rows), default=0)
    if through:
        st.caption(f"假期紀錄計至 {info['year']}年{through}月。在職日數計至所選月份月底；已離職則計至離職日。")
    labels = {key: label for key, label in GROUPS}
    counts = {
        key: sum(row["group"] == key and row["status"] == "在職" for row in rows)
        for key, _label in GROUPS
    }
    options = [f"{labels[key]} {counts[key]}" for key, _label in GROUPS]
    if any(not row["group"] for row in rows):
        options.append("未分類")
    picked = st.segmented_control("組別", options, default=options[0], key="staff-group") or options[0]
    group_key = ""
    for key, _label in GROUPS:
        if picked.startswith(labels[key]):
            group_key = key
            break
    filters = st.columns([1, 2, 1])
    with filters[0]:
        status = st.segmented_control("狀況", ["全部", "在職", "已離職"], default="在職", key="staff-status") or "在職"
    with filters[1]:
        query = st.text_input("搜尋姓名或員工編號", key="staff-query")
    with filters[2]:
        add_clicked = st.button("新增員工", type="primary", disabled=locked, key="staff-add")
    needle = _text(query).lower()
    shown = [
        row for row in rows
        if row["group"] == group_key
        and (status == "全部" or row["status"] == status)
        and (not needle or needle in f"{row['employee_no']} {row['name_zh']} {row['name_en']}".lower())
    ]
    table = pd.DataFrame(shown)
    if table.empty:
        st.info("這個組別沒有符合的員工。")
    else:
        from payroll.core.access import scrub_office_row
        view = pd.DataFrame([scrub_office_row(row, _role()) for row in shown]).rename(columns={
            "employee_no": "員工編號", "name_zh": "中文姓名", "name_en": "英文姓名",
            "position": "職位", "department": "部門", "status": "狀況",
            "service_days": "在職", "salary": "薪金", "pay_basis": "計薪",
        })
        order = ["員工編號", "中文姓名", "英文姓名", "職位", "部門", "狀況", "在職", "薪金", "計薪"]
        st.dataframe(
            view, hide_index=True, width="stretch",
            column_order=order,
        )
    if shown:
        _export(shown)
    # A dialog stays open on its own after this run. Calling it again from a
    # saved flag opens a second dialog and Streamlit rejects the page.
    for stale in ("staff_add", "staff_edit", "staff_resign", "staff_salary"):
        st.session_state.pop(stale, None)
    person = None
    action = None
    if shown:
        labels_people = [f"{row['employee_no']} {row['name_zh'] or row['name_en']}" for row in shown]
        choice = st.selectbox("員工", labels_people, key="staff-person")
        person = shown[labels_people.index(choice)] if choice in labels_people else shown[0]
        action = _profile(person, info, locked)
    if add_clicked:
        _add_dialog(group_key, staff)
    elif person is not None and action == "edit":
        _edit_dialog(person, staff)
    elif person is not None and action == "resign":
        _resign_dialog(person)
    elif person is not None and action == "salary":
        _salary_dialog(person, info)


def page_staff():
    from app.context import DEMO, _context, _month_label

    info, readonly, _draft, people, _table = _context()
    render(info, readonly, people, demo=DEMO, month_label=_month_label(info["key"]))
