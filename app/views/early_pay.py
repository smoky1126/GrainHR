"""Pay one resigned person before the rest of the month."""

from datetime import date
from pathlib import Path

import streamlit as st

from app.components.format import hk
from payroll.core.config import parse_month
from payroll.core.labels import BOOKS
from payroll.pay.early import early_hold, issue_early, latest_early, open_people, quote_early
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


def _offer_slip(info, person, row, pay_date, readonly, key, issue=None):
    """Transaction numbers and the PDF. With issue, downloading records the early pay."""
    if row is None or person.get("kind") == "part":
        return
    staff_id = _text(row.get("staff_id")) or _text(person.get("staff_id"))
    prefix = f"{info['key']}-{person['book']}-{staff_id or person['employee_no']}"
    with st.form(f"slip-ref-form-{prefix}", border=False):
        salary_ref = _saved_text(
            "薪金交易編號", f"early-ref-{prefix}", _text(row.get("salary_reference")), readonly,
        )
        allowance_ref = _saved_text(
            "津貼交易編號", f"early-allow-ref-{prefix}", _text(row.get("allowance_reference")), readonly,
        )
        st.caption("薪金和津貼是兩次過數。編號會印在糧單的自動轉賬一行。沒有津貼就讓津貼編號留空。")
        saved = st.form_submit_button("儲存交易編號", disabled=readonly or not staff_id)
    if staff_id and not readonly and saved:
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
    record = None
    if issue and not readonly:
        record = _record_on_download(
            info, person, staff_id, salary_ref, allowance_ref, pay_date, issue,
        )
    _download_slip(
        info, person, shown, pay_date, key, record,
        pays=issue is not None, disabled=issue is not None and record is None,
    )


def _record_on_download(info, person, staff_id, salary_ref, allowance_ref, pay_date, issue):
    """Save the typed references, then record the early pay, when the slip is downloaded."""
    last_iso, reason, error_key = issue
    if reason:
        return None

    def record():
        from payroll.core.config import book_info
        from payroll.pay.early import issue_early
        from payroll.pay.review import save_one
        try:
            if staff_id:
                save_one(book_info(info, person["book"]), staff_id, {
                    "salary_reference": salary_ref.strip(),
                    "allowance_reference": allowance_ref.strip(),
                })
            last_day = date.fromisoformat(last_iso) if last_iso else person.get("leave_date")
            issue_early(
                info, person["employee_no"], pay_date,
                book=person["book"], kind=person.get("kind") or "full", last_day=last_day,
            )
        except PermissionError:
            st.session_state[error_key] = "請先關閉已打開的糧單或提前出糧紀錄，然後再試。"
            return
        except SystemExit as error:
            st.session_state[error_key] = str(error)
            return
        st.session_state.pop(error_key, None)
        st.session_state["dirty"] = True
        st.session_state.pop("drafts", None)
        st.session_state.pop("draft_stamps", None)
        st.session_state.pop("early-preview", None)
        st.toast(f"已為 {person['name']} 提前出糧，月結不會再發。")

    return record


def _download_slip(info, person, row, pay_date, key, record=None, pays=False, disabled=False):
    """Offer the PDF. record, when set, stores the early pay as the file downloads."""
    if row is None or person.get("kind") == "part":
        return
    from payroll.core.config import book_info
    from payroll.documents.slip_pdf import render_office_pdf
    from payroll.pay.early import format_pay_date
    from payroll.staff.staff import read_batch
    booked = book_info(info, person["book"])
    if hasattr(pay_date, "day"):
        booked["pay_date_override"] = format_pay_date(pay_date)
    elif _text(pay_date):
        booked["pay_date_override"] = _text(pay_date)
    staff_id = _text(row.get("staff_id")) or person["employee_no"]
    name = _text(row.get("slip_name")).split()[0] or staff_id
    safe = "".join(ch for ch in name if ch not in '<>:"/\\|?*\'').strip() or staff_id
    batch = read_batch(booked) or str(staff_id).split("-")[0]
    suffix = str(staff_id).split("-")[-1]
    shown = row.copy()

    def build():
        return render_office_pdf(shown, booked)

    st.download_button(
        "產生並下載糧單" if pays else "下載這份糧單",
        build,
        file_name=f"#{batch}_{suffix}_{safe}.pdf",
        mime="application/pdf",
        on_click=record or "ignore",
        disabled=disabled,
        type="primary",
        width="stretch",
        key=f"slip-make-{key}" if pays else key,
    )


@st.cache_data(ttl=6 * 60 * 60, max_entries=24, show_spinner=False)
def _cached_leaver_draft(month_key, book, plan, stamp, today_iso):
    from payroll.pay.early import leaver_draft
    del stamp, today_iso
    last_days = {number: date.fromisoformat(day) for number, day in plan}
    return leaver_draft(parse_month(month_key), book, last_days)[1]


def _issued_plan(info, book):
    from payroll.pay.early import latest_early
    from payroll.staff.staff import _as_date
    plan = {}
    for number, record in latest_early(info).items():
        left = _as_date(record.get("leave_date"))
        if left is not None and (_text(record.get("book")) or "bg") == book:
            plan[number] = left
    return plan


def _leaver_row(info, person, allow_closed=False, plan=None):
    """The calculated row, reused until a punch, roster, staff or adjustment file changes."""
    from app.context import _input_stamp
    from payroll.core.config import book_info
    from payroll.pay.early import early_keys, leaver_row
    plan = dict(plan or {})
    plan[person["employee_no"]] = person["leave_date"]
    key = tuple(sorted((number, day.isoformat()) for number, day in plan.items()))
    files = _input_stamp(book_info(info, person["book"]))
    ids, numbers = early_keys(info)
    stamp = (
        tuple(item for item in files if Path(item[0]).name != "early_paid.xlsx"),
        tuple(sorted(ids)),
        tuple(sorted(numbers)),
    )
    draft = _cached_leaver_draft(info["key"], person["book"], key, stamp, date.today().isoformat())
    return leaver_row(draft, person, allow_closed)


def _paid_row(info, draft, person, record):
    """The slip that was compiled, cut off on the last day stored with that payment."""
    from payroll.staff.staff import _as_date
    left = _as_date(record.get("leave_date")) or person.get("leave_date")
    planned = dict(person)
    if left is not None:
        planned["leave_date"] = left
    if planned.get("leave_date") is None:
        return _full_row(draft, person)
    try:
        return _leaver_row(info, planned, allow_closed=True, plan=_issued_plan(info, person["book"]))
    except SystemExit:
        return _full_row(draft, person)


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
            panel = st.expander("查看、修改及下載糧單", key=f"early-open-{key}", on_change="rerun")
            with panel:
                if panel.open:
                    _issued_editor(info, draft, person, record, readonly, key)
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
        if calculated:
            _breakdown(row, office=person["book"] == "admin")
            note = _text(row.get("review"))
            if note and note.lower() != "nan":
                st.caption(note)
            _adjustment(info, row, person, readonly)
            _confirm_absence(info, row, person, readonly)
        if hasattr(left, "year") and left >= date.today():
            st.caption("最後工作日之前可以先出。還沒打卡的日子按更表計算，不當作缺卡。")
        if calculated:
            _slip_then_issue(
                info, person, row, reason, readonly, f"early-card-{key}",
                left.isoformat() if hasattr(left, "isoformat") else "",
            )
            return
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


def _issued_editor(info, draft, person, record, readonly, key):
    st.caption("可以再改這份糧單。儲存調整後，下載的 PDF 和過數金額會更新。不會再出一次糧。")
    paid_row = _paid_row(info, draft, person, record)
    if person["kind"] == "full" and paid_row is not None:
        _breakdown(paid_row, office=person["book"] == "admin")
        _adjustment(info, paid_row, person, readonly)
        _confirm_absence(info, paid_row, person, readonly)
    _transfer_reference(info, draft, person, record, readonly, paid_row)
    if paid_row is not None:
        _download_slip(info, person, paid_row, record.get("pay_date"), f"early-down-{key}")
        return
    path = _slip_file(info, draft, person, record)
    if path is not None and path.is_file():
        st.download_button(
            "下載這份糧單",
            path.read_bytes(),
            file_name=path.name,
            mime="application/pdf" if path.suffix.lower() == ".pdf" else None,
            key=f"early-down-{key}",
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
    st.caption("這裡填要發放的未用年假日數。糧單會加上全月薪金 × 12 ÷ 365 × 日數。改完按「儲存調整」才會重新計算。")
    with st.form(f"early-adj-form-{prefix}", border=False):
        values = _adjustment_inputs(row, person, readonly, prefix)
        saved = st.form_submit_button("儲存調整", disabled=readonly)
    if readonly or not saved:
        return
    from payroll.core.config import book_info
    from payroll.pay.review import save_one
    try:
        save_one(book_info(info, person["book"]), staff_id, values)
    except SystemExit as error:
        st.error(str(error))
        return
    from payroll.pay.early import latest_early, revise_issued_net
    issued = latest_early(info).get(person["employee_no"])
    if issued is not None:
        with st.spinner("正在重新計算"):
            revised = _paid_row(info, None, person, issued)
        if revised is not None:
            revise_issued_net(info, person["employee_no"], revised.get("net"))
    st.session_state["dirty"] = True
    st.session_state.pop("drafts", None)
    st.session_state.pop("draft_stamps", None)
    st.session_state.pop("early-preview", None)
    st.toast("已儲存調整")
    st.rerun()


def _adjustment_inputs(row, person, readonly, prefix):
    unpaid = st.number_input(
        "無薪假（日）", value=_amount(row.get("unpaid_days")), step=0.5, disabled=readonly,
        help="只有真正沒有出糧的缺勤才填。未用年假不要填在這裡。", key=f"early-unpaid-{prefix}",
    )
    if _amount(row.get("unused_annual_days")):
        typed_leave = row.get("unused_annual_days")
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
    mainland = _text(row.get("scheme")).lower() == "rent"
    water_value = 0.0
    power_value = 0.0
    if mainland:
        from payroll.pay.payroll import chosen_charge
        water_value = st.number_input(
            "水費", value=chosen_charge(row.get("water_override"), row.get("water")),
            step=0.1, min_value=0.0, disabled=readonly,
            help="你填的金額是最終水費。不會被原來的水費改掉。不計入租金。",
            key=f"early-water-{prefix}",
        )
        power_value = st.number_input(
            "電費", value=chosen_charge(row.get("electricity_override"), row.get("electricity")),
            step=0.1, min_value=0.0, disabled=readonly,
            help="你填的金額是最終電費。不會被原來的電費改掉。不計入租金。",
            key=f"early-power-{prefix}",
        )
        st.caption("水費和電費以你儲存的金額為準。租金仍然是扣薪後的 10%，不包括這兩項。")
    return {
        "unpaid_days": float(unpaid),
        "unused_annual_days": float(annual),
        "annual_taken": "",
        "manual_delta": float(extra),
        "salary_deduct_days": float(deduct),
        "salary_deduct_minutes": float(deduct_mins),
        "final_transport": float(transport_value),
        "final_health": float(health_value),
        **({"water_override": float(water_value), "electricity_override": float(power_value)} if mainland else {}),
    }


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
    with st.form(f"early-abs-form-{info['key']}-{person['book']}-{staff_id}", border=False):
        for label in pending:
            current = reverse.get(stored.get(label), options[0])
            picked[label] = st.radio(
                label, options, index=options.index(current) if current in options else 0,
                horizontal=True, key=f"early-abs-{info['key']}-{person['book']}-{staff_id}-{label}",
            )
        saved = st.form_submit_button("儲存缺勤確認")
    if not saved:
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


def _transfer_reference(info, draft, person, record, readonly, paid_row=None):
    """The bank reference for this early payment. It is printed on the slip."""
    row = paid_row if paid_row is not None else _full_row(draft, person)
    staff_id = _text(record.get("staff_id"))
    if not staff_id and row is not None:
        staff_id = _text(row.get("staff_id"))
    if not staff_id:
        st.caption("這個人沒有糧單編號，不能寫入交易編號。")
        return
    prefix = f"{info['key']}-{person['book']}-{staff_id}-issued"
    current_salary = _text(row.get("salary_reference")) if row is not None else ""
    current_allowance = _text(row.get("allowance_reference")) if row is not None else ""
    with st.form(f"issued-ref-form-{prefix}", border=False):
        salary_ref = _saved_text("薪金交易編號", f"issued-ref-{prefix}", current_salary, readonly)
        allowance_ref = _saved_text("津貼交易編號", f"issued-allow-{prefix}", current_allowance, readonly)
        st.caption("薪金和津貼是兩次過數。編號會印在糧單的自動轉賬一行。")
        saved = st.form_submit_button("儲存交易編號", disabled=readonly)
    if readonly or not saved:
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


def _plan_departments(waiting):
    """Departments that still have someone to calculate, in the staff-list order."""
    from payroll.staff.directory import GROUPS
    counts = {}
    for person in waiting:
        label = person.get("group_label") or "未分類"
        counts[label] = counts.get(label, 0) + 1
    ordered = []
    seen = set()
    for _key, label in GROUPS:
        if counts.get(label) and label not in seen:
            ordered.append((label, counts[label]))
            seen.add(label)
    for label, count in sorted(counts.items()):
        if label not in seen:
            ordered.append((label, count))
    return ordered


def _plan_ahead(info, waiting, readonly):
    st.markdown("**最後工作日之前先計算**")
    st.caption("先選部門，再選同事。打開下面才填最後工作日和計算。")
    departments = _plan_departments(waiting)
    dept_labels = [f"{label}（{count}）" for label, count in departments]
    dept_key = f"early-dept-{info['key']}"
    if st.session_state.get(dept_key) not in dept_labels:
        st.session_state.pop(dept_key, None)
    filters = st.columns(2)
    dept_choice = filters[0].selectbox(
        "部門", dept_labels, index=None, placeholder="選擇部門", key=dept_key,
    )
    if dept_choice not in dept_labels:
        return
    dept = departments[dept_labels.index(dept_choice)][0]
    people = [person for person in waiting if (person.get("group_label") or "未分類") == dept]
    people.sort(key=lambda person: person["name"])
    labels = [f"{person['name']}（{person['employee_no']}）" for person in people]
    staff_key = f"early-who-{info['key']}-{dept}"
    if st.session_state.get(staff_key) not in labels:
        st.session_state.pop(staff_key, None)
    chosen = filters[1].selectbox(
        "同事", labels, index=None, placeholder="選擇同事", key=staff_key,
    )
    if chosen not in labels:
        return
    person = people[labels.index(chosen)]
    panel = st.expander(
        f"計算 {person['name']}",
        key=f"early-plan-open-{info['key']}-{person['employee_no']}",
        on_change="rerun",
    )
    with panel:
        if panel.open:
            _plan_person(info, person, readonly)


def _plan_person(info, person, readonly):
    start = date(int(info["year"]), int(info["month"]), 1)
    end = date(int(info["year"]), int(info["month"]), int(info["days"]))
    contract = person.get("contract_end")
    default = contract if isinstance(contract, date) and start <= contract <= end else date.today()
    if default < start or default > end:
        default = end
    if isinstance(contract, date) and start <= contract <= end:
        st.caption(f"按合約，最後工作日是 {contract.isoformat()}（合約完結日的前一日）。續約請到員工總表按「續約」。")
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
    """Same salary editor as a resignation payment, for a last day chosen in advance.

    The salary is calculated only after 計算薪金, so opening 出糧 does not build it.
    """
    from app.context import _input_stamp
    from payroll.core.config import book_info
    from payroll.pay.early import early_hold
    planned = dict(person)
    planned["leave_date"] = last_day
    token = (info["key"], person["employee_no"], person["book"], last_day.isoformat(), date.today().isoformat())
    cached = st.session_state.get("early-plan")
    same = isinstance(cached, dict) and cached.get("token") == token
    if not same:
        if st.button("計算薪金", disabled=readonly, key=f"early-plan-go-{info['key']}"):
            try:
                with st.spinner("正在計算"):
                    row = _leaver_row(info, planned)
            except SystemExit as error:
                st.error(str(error))
                return
            stamp = _input_stamp(book_info(info, person["book"]))
            st.session_state["early-plan"] = {"token": token, "stamp": stamp, "row": row}
            st.rerun()
        st.caption("選好同事和最後工作日，按「計算薪金」。")
        return
    stamp = _input_stamp(book_info(info, person["book"]))
    if cached.get("stamp") != stamp:
        try:
            with st.spinner("正在計算"):
                row = _leaver_row(info, planned)
        except SystemExit as error:
            st.error(str(error))
            return
        cached = {"token": token, "stamp": stamp, "row": row}
        st.session_state["early-plan"] = cached
    row = cached["row"]
    reason = early_hold(row)
    _breakdown(row, office=person["book"] == "admin")
    note = _text(row.get("review"))
    if note and note.lower() != "nan":
        st.caption(note)
    _adjustment(info, row, person, readonly)
    _confirm_absence(info, row, person, readonly)
    if last_day >= date.today():
        st.caption("還沒打卡的日子按更表計算，不當作缺卡。")
    _slip_then_issue(
        info, person, row, reason, readonly,
        f"early-plan-{info['key']}-{person['employee_no']}", last_day.isoformat(),
    )


def _slip_then_issue(info, person, row, reason, readonly, key, last_iso):
    """One action: download the slip, and that records the early pay."""
    st.caption("核對上面的計算和調整，然後按「產生並下載糧單」。下載即提前出糧，月結不會再發一次。")
    picked = st.date_input(
        "出糧日期",
        value=date.today(),
        disabled=readonly,
        format="YYYY-MM-DD",
        key=f"{key}-payon",
    )
    error_key = f"early-issue-error-{key}"
    error = st.session_state.pop(error_key, "")
    if reason:
        st.warning(reason)
    elif error:
        st.error(error)
    _offer_slip(
        info, person, row, picked, readonly, f"{key}-pdf",
        issue=None if readonly else (last_iso, reason, error_key),
    )


def early_section(info, draft, readonly):
    try:
        from payroll.pay.early import early_cards
        people = early_cards(info)
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
