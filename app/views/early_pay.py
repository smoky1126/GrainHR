"""Pay one resigned person before the rest of the month."""

from datetime import date
from pathlib import Path

import streamlit as st

from app.components.format import hk
from payroll.core.config import parse_month
from payroll.core.labels import BOOKS
from payroll.pay.early import early_hold, issue_early, latest_early, month_leavers, open_people, quote_early
from payroll.pay.part_time import PT_BOOKS, build_pt, clip_days
from payroll.staff.staff import _text, load_staff


def _full_row(draft, person):
    if draft is None or len(draft) == 0 or "employee_no" not in draft.columns:
        return None
    hit = draft[draft["employee_no"].map(_text) == person["employee_no"]]
    if "book" in hit.columns:
        hit = hit[hit["book"].map(_text) == person["book"]]
    if hit.empty:
        return None
    return hit.iloc[0]


def _part_rows(info, people):
    if not any(person["kind"] == "part" for person in people):
        return {}
    built = {row["employee_no"]: row for row in build_pt(info, load_staff())}
    clipped = {}
    for person in people:
        if person["kind"] != "part":
            continue
        row = built.get(person["employee_no"])
        if row is None:
            continue
        clipped[person["employee_no"]] = clip_days(row, person["leave_date"], row, info)
        clipped[person["employee_no"]]["_pay_this"] = row["pay_this"]
    return clipped


@st.dialog("提前出糧")
def confirm_early(month_key, employee_no, book, kind, name, pay_iso, amount_text, last_iso=""):
    st.write(f"現在為 {name} 出糧，出糧日期是 {pay_iso}。")
    if last_iso:
        st.write(f"計至最後工作日 {last_iso}。還沒打卡的日子按更表計算。")
    if amount_text:
        st.write(f"預計過數 {amount_text}。月結時不會再發一次。")
    else:
        st.write("月結時不會再發一次。")
    if not st.button("確定出糧", type="primary", key="yes-early"):
        return
    info = parse_month(month_key)
    last_day = date.fromisoformat(last_iso) if last_iso else None
    try:
        with st.spinner("正在製作糧單"):
            issue_early(
                info, employee_no, date.fromisoformat(pay_iso),
                book=book, kind=kind, last_day=last_day,
            )
    except PermissionError:
        st.error("請先關閉已打開的糧單或提前出糧紀錄，然後再試。")
        return
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.toast(f"已為 {name} 提前出糧")
    st.rerun()


def _card(info, draft, person, record, part_rows, readonly):
    kind = "兼職" if person["kind"] == "part" else "全職"
    books = PT_BOOKS if person["kind"] == "part" else BOOKS
    left = person["leave_date"]
    left_text = left.isoformat() if hasattr(left, "isoformat") else _text(left)
    key = f"{info['key']}-{person['book']}-{person['employee_no']}"
    with st.container(border=True):
        st.markdown(f"**{person['name']}**")
        st.caption(f"{kind} · {books.get(person['book'], person['book'])} · {person['employee_no']} · 離職日期 {left_text}")
        if record is not None:
            amount = hk(record.get("net"))
            when = _text(record.get("pay_date"))
            detail = f"出糧日期 {when}" if when else "已記錄"
            if amount:
                detail = f"{detail}，過數 {amount}"
            st.success(f"{detail}。月結不會再發。", title="已提前出糧")
            path = Path(_text(record.get("slip")))
            if path.is_file():
                st.download_button(
                    "下載這份糧單",
                    path.read_bytes(),
                    file_name=path.name,
                    key=f"early-down-{key}",
                )
            return
        amount = None
        reason = ""
        if person["kind"] == "part":
            row = part_rows.get(person["employee_no"])
            if row is None:
                reason = "這個人不在本月兼職糧單。"
            elif row.get("_pay_this") != "Y":
                reason = "這個人本月不發薪。"
            elif float(row.get("total_hours") or 0) <= 0:
                reason = "到離職日沒有工時。請先核對出勤。"
            else:
                amount = row.get("transfer")
        else:
            row = _full_row(draft, person)
            if row is None:
                reason = "請先核對出勤，才能計算這個人的薪金。"
            elif not bool(row.get("pay_this")):
                reason = "這個人本月不發薪。"
            else:
                reason = early_hold(row)
                amount = row.get("net")
        amount_text = hk(amount)
        if amount_text:
            st.write(f"預計薪金 {amount_text}")
        if person["kind"] == "full" and row is not None:
            _breakdown(row, office=person["book"] == "admin")
            note = _text(row.get("review"))
            if note and note.lower() != "nan":
                st.caption(note)
            _adjustment(info, row, person, readonly)
        if hasattr(left, "year") and left >= date.today():
            st.caption("最後工作日之前可以先出。還沒打卡的日子按更表計算，不當作缺卡。")
        if reason:
            st.warning(reason)
        actions = st.container(horizontal=True, vertical_alignment="bottom")
        with actions:
            picked = st.date_input(
                "出糧日期",
                value=date.today(),
                disabled=readonly,
                format="YYYY-MM-DD",
                key=f"early-date-{key}",
            )
            go = st.button(
                "提前出糧",
                type="primary",
                disabled=readonly or bool(reason),
                key=f"early-go-{key}",
            )
        if go:
            confirm_early(
                info["key"], person["employee_no"], person["book"], person["kind"],
                person["name"], picked.isoformat(), amount_text,
                left.isoformat() if hasattr(left, "isoformat") else "",
            )


def _breakdown(row, office=False):
    """Show the pieces already inside a last payment."""
    leave_pay = _amount(row.get("leave_pay"))
    if leave_pay:
        st.caption(f"未用年假 {hk(leave_pay)}，已計入預計薪金。日薪是全月基本薪金乘 12 再除以 365。")
    hours = _amount(row.get("ot_hours_detected"))
    overtime = _amount(row.get("ot_pay"))
    if office and hours:
        st.caption(f"加班 {hours:g} 小時。寫字樓沒有加班費。")
    elif hours or overtime:
        st.caption(f"加班 {hours:g} 小時，{hk(overtime) or 'HK$ 0.00'}。店舖和工場沒有選補鐘時，最後一次出糧會計入。")
    unpaid = _amount(row.get("unpaid_amount"))
    if unpaid:
        st.caption(f"無薪假已扣 {hk(unpaid)}。")
    deducted = []
    for label, key in (("租金", "rent"), ("水費", "water"), ("電費", "electricity")):
        value = _amount(row.get(key))
        if value:
            deducted.append(f"{label} {hk(value)}")
    if deducted:
        st.caption("內地勞工已扣：" + "，".join(deducted) + "。")
    late = _amount(row.get("late_mins_detected"))
    if late > 5:
        st.caption(f"遲到 {late:g} 分鐘。遲到不扣基本薪金，只會沒有勤工獎。離職這個月本來就沒有本月勤工獎。")
    allowance = _amount(row.get("allowance_amount"))
    if allowance:
        st.caption(f"交通／健康津貼 {hk(allowance)}。這是另一筆過數，不在預計薪金裡。")
        st.write(f"今次共付 {hk(_amount(row.get('net')) + allowance)}")


def _amount(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _adjustment(info, row, person, readonly):
    """Leave days and allowances for this one early slip."""
    staff_id = _text(row.get("staff_id"))
    if not staff_id:
        return
    from payroll.pay.payroll import _shown_allowances
    from payroll.staff.staff import ensure_pay_table

    transport, health = 0.0, 0.0
    try:
        table = ensure_pay_table(book=person["book"])
        matched = table[table["employee_no"].map(_text) == person["employee_no"]]
        if len(matched):
            transport, health = _shown_allowances(matched.iloc[0])
    except SystemExit:
        transport, health = 0.0, 0.0
    balances = []
    for label_key, days_key in (("al_1_label", "al_1_days"), ("al_2_label", "al_2_days")):
        label = _text(row.get(label_key))
        if label:
            balances.append(f"{label} {_amount(row.get(days_key)):g} 日")
    if balances:
        st.caption("未使用年假：" + "；".join(balances))
    st.caption("未用年假已按全月日薪乘餘下日數計入薪金。代通知金才填在「其他調整」。年假日數只改糧單上的結餘。")
    prefix = f"{info['key']}-{person['book']}-{staff_id}"
    unpaid = st.number_input(
        "無薪假（日）", value=_amount(row.get("unpaid_days")), step=0.5, disabled=readonly,
        help="扣薪的日數。", key=f"early-unpaid-{prefix}",
    )
    annual = st.number_input(
        "年假（日）", value=_amount(row.get("annual_taken")), step=0.5, disabled=readonly,
        help="這個月已放的年假。未放年假的補償不要填在這裡。", key=f"early-annual-{prefix}",
    )
    transport_value = st.number_input(
        "交通津貼", value=_amount(transport), step=1.0, disabled=readonly,
        help="實額，加進糧單津貼。", key=f"early-transport-{prefix}",
    )
    health_value = st.number_input(
        "健康津貼", value=_amount(health), step=1.0, disabled=readonly,
        help="實額，和交通津貼相加。", key=f"early-health-{prefix}",
    )
    extra = st.number_input(
        "其他調整", value=_amount(row.get("manual_delta")), step=1.0, disabled=readonly,
        help="代通知金。正數是加，負數是減。未用年假已經按日薪計入薪金，不要在這裡再填一次。強積金不會跟着改。",
        key=f"early-delta-{prefix}",
    )
    if readonly or not st.button("儲存調整", key=f"early-save-{prefix}"):
        return
    from payroll.core.config import book_info
    from payroll.pay.review import save_one, set_allowances
    try:
        save_one(book_info(info, person["book"]), staff_id, {
            "unpaid_days": float(unpaid),
            "annual_taken": float(annual),
            "manual_delta": float(extra),
        })
        set_allowances(info, person["book"], person["employee_no"], float(transport_value), float(health_value))
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.toast("已儲存調整")
    st.rerun()


def _plan_ahead(info, waiting, readonly):
    st.markdown("**最後工作日之前先計算**")
    st.caption("未寫離職也可以。選最後工作日，還沒打卡的日子按更表計算。")
    labels = [f"{person['name']}（{person['employee_no']}）" for person in waiting]
    chosen = st.selectbox("同事", labels, key=f"early-who-{info['key']}")
    person = waiting[labels.index(chosen)]
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    default = date.today()
    if default < start or default > end:
        default = end
    picked_last = st.date_input(
        "最後工作日",
        value=default,
        min_value=start,
        max_value=end,
        format="YYYY-MM-DD",
        disabled=readonly,
        key=f"early-last-{info['key']}",
    )
    pay_on = st.date_input(
        "出糧日期",
        value=date.today(),
        format="YYYY-MM-DD",
        disabled=readonly,
        key=f"early-payon-{info['key']}",
    )
    quote = st.session_state.get("early-quote")
    same = (
        isinstance(quote, dict)
        and quote.get("key") == info["key"]
        and quote.get("employee_no") == person["employee_no"]
        and quote.get("book") == person["book"]
        and quote.get("last") == picked_last.isoformat()
    )
    if not same:
        quote = None
    actions = st.container(horizontal=True, vertical_alignment="bottom")
    with actions:
        if st.button("計算薪金", disabled=readonly, key=f"early-quote-{info['key']}"):
            try:
                with st.spinner("正在計算"):
                    quote = quote_early(
                        info, person["employee_no"], picked_last,
                        book=person["book"], kind=person["kind"],
                    )
            except SystemExit as error:
                st.error(str(error))
            else:
                st.session_state["early-quote"] = quote
                st.rerun()
        amount_text = hk(quote.get("net")) if quote else ""
        if quote and st.button(
            "提前出糧",
            type="primary",
            disabled=readonly or bool(quote.get("reason")),
            key=f"early-issue-{info['key']}",
        ):
            confirm_early(
                info["key"], person["employee_no"], person["book"], person["kind"],
                person["name"], pay_on.isoformat(), amount_text, picked_last.isoformat(),
            )
    if not quote:
        return
    if quote.get("period"):
        st.caption(quote["period"])
    if amount_text:
        st.write(f"預計過數 {amount_text}")
    if quote.get("prior"):
        st.caption("還沒打卡的日子按更表計算，不當作缺卡。")
    if quote.get("reason"):
        st.warning(quote["reason"])


def early_section(info, draft, readonly):
    try:
        people = month_leavers(info)
        waiting = open_people(info)
    except SystemExit as error:
        st.error(str(error))
        return
    if not people and not waiting:
        return
    st.markdown("**離職提前出糧**")
    st.caption("可以在最後工作日之前幾天先計算和出糧。月結時不會再發一次。")
    try:
        paid = latest_early(info)
        part_rows = _part_rows(info, people)
    except SystemExit as error:
        st.error(str(error))
        return
    for person in people:
        _card(info, draft, person, paid.get(person["employee_no"]), part_rows, readonly)
    if waiting:
        _plan_ahead(info, waiting, readonly)
