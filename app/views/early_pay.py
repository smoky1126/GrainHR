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


def _slip_file(info, draft, person, record):
    """The download. Every slip is a PDF with the logo on top."""
    stored = Path(_text(record.get("slip")))
    pdf = stored.with_suffix(".pdf") if stored.suffix else None
    row = _full_row(draft, person)
    if row is not None and pdf is not None:
        from payroll.core.config import book_info
        from payroll.documents.slip_pdf import write_office_pdf
        try:
            booked = book_info(info, person["book"])
            booked["pay_date_override"] = _text(record.get("pay_date"))
            written = write_office_pdf(pdf, row, booked)
        except (OSError, SystemExit):
            written = None
        if written is not None:
            if person["book"] == "admin":
                try:
                    from payroll.documents.slips_admin import refresh_leave_dates
                    xlsx = stored if stored.suffix.lower() == ".xlsx" else pdf.with_suffix(".xlsx")
                    refresh_leave_dates(xlsx, row)
                except (OSError, SystemExit):
                    pass
            return written
    if pdf is not None and pdf.is_file():
        return pdf
    return stored if stored.is_file() else None


def _offer_slip(info, person, row, pay_date, readonly, key):
    """Transaction numbers and the PDF, the same as an issued slip."""
    if row is None or person.get("kind") == "part":
        return
    staff_id = _text(row.get("staff_id")) or _text(person.get("staff_id"))
    prefix = f"{info['key']}-{person['book']}-{staff_id or person['employee_no']}"
    salary_ref = _saved_text(
        "薪金交易編號", f"early-ref-{prefix}", _text(row.get("salary_reference")), readonly,
    )
    allowance_ref = _saved_text(
        "津貼交易編號", f"early-allow-ref-{prefix}", _text(row.get("allowance_reference")), readonly,
    )
    st.caption("薪金和津貼是兩次過數。編號會印在糧單的自動轉賬一行。沒有津貼就讓津貼編號留空。")
    if staff_id and not readonly and st.button("儲存交易編號", key=f"slip-ref-save-{prefix}"):
        from payroll.core.config import book_info
        from payroll.pay.review import save_one
        try:
            save_one(book_info(info, person["book"]), staff_id, {
                "salary_reference": salary_ref.strip(),
                "allowance_reference": allowance_ref.strip(),
            })
        except SystemExit as error:
            st.error(str(error))
            return
        st.session_state["dirty"] = True
        st.session_state.pop("drafts", None)
        st.session_state.pop("draft_stamps", None)
        st.session_state.pop("early-preview", None)
        st.toast("已儲存交易編號。下載的糧單會印上這個編號。")
        st.rerun()
    shown = row.copy()
    shown["salary_reference"] = salary_ref.strip()
    shown["allowance_reference"] = allowance_ref.strip()
    _download_slip(info, person, shown, pay_date, key)


def _download_slip(info, person, row, pay_date, key):
    """Offer the same PDF download before the salary is issued."""
    if row is None or person.get("kind") == "part":
        return
    from payroll.core.config import book_info
    from payroll.documents.slip_pdf import render_office_pdf
    from payroll.pay.early import format_pay_date
    from payroll.staff.staff import read_batch
    booked = book_info(info, person["book"])
    if hasattr(pay_date, "day"):
        booked["pay_date_override"] = format_pay_date(pay_date)
    staff_id = _text(row.get("staff_id")) or person["employee_no"]
    name = _text(row.get("slip_name")).split()[0] or staff_id
    safe = "".join(ch for ch in name if ch not in '<>:"/\\|?*\'').strip() or staff_id
    batch = read_batch(booked) or str(staff_id).split("-")[0]
    suffix = str(staff_id).split("-")[-1]
    try:
        data = render_office_pdf(row, booked)
    except (OSError, SystemExit, ValueError) as error:
        st.error(str(error))
        return
    st.download_button(
        "下載這份糧單",
        data,
        file_name=f"#{batch}_{suffix}_{safe}.pdf",
        mime="application/pdf",
        type="primary",
        width="stretch",
        key=key,
    )


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
            _transfer_reference(info, draft, person, record, readonly)
            path = _slip_file(info, draft, person, record)
            if path is not None and path.is_file():
                st.download_button(
                    "下載這份糧單",
                    path.read_bytes(),
                    file_name=path.name,
                    mime="application/pdf" if path.suffix.lower() == ".pdf" else None,
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
        calculated = person["kind"] == "full" and row is not None
        picked = date.today()
        if calculated:
            _breakdown(row, office=person["book"] == "admin")
            note = _text(row.get("review"))
            if note and note.lower() != "nan":
                st.caption(note)
            picked = st.date_input(
                "出糧日期",
                value=date.today(),
                disabled=readonly,
                format="YYYY-MM-DD",
                key=f"early-date-{key}",
            )
            _offer_slip(info, person, row, picked, readonly, f"early-pdf-{key}")
            _adjustment(info, row, person, readonly)
            _confirm_absence(info, row, person, readonly)
        if hasattr(left, "year") and left >= date.today():
            st.caption("最後工作日之前可以先出。還沒打卡的日子按更表計算，不當作缺卡。")
        if reason:
            st.warning(reason)
        actions = st.container(horizontal=True, vertical_alignment="bottom")
        with actions:
            if not calculated:
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
    """One line for each part of the salary, in the order it is added or taken off."""
    full = _amount(row.get("full_salary"))
    counted = _amount(row.get("counted_days"))
    month_days = _amount(row.get("month_days"))
    basic = _amount(row.get("basic_salary"))
    lines = []
    if full and month_days and counted and counted != month_days:
        lines.append(f"全月基本薪金 {hk(full)}")
        lines.append(f"基本薪金 {hk(full)} ÷ {month_days:g} × {counted:g} = {hk(basic)}")
    else:
        lines.append(f"基本薪金 {hk(basic)}")
    leave_pay = _amount(row.get("leave_pay"))
    if leave_pay:
        lines.append(
            f"+ 未用年假 {hk(leave_pay)}（全月薪金 × 12 ÷ 365 × {_amount(row.get('unused_annual_days')):g} 日）"
        )
    other = _amount(row.get("other_income")) - leave_pay
    if other:
        sign = "+" if other > 0 else "−"
        lines.append(f"{sign} 其他收入 {hk(abs(other))}")
    overtime = _amount(row.get("ot_pay"))
    hours = _amount(row.get("ot_hours_detected"))
    if office and hours and not overtime:
        lines.append(f"加班 {hours:g} 小時，寫字樓不計加班費")
    elif overtime:
        lines.append(f"+ 加班 {hours:g} 小時 {hk(overtime)}")
    bonus = _amount(row.get("bonus_paid"))
    if bonus:
        lines.append(f"+ 勤工獎 {hk(bonus)}")
    manual = _amount(row.get("manual_delta"))
    if manual:
        sign = "+" if manual > 0 else "−"
        lines.append(f"{sign} 其他調整 {hk(abs(manual))}")
    unpaid = _amount(row.get("unpaid_amount"))
    if unpaid:
        lines.append(f"− 無薪假及扣薪 {hk(unpaid)}")
    for label, key in (("租金", "rent"), ("水費", "water"), ("電費", "electricity")):
        value = _amount(row.get(key))
        if value:
            lines.append(f"− {label} {hk(value)}")
    scheme = _text(row.get("scheme")).lower()
    mpf = _amount(row.get("mpf_employee"))
    if scheme == "rent":
        lines.append("強積金　不扣（內地勞工）")
    elif mpf:
        lines.append(f"− 僱員強積金 {hk(mpf)}（收入欄合計 × 5%，最後扣除，不包括交通／健康津貼）")
    else:
        lines.append("強積金　不扣")
    late = _text(row.get("late_text"))
    early = _text(row.get("early_text"))
    lines.append("遲到 " + (late if late and late.lower() != "nan" else "無"))
    lines.append("早退 " + (early if early and early.lower() != "nan" else "無"))
    pending = _text(row.get("absence_pending"))
    if pending and pending.lower() != "nan":
        lines.append(f"缺勤未確認 {pending}")
    lines.append(f"= 預計薪金 {hk(row.get('net'))}")
    allowance = _amount(row.get("allowance_amount"))
    if allowance:
        lines.append(f"+ 交通／健康津貼 {hk(allowance)}（另一筆過數）")
        lines.append(f"= 今次共付 {hk(_amount(row.get('net')) + allowance)}")
    st.markdown("\n".join(f"- {line}" for line in lines))
    from payroll.core.money import serious_late
    office_limit = 240 if office else 15
    cases = serious_late(row.get("late_text"), office_limit)
    listed = "、".join(f"{day} {minutes}分鐘" for day, minutes in cases)
    if office:
        missing = _text(row.get("missing_text"))
        if cases or missing:
            detail = listed
            if missing:
                detail = "、".join(part for part in (detail, f"缺卡 {missing}") if part)
            st.caption(f"寫字樓缺半天可以扣薪：{detail}。在「扣薪日數」填 0.5 是半天，0 是不扣。")
    if not office:
        notes = []
        for label, text in (("遲到", row.get("late_text")), ("早退", row.get("early_text"))):
            found = serious_late(text, 0)
            if not found:
                continue
            total = sum(minutes for _, minutes in found)
            detail = "、".join(f"{day} {minutes}分鐘" for day, minutes in found)
            notes.append(f"{label} {detail}，共 {total} 分鐘")
        if notes:
            st.caption("。".join(notes) + "。店舖和工場在「扣薪分鐘」填要扣的分鐘，按實際分鐘計薪。0 是不扣。")


def _amount(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _previous_allowance(info, staff_id):
    """Last month's allowance from the saved draft. None when that file is absent."""
    import pandas as pd
    from payroll.core.config import parse_month

    year, month = int(info["year"]), int(info["month"])
    if month == 1:
        key = f"{year - 1}-12"
    else:
        key = f"{year}-{month - 1:02d}"
    path = parse_month(key)["folder"] / "payroll_draft.xlsx"
    if not path.exists():
        return None
    wanted = _text(staff_id)
    try:
        book = pd.ExcelFile(path)
    except (OSError, ValueError):
        return None
    for sheet in book.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet)
        if "糧單編號" not in frame.columns or "津貼" not in frame.columns:
            continue
        hit = frame[frame["糧單編號"].map(_text) == wanted]
        if hit.empty:
            continue
        try:
            amount = float(hit.iloc[0]["津貼"])
        except (TypeError, ValueError):
            return None
        if amount != amount:
            return None
        return amount
    return None


def _adjustment(info, row, person, readonly):
    """Leave days and allowances for this one early slip."""
    staff_id = _text(row.get("staff_id"))
    if not staff_id:
        return
    last_allowance = _previous_allowance(info, staff_id)
    if last_allowance is None:
        st.caption("找不到上月津貼。今次交通津貼和健康津貼請自行填寫，儲存後才計入。不計入強積金。")
    else:
        st.caption(f"上月津貼 {hk(last_allowance)}。今次請自行填寫，儲存後才計入。不計入強積金。")
    prefix = f"{info['key']}-{person['book']}-{staff_id}"
    balances = []
    for label_key, days_key in (("al_1_label", "al_1_days"), ("al_2_label", "al_2_days")):
        label = _text(row.get(label_key))
        if label:
            balances.append(f"{label} {_amount(row.get(days_key)):g} 日")
    if balances:
        st.caption("年假結餘紀錄：" + "；".join(balances))
    st.caption("這裡填要發放的未用年假日數。糧單會加上全月薪金 × 12 ÷ 365 × 日數。")
    unpaid = st.number_input(
        "無薪假（日）", value=_amount(row.get("unpaid_days")), step=0.5, disabled=readonly,
        help="只有真正沒有出糧的缺勤才填。未用年假不要填在這裡。", key=f"early-unpaid-{prefix}",
    )
    if _amount(row.get("unused_annual_days")):
        typed_leave = row.get("unused_annual_days")
    elif _amount(row.get("annual_taken")):
        typed_leave = row.get("annual_taken")
    else:
        typed_leave = _amount(row.get("al_1_days")) + _amount(row.get("al_2_days"))
    annual = st.number_input(
        "未用年假（日）", value=_amount(typed_leave), step=0.01, disabled=readonly,
        help="要發放的未用年假。金額加進薪金，並計入強積金。",
        key=f"early-annual-{prefix}",
    )
    transport_value = st.number_input(
        "交通津貼", value=_amount(row.get("final_transport")), step=1.0, disabled=readonly,
        help="今次最後一筆由你填。上月金額只作提示。不計入強積金。", key=f"early-transport-{prefix}",
    )
    health_value = st.number_input(
        "健康津貼", value=_amount(row.get("final_health")), step=1.0, disabled=readonly,
        help="今次最後一筆由你填。上月金額只作提示。不計入強積金。", key=f"early-health-{prefix}",
    )
    extra = st.number_input(
        "其他調整", value=_amount(row.get("manual_delta")), step=1.0, disabled=readonly,
        help="代通知金。正數是加，負數是減。未用年假已經計入薪金和強積金，不要在這裡再填一次。",
        key=f"early-delta-{prefix}",
    )
    deduct = st.number_input(
        "扣薪日數", value=_amount(row.get("salary_deduct_days")), step=0.5, min_value=0.0, disabled=readonly,
        help="半天或整天。0 是不扣。0.5 是半天。",
        key=f"early-deduct-{prefix}",
    )
    deduct_mins = 0.0
    if _text(person.get("book")) != "admin":
        deduct_mins = st.number_input(
            "扣薪分鐘", value=_amount(row.get("salary_deduct_minutes")), step=1.0, min_value=0.0, disabled=readonly,
            help="店舖和工場。寫字樓不適用。金額 = 月薪 ÷ 當月日數 ÷ 9.5 小時 ÷ 60 × 分鐘。0 是不扣。",
            format="%.0f",
            key=f"early-deduct-mins-{prefix}",
        )
        if deduct_mins:
            from payroll.core.money import minute_deduction
            st.caption(f"{int(deduct_mins)} 分鐘扣 {hk(minute_deduction(row.get('full_salary'), row.get('month_days'), deduct_mins))}。")
    if readonly or not st.button("儲存調整", key=f"early-save-{prefix}"):
        return
    from payroll.core.config import book_info
    from payroll.pay.review import save_one
    try:
        save_one(book_info(info, person["book"]), staff_id, {
            "unpaid_days": float(unpaid),
            "unused_annual_days": float(annual),
            "annual_taken": 0,
            "manual_delta": float(extra),
            "salary_deduct_days": float(deduct),
            "salary_deduct_minutes": float(deduct_mins),
            "final_transport": float(transport_value),
            "final_health": float(health_value),
        })
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.session_state.pop("early-preview", None)
    st.toast("已儲存調整")
    st.rerun()


def _confirm_absence(info, row, person, readonly):
    """Answer each missing punch here. The review page can still be locked."""
    pending = [part for part in _text(row.get("absence_pending")).split("、") if part and part.lower() != "nan"]
    if not pending or readonly:
        return
    from payroll.core.config import book_info
    from payroll.pay.payroll import parse_absence_choices
    from payroll.pay.review import save_one
    staff_id = _text(row.get("staff_id"))
    if not staff_id:
        return
    st.caption("更表有更但沒有打卡。每一天選無薪假、病假，或有上班但忘記打卡。")
    stored = parse_absence_choices(row.get("absence_choices"))
    options = ["無薪假", "病假", "有上班（忘記打卡）"]
    codes = {"無薪假": "unpaid", "病假": "sick", "有上班（忘記打卡）": "worked"}
    reverse = {value: key for key, value in codes.items()}
    picked = {}
    for label in pending:
        current = reverse.get(stored.get(label), options[0])
        picked[label] = st.radio(
            label, options, index=options.index(current) if current in options else 0,
            horizontal=True, key=f"early-abs-{info['key']}-{person['book']}-{staff_id}-{label}",
        )
    if not st.button("儲存缺勤確認", key=f"early-abs-save-{info['key']}-{person['book']}-{staff_id}"):
        return
    merged = dict(stored)
    for label, choice in picked.items():
        merged[label] = codes[choice]
    text = "、".join(f"{label}:{kind}" for label, kind in merged.items())
    try:
        save_one(book_info(info, person["book"]), staff_id, {"absence_choices": text})
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.session_state.pop("early-preview", None)
    st.toast("已儲存缺勤")
    st.rerun()


def _saved_text(label, key, current, disabled):
    if key not in st.session_state:
        st.session_state[key] = "" if current.lower() == "nan" else current
    return st.text_input(label, key=key, disabled=disabled)


def _transfer_reference(info, draft, person, record, readonly):
    """The bank reference for this early payment. It is printed on the slip."""
    row = _full_row(draft, person)
    staff_id = _text(record.get("staff_id"))
    if not staff_id and row is not None:
        staff_id = _text(row.get("staff_id"))
    if not staff_id:
        st.caption("這個人沒有糧單編號，不能寫入交易編號。")
        return
    prefix = f"{info['key']}-{person['book']}-{staff_id}-issued"
    current_salary = _text(row.get("salary_reference")) if row is not None else ""
    current_allowance = _text(row.get("allowance_reference")) if row is not None else ""
    salary_ref = _saved_text("薪金交易編號", f"issued-ref-{prefix}", current_salary, readonly)
    allowance_ref = _saved_text("津貼交易編號", f"issued-allow-{prefix}", current_allowance, readonly)
    st.caption("薪金和津貼是兩次過數。編號會印在糧單的自動轉賬一行。")
    if readonly or not st.button("儲存交易編號", key=f"issued-save-{prefix}"):
        return
    from payroll.core.config import book_info
    from payroll.pay.review import save_one
    try:
        save_one(book_info(info, person["book"]), staff_id, {
            "salary_reference": salary_ref.strip(),
            "allowance_reference": allowance_ref.strip(),
        })
    except SystemExit as error:
        st.error(str(error))
        return
    if person.get("book") != "admin" and row is not None:
        _rewrite_shop_slip(info, person, record, row, salary_ref.strip(), allowance_ref.strip(), staff_id)
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.toast("已儲存交易編號。重新下載糧單就會看到編號。")
    st.rerun()


def _rewrite_shop_slip(info, person, record, row, salary_ref, allowance_ref, staff_id):
    from payroll.core.config import book_info
    from payroll.documents.slips import write_person_slip
    updated = row.copy()
    updated["salary_reference"] = salary_ref
    updated["allowance_reference"] = allowance_ref
    updated["pay_this"] = True
    booked = book_info(info, person["book"])
    booked["pay_date_override"] = _text(record.get("pay_date"))
    try:
        write_person_slip(booked, updated.to_frame().T, staff_id)
    except (OSError, SystemExit):
        return


def _mainland_contracts(info, readonly):
    """合約完結 is the last working day. A later date entered here is a renewal."""
    from payroll.staff.staff import _as_date, _text, load_staff
    from payroll.staff.staff_write import edit_staff

    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    people = []
    for _, record in load_staff().iterrows():
        if _text(record.get("sheet")) != "內地勞工" or _text(record.get("status")) == "已離職":
            continue
        number = _text(record.get("employee_no"))
        if not number:
            continue
        people.append({
            "employee_no": number,
            "name_zh": _text(record.get("name_zh")),
            "name": _text(record.get("name_zh")) or _text(record.get("name_en")) or number,
            "sheet": "內地勞工",
            "contract_end": _as_date(record.get("contract_end")),
        })
    if not people:
        return
    people.sort(key=lambda person: ((person["contract_end"] or date.max), person["name"]))
    ending = [
        person for person in people
        if person["contract_end"] is not None and person["contract_end"] <= end
    ]
    st.markdown("**內地合約完結**")
    st.caption("合約完結日是最後工作日，薪金計到那一日。續約就填一個更後的日期。")
    if ending:
        names = "、".join(
            f"{person['name']} {person['contract_end'].isoformat()}" for person in ending
        )
        st.caption(f"已到或本月完結：{names}")
    labels = [
        f"{person['name']}（{person['employee_no']}）"
        + (f"　{person['contract_end'].isoformat()}" if person["contract_end"] else "　未填")
        for person in people
    ]
    chosen = st.selectbox("同事", labels, key=f"contract-who-{info['key']}")
    person = people[labels.index(chosen)]
    current = person["contract_end"] if isinstance(person["contract_end"], date) else end
    picked = st.date_input(
        "合約完結日期",
        value=current,
        format="YYYY-MM-DD",
        disabled=readonly,
        key=f"contract-end-{info['key']}-{person['employee_no']}-{current.isoformat()}",
    )
    if readonly or not st.button("儲存合約完結", key=f"contract-save-{info['key']}-{person['employee_no']}"):
        return
    try:
        edit_staff(person["sheet"], person["employee_no"], person["name_zh"], {
            "合約完結日期": picked.isoformat(),
        })
    except SystemExit as error:
        st.error(str(error))
        return
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.session_state.pop("draft", None)
    st.toast("已更新合約完結日期")
    st.rerun()


def _plan_ahead(info, waiting, readonly):
    st.markdown("**最後工作日之前先計算**")
    st.caption("未寫離職也可以。選最後工作日，還沒打卡的日子按更表計算。")
    labels = [f"{person['name']}（{person['employee_no']}）" for person in waiting]
    chosen = st.selectbox("同事", labels, key=f"early-who-{info['key']}")
    person = waiting[labels.index(chosen)]
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    contract = person.get("contract_end")
    default = contract if isinstance(contract, date) and start <= contract <= end else date.today()
    if default < start or default > end:
        default = end
    if isinstance(contract, date) and start <= contract <= end:
        st.caption(f"合約完結 {contract.isoformat()} 是最後工作日。續約請改上面的合約完結日期。")
    picked_last = st.date_input(
        "最後工作日",
        value=default,
        min_value=start,
        max_value=end,
        format="YYYY-MM-DD",
        disabled=readonly,
        key=f"early-last-{info['key']}-{person['employee_no']}",
    )
    if person["kind"] == "full":
        _plan_editor(info, person, picked_last, readonly)
        return
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


def _plan_editor(info, person, last_day, readonly):
    """Same salary editor as a resignation payment, for a last day chosen in advance."""
    token = f"{info['key']}|{person['employee_no']}|{person['book']}|{last_day.isoformat()}"
    cached = st.session_state.get("early-preview")
    if not isinstance(cached, dict) or cached.get("token") != token:
        from payroll.pay.early import preview_early
        try:
            with st.spinner("正在計算"):
                _person, row, _part, reason = preview_early(
                    info, person["employee_no"], last_day,
                    book=person["book"], kind=person["kind"],
                )
        except SystemExit as error:
            st.error(str(error))
            return
        cached = {"token": token, "row": row, "reason": reason}
        st.session_state["early-preview"] = cached
    row = cached["row"]
    reason = cached.get("reason") or ""
    _breakdown(row, office=person["book"] == "admin")
    note = _text(row.get("review"))
    if note and note.lower() != "nan":
        st.caption(note)
    picked = st.date_input(
        "出糧日期",
        value=date.today(),
        disabled=readonly,
        format="YYYY-MM-DD",
        key=f"early-payon-{info['key']}-{person['employee_no']}",
    )
    _offer_slip(
        info, person, row, picked, readonly,
        f"early-pdf-{info['key']}-{person['employee_no']}",
    )
    _adjustment(info, row, person, readonly)
    _confirm_absence(info, row, person, readonly)
    if last_day >= date.today():
        st.caption("還沒打卡的日子按更表計算，不當作缺卡。")
    if reason:
        st.warning(reason)
    actions = st.container(horizontal=True, vertical_alignment="bottom")
    with actions:
        go = st.button(
            "提前出糧",
            type="primary",
            disabled=readonly or bool(reason),
            key=f"early-issue-{info['key']}-{person['employee_no']}",
        )
    if go:
        confirm_early(
            info["key"], person["employee_no"], person["book"], person["kind"],
            person["name"], picked.isoformat(), hk(row.get("net")), last_day.isoformat(),
        )


def early_section(info, draft, readonly):
    try:
        people = month_leavers(info)
        waiting = open_people(info)
    except SystemExit as error:
        st.error(str(error))
        return
    _mainland_contracts(info, readonly)
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
