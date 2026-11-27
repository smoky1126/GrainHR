"""One-page salary slip as a PDF, with the company logo at the top."""

import re
from pathlib import Path


FONT = Path(__file__).resolve().parent / "fonts" / "NotoSansTC-Regular.otf"
FOOTER = "For salary content inquiry, please contact the HR Department within 5 days. 如對薪金內容有任何疑問，請於5天內聯絡人事部。"


def _num(row, key):
    try:
        value = row.get(key)
    except (AttributeError, TypeError):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _text(row, key):
    try:
        value = row.get(key)
    except (AttributeError, TypeError):
        return ""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _money(value):
    return f"{float(value):,.2f}"


def _whole(value):
    number = float(value)
    if abs(number - round(number)) < 0.001:
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _days(value):
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _join_text(value):
    if hasattr(value, "strftime"):
        return f"{value.day} {value.strftime('%b %Y')}"
    text = _plain(value)
    return text.split(" ")[0] if "00:00:00" in text else text


def _dates_for_month(text, month):
    from payroll.documents.breakdown import dates_in_month
    return dates_in_month(text, month)


def _punch_marks(row, info):
    from payroll.documents.breakdown import missing_punch_marks
    month = info.get("month") if isinstance(info, dict) else None
    text = _text(row, "punch_missing") or _text(row, "missing_text")
    return missing_punch_marks(text, month)


def _detail_lines(row, info):
    from payroll.documents.breakdown import breakdown_lines
    month = info.get("month") if isinstance(info, dict) else None
    year = info.get("year") if isinstance(info, dict) else None
    return breakdown_lines(row, month, year)


def _plain(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def slip_content(row, info=None):
    """The lines on an office slip. Full monthly salary is shown, then the amount actually paid."""
    info = info or {}
    full = _num(row, "full_salary") or _num(row, "basic_salary")
    basic = _num(row, "basic_salary")
    month_days = int(_num(row, "month_days") or 0)
    counted = int(_num(row, "counted_days") or 0)
    partial = bool(month_days and counted and counted < month_days and abs(full - basic) > 0.009)
    leave_pay = _num(row, "leave_pay")
    leave_days = _num(row, "unused_annual_days")
    payments = []
    included = 0.0
    payments.append(("Basic Salary 基本月薪", full if partial else basic, ""))
    if partial:
        payments.append((
            _text(row, "period") or f"{counted} Day(s)",
            basic,
            f"(${_whole(full)}/{month_days}*{counted})",
        ))
        included += basic
    else:
        included += basic
    if leave_pay > 0.009:
        days = _days(leave_days) if leave_days else ""
        note = f"(${_whole(full * 12)}/365*{days})" if days else ""
        payments.append(("Unused Annual Leave 未使用年假", leave_pay, note))
        included += leave_pay
    other = _num(row, "other_income") - leave_pay
    if other > 0.009:
        payments.append(("其他收入", other, ""))
        included += other
    if _num(row, "ot_pay") > 0.009:
        payments.append(("Overtime 加班費", _num(row, "ot_pay"), ""))
        included += _num(row, "ot_pay")
    if _num(row, "bonus_paid") > 0.009:
        payments.append(("Attendance bonus 勤工獎", _num(row, "bonus_paid"), ""))
        included += _num(row, "bonus_paid")
    manual = _num(row, "manual_delta")
    if manual > 0.009:
        payments.append(("其他調整", manual, ""))
        included += manual
    deductions = []
    unpaid = _num(row, "unpaid_amount")
    late_pay = min(_num(row, "minute_deduct_amount"), unpaid)
    leave_unpaid = round(unpaid - late_pay, 2)
    if leave_unpaid > 0.009:
        deductions.append(("NPL 無薪假", leave_unpaid))
        included -= leave_unpaid
    if late_pay > 0.009:
        mins = int(round(_num(row, "salary_deduct_minutes")))
        deductions.append((f"遲到 {mins} 分鐘" if mins else "遲到", late_pay))
        included -= late_pay
    for key, label in (
        ("rent", "Rent 租金"),
        ("water", "Water 水費"),
        ("electricity", "Electricity 電費"),
    ):
        amount = _num(row, key)
        if amount > 0.009:
            deductions.append((label, amount))
            included -= amount
    if manual < -0.009:
        deductions.append(("其他調整", -manual))
        included += manual
    mpf_employee = _num(row, "mpf_employee")
    net = _num(row, "net")
    subtotal = round(net + mpf_employee, 2)
    gap = round(subtotal - included, 2)
    if gap >= 0.05:
        payments.append(("其他收入", gap, ""))
    elif gap <= -0.05:
        deductions.append(("其他扣除", -gap))
    health, transport = _allowances(row)
    transport_note = _prorate_note(row, "standing_transport", transport, partial, month_days, counted)
    health_note = _prorate_note(row, "standing_health", health, partial, month_days, counted)
    year = int(info.get("year") or 0) or None
    unused_label = _text(row, "al_1_label")
    if "未使用" not in unused_label:
        unused_label = f"{year} Unused Annual Leave {year}未使用年假" if year else "Unused Annual Leave 未使用年假"
    shown_days = leave_days if leave_days else _num(row, "al_1_days") + _num(row, "al_2_days")
    return {
        "company": _company_name(info),
        "name": _text(row, "slip_name"),
        "nickname": _nickname(row),
        "department": _text(row, "department"),
        "position": _text(row, "position"),
        "join_date": _join_text(row.get("join_date") if hasattr(row, "get") else ""),
        "period": _text(row, "period"),
        "file_no": _file_no(row, info),
        "unused_label": unused_label,
        "unused_days": shown_days,
        "sick_days": _num(row, "sick_days"),
        "annual_taken": _num(row, "annual_taken"),
        "annual_dates": _dates_for_month(_text(row, "annual_dates"), info.get("month")),
        "unpaid_days": _num(row, "unpaid_days"),
        "birthday_days": _num(row, "birthday_days"),
        "absent_mins": _num(row, "salary_deduct_minutes") or _num(row, "absent_mins"),
        "payments": payments,
        "deductions": deductions,
        "punch_marks": _punch_marks(row, info),
        "subtotal": subtotal,
        "mpf_employee": mpf_employee,
        "mpf_employer": _num(row, "mpf_employer"),
        "total": net,
        "health": health,
        "health_note": health_note,
        "transport": transport,
        "transport_note": transport_note,
        "logo": _logo_path(),
        "details": _detail_lines(row, info),
        "pay_date": _text(info, "pay_date_override"),
        "salary_reference": _text(row, "salary_reference"),
        "allowance_reference": _text(row, "allowance_reference"),
    }


def _allowances(row):
    health = _num(row, "final_health")
    transport = _num(row, "final_transport")
    paid = _num(row, "allowance_amount")
    if abs(paid - (health + transport)) < 0.02:
        return health, transport
    health = _num(row, "standing_health")
    transport = _num(row, "standing_transport")
    if health == 0 and transport == 0:
        transport = paid
    return health, transport


def _prorate_note(row, key, paid, partial, month_days, counted):
    standing = _num(row, key)
    if not partial or not standing or not month_days:
        return ""
    expected = round(standing / month_days * counted, 2)
    if abs(expected - paid) >= 0.02:
        return ""
    return f"(${_whole(standing)}/{month_days}*{counted})"


def _nickname(row):
    slip = _text(row, "slip_name")
    extra = [word for word in _text(row, "name_en").split() if word not in slip]
    return extra[-1] if extra else ""


def _file_no(row, info):
    shown = _text(row, "staff_id")
    try:
        from payroll.staff.staff import read_batch
        batch = read_batch(info) if info else None
    except (OSError, KeyError, TypeError, ValueError):
        batch = None
    if batch and "-" in shown:
        shown = f"{batch}-{shown.split('-', 1)[1]}"
    if "-" not in shown:
        return shown
    prefix, suffix = shown.split("-", 1)
    return f"#{prefix}- {suffix}"


def _company_from_text(text):
    head = str(text or "").strip().split("Employee")[0].strip()
    if "Limited" in head or "有限公司" in head:
        return head
    return ""


def _company_name(info):
    template = info.get("slip_template") if isinstance(info, dict) else None
    if not template:
        try:
            from payroll.core.config import book_info
            template = book_info(info, "admin").get("slip_template")
        except (KeyError, TypeError, ValueError, OSError, SystemExit):
            template = None
    path = Path(str(template)) if template else None
    found = ""
    if path is not None and path.is_file() and path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = book.worksheets[0]
            for cells in sheet.iter_rows(max_row=40, max_col=3, values_only=True):
                for value in cells:
                    text = _plain(value)
                    if "有限公司" in text or "Limited" in text:
                        found = text
                        break
                if found:
                    break
        finally:
            book.close()
    elif path is not None and path.is_file() and path.suffix.lower() == ".docx":
        import zipfile
        try:
            xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
        except (OSError, KeyError, zipfile.BadZipFile):
            xml = ""
        found = _company_from_text(re.sub(r"<[^>]+>", "", xml))
    if found:
        return found
    try:
        from payroll.core.settings import daka
        return str(daka().get("company") or "")
    except (OSError, TypeError):
        return ""


def _logo_path():
    from payroll.core.config import CODE_ROOT, home
    candidates = [
        CODE_ROOT / "app" / "assets" / "logo.jpg",
        home() / "assets" / "logo.jpg",
        home() / "app" / "assets" / "logo.jpg",
    ]
    try:
        from payroll.core.settings import load
        root = Path(str(load().get("_path") or "")).resolve().parent
        candidates.append(root / "assets" / "logo.jpg")
        logo = str((load().get("daka") or {}).get("logo") or "")
        if logo:
            candidates.append(root / logo)
            candidates.append(CODE_ROOT / logo)
    except (OSError, TypeError):
        pass
    for path in candidates:
        if path.is_file():
            return path
    return None


def _document(row, info=None):
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="pt")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.add_font("slip", "", str(FONT))
    _draw(pdf, slip_content(row, info))
    return pdf


def render_office_pdf(row, info=None):
    """The slip as PDF bytes, for a download button."""
    return bytes(_document(row, info).output())


def write_office_pdf(path, row, info=None):
    """Write one salary slip. The file is a PDF, not a spreadsheet."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _document(row, info).output(str(target))
    return target


def _draw(pdf, content):
    left, right = 36, 559
    width = right - left
    mid = left + width * 0.56
    if content["logo"]:
        pdf.image(str(content["logo"]), x=right - 156, y=18, w=150)
        _text_at(pdf, left, 30, right - left - 160, 18, content["company"], 11, "C")
    else:
        _text_at(pdf, left, 30, width, 18, content["company"], 11, "C")
    y = 72
    y = _pair(pdf, left, y, width, "Employee 員工:", content["name"], content["nickname"])
    y = _pair(pdf, left, y, width, "Department 部門:", content["department"], "")
    y += 6
    _text_at(pdf, left, y, width, 14, "Salary Slip 薪酬單", 11, "C")
    y += 16
    _text_at(pdf, mid, y, right - mid, 13, "Confidential File No.:", 8, "L")
    _text_at(pdf, mid + 130, y, right - mid - 130, 13, content["file_no"], 8, "R")
    y += 14
    y = _pair(pdf, left, y, width, "Position 職位:", content["position"], "")
    y = _pair(pdf, left, y, width, "Join Date 入職日期:", content["join_date"], "")
    box_top = y
    y = _leave_row(pdf, left, y, right, mid, "Payment Period 計薪周期:", content["period"], content["unused_label"], content["unused_days"])
    y = _leave_row(pdf, left, y, right, mid, "Sick Leave 病假:", _day_text(content["sick_days"]), "Annual Leave 年假:", content["annual_taken"], content["annual_dates"])
    y = _leave_row(pdf, left, y, right, mid, "NPL 無薪假:", _day_text(content["unpaid_days"]), "Birthday Leave 生日假:", content["birthday_days"])
    pdf.rect(left, box_top - 2, width, y - box_top + 4)
    y += 12
    y = _pay_box(pdf, left, y, right, mid, content)
    y = _autopay(pdf, left, y + 4, right, content["pay_date"], content["salary_reference"])
    y += 12
    y = _allowance_box(pdf, left, y, right, content)
    if content["health"] or content["transport"] or content["allowance_reference"]:
        y = _autopay(pdf, left, y + 4, right, content["pay_date"], content["allowance_reference"])
    y = _detail_box(pdf, left, y + 14, right, content)
    pdf.set_text_color(0, 0, 0)
    _text_at(pdf, left, min(y + 16, 800), width, 12, FOOTER, 7, "C")


def _day_text(days, dates=""):
    text = f"{_days(days)} Day(s)"
    if dates:
        return f"{dates}   {text}"
    return text


def _pair(pdf, left, y, width, label, value, extra):
    _text_at(pdf, left, y, 118, 13, label, 8, "L")
    _text_at(pdf, left + 120, y, 220, 13, value, 8, "L")
    if extra:
        _text_at(pdf, left + 340, y, 80, 13, extra, 8, "L")
    return y + 14


def _leave_row(pdf, left, y, right, mid, left_label, left_value, right_label, right_days, right_dates=""):
    _text_at(pdf, left + 4, y, 130, 13, left_label, 8, "L")
    _text_at(pdf, left + 136, y, mid - left - 144, 13, left_value, 8, "L", fit=True)
    _text_at(pdf, mid + 4, y, right - mid - 86, 13, right_label, 7, "L", fit=True)
    if right_dates:
        _text_at(pdf, mid + 150, y, 70, 13, right_dates, 7, "L")
    _text_at(pdf, right - 78, y, 72, 13, _day_text(right_days) if not isinstance(right_days, str) else right_days, 8, "R")
    return y + 15


def _pay_box(pdf, left, y, right, mid, content):
    top = y
    _text_at(pdf, left + 6, y, mid - left, 14, "Payment 收入", 8, "C")
    absent = content["absent_mins"]
    deduction = "Deduction  扣除項目"
    if absent:
        deduction = f"Total Absent mins 缺勤分鐘: {_days(absent)}"
    _text_at(pdf, mid, y, right - mid, 14, deduction, 8, "C")
    y += 16
    pdf.line(left, y, right, y)
    split = y
    for label, amount, note in content["payments"]:
        _text_at(pdf, left + 6, y, mid - left - 90, 12, label, 8, "L")
        _text_at(pdf, mid - 86, y, 28, 12, "HKD$", 8, "L")
        _text_at(pdf, mid - 78, y, 70, 12, _money(amount), 8, "R")
        y += 12
        if note:
            pdf.set_text_color(70, 70, 70)
            _text_at(pdf, left + 8, y, mid - left - 16, 11, note, 7, "L")
            pdf.set_text_color(0, 0, 0)
            y += 11
    for label, amount in content["deductions"]:
        _text_at(pdf, mid + 6, split, right - mid - 90, 12, label, 8, "L")
        _text_at(pdf, right - 86, split, 28, 12, "-HKD$", 8, "L")
        _text_at(pdf, right - 78, split, 72, 12, _money(amount), 8, "R")
        split += 13
    for mark in content.get("punch_marks") or []:
        _text_at(pdf, mid + 6, split, right - mid - 12, 12, mark, 8, "L", fit=True)
        split += 13
    y = max(y, split) + 36
    pdf.line(mid, top, mid, y)
    pdf.line(left, y, right, y)
    y = _total_line(pdf, left, y, right, "Subtotal 小計", "HKD$", content["subtotal"], 8)
    if content["mpf_employee"] or content["mpf_employer"]:
        y = _total_line(pdf, left, y, right, "Employee MPF 強積金僱員供款  5%", "-HKD$", content["mpf_employee"], 8)
        y = _total_line(pdf, left, y, right, "Employer MPF 強積金僱主供款  5%", "-HKD$", content["mpf_employer"], 8)
    pdf.line(left, y, right, y)
    y = _total_line(pdf, left, y, right, "Total 總收入", "HKD$", content["total"], 10)
    pdf.rect(left, top, right - left, y - top)
    return y


def _total_line(pdf, left, y, right, label, currency, amount, size):
    _text_at(pdf, left + 6, y, 280, 14, label, size, "L")
    _text_at(pdf, right - 130, y, 46, 14, currency, size, "R")
    _text_at(pdf, right - 82, y, 76, 14, _money(amount), size, "R")
    return y + 14


def _autopay(pdf, left, y, right, pay_date, reference):
    when = pay_date or ""
    number = reference or ""
    if not when and not number:
        return y
    _text_at(
        pdf, left + 6, y, right - left - 12, 12,
        f"By Auto Pay 經自動轉賬 {when}  交易編號：{number}", 8, "L",
    )
    return y + 14


def _detail_box(pdf, left, y, right, content):
    lines = [line for line in content.get("details") or [] if line]
    if not lines:
        return y
    top = y
    _text_at(pdf, left + 6, y, right - left - 12, 12, "明細 Breakdown", 8, "L")
    y += 13
    pdf.set_font("slip", size=7)
    for line in lines:
        pdf.set_xy(left + 6, y)
        pdf.multi_cell(right - left - 12, 10, line)
        y = pdf.get_y()
        if y > 760:
            break
    y += 4
    pdf.rect(left, top, right - left, y - top)
    return y


def _allowance_box(pdf, left, y, right, content):
    top = y
    _text_at(pdf, left + 6, y, 200, 13, "Allowance", 8, "L")
    y += 13
    y = _allowance_line(pdf, left, y, "Health Allowance", content["health"], content["health_note"])
    y = _allowance_line(pdf, left, y, "Transportation Allowance", content["transport"], content["transport_note"])
    pdf.line(left, y + 2, right, y + 2)
    y += 4
    _text_at(pdf, left + 120, y, 160, 14, "Total 總收入", 10, "R")
    _text_at(pdf, left + 286, y, 40, 14, "HKD$", 10, "L")
    _text_at(pdf, left + 320, y, 70, 14, _money(content["health"] + content["transport"]), 10, "R")
    y += 16
    pdf.rect(left, top, right - left, y - top)
    return y


def _allowance_line(pdf, left, y, label, amount, note):
    _text_at(pdf, left + 6, y, 180, 12, label, 8, "L")
    _text_at(pdf, left + 190, y, 36, 12, "HKD$", 8, "L")
    _text_at(pdf, left + 220, y, 70, 12, _money(amount), 8, "R")
    y += 12
    if note:
        pdf.set_text_color(70, 70, 70)
        _text_at(pdf, left + 8, y, 180, 11, note, 7, "L")
        pdf.set_text_color(0, 0, 0)
        y += 11
    return y


def _text_at(pdf, x, y, width, height, text, size, align, fit=False):
    shown = "" if text is None else str(text)
    if fit and shown:
        pdf.set_font("slip", size=size)
        while size > 6 and pdf.get_string_width(shown) > width - 1:
            size -= 0.4
            pdf.set_font("slip", size=size)
    pdf.set_font("slip", size=size)
    pdf.set_xy(x, y)
    pdf.cell(width, height, shown, align=align)
