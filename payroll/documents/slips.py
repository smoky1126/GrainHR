"""Fill the salary-slip document and the allowance summary from an approved draft."""

import math
import re
import shutil
from copy import deepcopy
from datetime import datetime

import pandas as pd
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from openpyxl import Workbook

from payroll.core.config import home
from payroll.documents.docxutil import iter_blocks, iter_unique_cells, paragraph_at, set_paragraph_text
from payroll.documents.parse_slips import FILE_NO, MONEY, _slip_tables, parse_slip_group, parse_slips


def _text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def _days(number):
    value = float(number)
    if value.is_integer():
        return str(int(value))
    return str(value)


def _paragraph(doc, anchor):
    return paragraph_at(doc, anchor["table"], anchor["row"], anchor["col"], anchor["para"])


def _put(doc, anchor, text):
    if not anchor:
        return
    set_paragraph_text(_paragraph(doc, anchor), text)


def _put_days(doc, anchor, number):
    if not anchor or number == "" or number is None:
        return
    _put(doc, anchor, f"{_days(number)} Day(s)")


def _replace_money(text, amount):
    match = MONEY.search(text or "")
    if not match:
        return text
    sign = match.group(1) or ""
    raw = match.group(0)
    if "HKD" in raw:
        unit = "HKD$" if "$" in raw else "HKD"
    else:
        unit = "HK$"
    shown = f"{sign}{unit}{abs(float(amount)):,.2f}"
    return text[:match.start()] + shown + text[match.end():]


def _replace_last_money(text, amount):
    matches = list(MONEY.finditer(text or ""))
    if not matches:
        return text
    match = matches[-1]
    sign = match.group(1) or ""
    raw = match.group(0)
    unit = "HKD$" if "HKD" in raw else "HK$"
    if "HKD" in raw and "$" not in raw:
        unit = "HKD"
    shown = f"{sign}{unit}{abs(float(amount)):,.2f}"
    return text[:match.start()] + shown + text[match.end():]


def _put_money(doc, anchor, amount):
    if not anchor:
        return
    paragraph = _paragraph(doc, anchor)
    set_paragraph_text(paragraph, _replace_money(paragraph.text, amount))


def _after_colon(text, value):
    for mark in ("：", ":"):
        if mark in text:
            return text.split(mark, 1)[0] + mark + value
    return value


def _staff_id(row):
    value = row.get("staff_id") if hasattr(row, "get") else ""
    text = _text(value)
    return "" if text.lower() == "nan" else text


def _donor_score(slip):
    score = 0
    if slip.get("allowance_amount"):
        score += 4
    if slip.get("absent_lines"):
        score += 4
    if slip.get("rent_base") == "after_unpaid":
        score += 2
    return score


def _page_break(after_table):
    nxt = after_table.getnext()
    if nxt is not None and nxt.tag == qn("w:p") and nxt.findall(".//" + qn("w:br")):
        return deepcopy(nxt)
    paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    break_mark = OxmlElement("w:br")
    break_mark.set(qn("w:type"), "page")
    run.append(break_mark)
    paragraph.append(run)
    return paragraph


def _join_text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, datetime):
        return f"{value.day} {value.strftime('%B')} {value.year}"
    text = str(value).strip()
    if text.lower() in {"", "nat", "nan"}:
        return ""
    try:
        parsed = pd.to_datetime(text)
    except (TypeError, ValueError):
        return text
    if pd.isna(parsed):
        return ""
    return f"{parsed.day} {parsed.strftime('%B')} {parsed.year}"


def _keep_label(text, value):
    for mark in ("：", ":"):
        if mark in text:
            return text.split(mark, 1)[0] + mark + value
    return text


def _rewrite_paragraph(paragraph, person):
    text = paragraph.text
    staff_id = _staff_id(person)
    name = _text(person.get("slip_name")) or _text(person.get("name_zh"))
    if text.startswith("Employee員工"):
        set_paragraph_text(paragraph, f"Employee員工：{name}")
    elif "Confidential File" in text or re.search(r"#\d+-\d+", text):
        set_paragraph_text(paragraph, re.sub(r"#\d+-\d+", f"#{staff_id}", text))
    elif "部門" in text:
        set_paragraph_text(paragraph, _keep_label(text, _text(person.get("department"))))
    elif "職位" in text:
        set_paragraph_text(paragraph, _keep_label(text, _text(person.get("position"))))
    elif "入職日期" in text:
        set_paragraph_text(paragraph, _keep_label(text, _join_text(person.get("join_date"))))
    elif "未使用年假" in text:
        set_paragraph_text(paragraph, "未使用年假：")
    elif re.search(r"\d+(?:\.\d+)?\s*Day", text):
        set_paragraph_text(paragraph, "0 Day(s)")
    elif text.startswith("OT ("):
        set_paragraph_text(paragraph, "OT (Hours):")
    elif "已補" in text or re.match(r"^\d{1,2}/\d{1,2}", text.strip()):
        set_paragraph_text(paragraph, "")
    elif "缺勤分鐘" in text:
        set_paragraph_text(paragraph, re.sub(r"(缺勤分鐘[:：]\s*)\d*", r"\g<1>0", text, count=1))


def add_missing_slips(document, people):
    """Append a copy of a same-scheme slip for each paid person who has none."""
    if not people:
        return document
    groups = _slip_tables(document)
    parsed = [parse_slip_group(group) for group in groups]
    donors = {}
    for slip, group in zip(parsed, groups):
        scheme = slip.get("scheme") or "mpf"
        score = _donor_score(slip)
        if scheme not in donors or score < donors[scheme][0]:
            donors[scheme] = (score, group)
    if not donors:
        return document
    fallback = donors.get("mpf") or next(iter(donors.values()))
    body = document.element.body
    sect = body.find(qn("w:sectPr"))

    def insert(element):
        if sect is not None:
            sect.addprevious(element)
        else:
            body.append(element)

    for person in people:
        scheme = _text(person.get("scheme")) or "mpf"
        group = donors.get(scheme, fallback)[1]
        insert(_page_break(group[-1][1]._tbl))
        for _index, table in group:
            copy = deepcopy(table._tbl)
            insert(copy)
            wrapped = Table(copy, document)
            for _row, _col, cell in iter_unique_cells(wrapped):
                for paragraph in cell.paragraphs:
                    if paragraph.text.strip():
                        _rewrite_paragraph(paragraph, person)
    return document


LONG_DATE = re.compile(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}")
SHORT_DATE = re.compile(r"\d{1,2}\s+[A-Za-z]+\s+\d{2}(?!\d)")
REF_TAIL = re.compile(r"(交易編號\s*[:：]\s*)\S*")


def short_pay_date(pay_date):
    """4 Nov 2026 becomes 04 NOV 26, the short style already printed on the slips."""
    match = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", _text(pay_date).strip())
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{int(day):02d} {month.upper()} {year[-2:]}"


def autopay_line(text, pay_date, reference):
    """Put this month's date and 交易編號 on one autopay line. A blank number stays blank."""
    updated = "" if text is None else str(text)
    pay_date = _text(pay_date).strip()
    reference = _text(reference).strip()
    if reference.lower() == "nan":
        reference = ""
    if pay_date and LONG_DATE.search(updated):
        updated = LONG_DATE.sub(pay_date, updated, count=1)
    elif pay_date:
        short = short_pay_date(pay_date)
        if short and SHORT_DATE.search(updated):
            updated = SHORT_DATE.sub(short, updated, count=1)
    if "交易編號" in updated:
        updated = REF_TAIL.sub(lambda match: match.group(1) + reference, updated, count=1)
    return updated


def _saved_pay_date(info):
    path = info["adjustments"]
    if not path.exists():
        return ""
    meta = pd.read_excel(path, sheet_name="meta")
    if meta.empty or "pay_date" not in meta.columns:
        return ""
    return _text(meta.iloc[0]["pay_date"])


def _rewrite_autopay(document, draft, info):
    """Each slip keeps its own 交易編號. A personal one wins, otherwise the payroll's salary number."""
    from docx.text.paragraph import Paragraph
    from payroll.staff.staff import read_refs

    salary_ref, _allowance = read_refs(info)
    pay_date = _saved_pay_date(info)
    by_id = {}
    for _, row in draft.iterrows():
        staff_id = _staff_id(row)
        if staff_id:
            by_id[staff_id] = row
    current = ""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            blob = "".join(node.text or "" for node in child.iter(qn("w:t")))
            match = FILE_NO.search(blob)
            if match:
                current = f"{match.group(1)}-{match.group(2)}"
            continue
        if child.tag != qn("w:p"):
            continue
        paragraph = Paragraph(child, document)
        if "自動轉" not in paragraph.text:
            continue
        own = ""
        row = by_id.get(current)
        if row is not None:
            own = _text(row.get("salary_reference")).strip()
            if own.lower() == "nan":
                own = ""
        set_paragraph_text(paragraph, autopay_line(paragraph.text, pay_date, own or salary_ref))


def _rewrite_batch_numbers(document, draft, info):
    """Print this month's batch, for example #245-3, while staff_id stays 243-3."""
    mapping = {}
    for _, row in draft.iterrows():
        staff_id = _staff_id(row)
        if "-" not in staff_id:
            continue
        shown = _display_staff_id(info, staff_id)
        if shown != staff_id:
            mapping[staff_id] = shown
    if not mapping:
        return
    for table in document.tables:
        for _row, _col, cell in iter_unique_cells(table):
            for paragraph in cell.paragraphs:
                match = re.search(r"#\s*(\d+)\s*-\s*(\d+)", paragraph.text)
                if not match:
                    continue
                key = f"{match.group(1)}-{match.group(2)}"
                if key not in mapping:
                    continue
                set_paragraph_text(
                    paragraph,
                    re.sub(r"#\s*\d+\s*-\s*\d+", f"#{mapping[key]}", paragraph.text, count=1),
                )


def _display_staff_id(info, staff_id):
    from payroll.staff.staff import read_batch
    batch = read_batch(info)
    if not batch or "-" not in staff_id:
        return staff_id
    return f"{batch}-{staff_id.split('-', 1)[1]}"


def _quarter_template(info):
    if int(info.get("month") or 0) not in (3, 6, 9, 12):
        return None
    book = info.get("book") or "bg"
    if book == "admin":
        return None
    name = "payslip_md_quarter.docx" if book == "md" else "payslip_bg_quarter.docx"
    path = home() / "templates" / name
    return path if path.exists() else None


def _paint_quarter(document, draft, info):
    """Write the three monthly lines and the quarter total on a September-style slip."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    month = int(info["month"])
    start = ((month - 1) // 3) * 3 + 1
    by_suffix = {}
    for _, row in draft.iterrows():
        by_suffix[_staff_id(row).split("-")[-1]] = row
    current = ""
    for child in document.element.body.iterchildren():
        text = "".join(node.text or "" for node in child.iter(qn("w:t")))
        match = re.search(r"#\s*\d+\s*-\s*(\d+)", text)
        if match:
            current = match.group(1)
        row = by_suffix.get(current)
        if row is None:
            continue
        amounts = {offset: 0.0 for offset in range(3)}
        for part in _text(row.get("bonus_history")).split("、"):
            found = re.search(r"(\d+)月\s*\$?([\d.]+)", part)
            if found and start <= int(found.group(1)) < start + 3:
                amounts[int(found.group(1)) - start] = float(found.group(2))
        if 0 <= month - start <= 2:
            amounts[month - start] = float(row.bonus or 0)
        total = float(row.bonus_paid or 0)
        for node in child.iter(qn("w:p")):
            paragraph = Paragraph(node, document)
            if "總獎金" in paragraph.text:
                set_paragraph_text(paragraph, _replace_last_money(paragraph.text, total))
            elif "月份勤工獎金" in paragraph.text:
                found = re.search(r"(\d{1,2})月", paragraph.text)
                if found and start <= int(found.group(1)) < start + 3:
                    set_paragraph_text(
                        paragraph, _replace_last_money(paragraph.text, amounts[int(found.group(1)) - start]),
                    )
            elif "勤工獎金" in paragraph.text and _money_in(paragraph.text):
                set_paragraph_text(paragraph, _replace_last_money(paragraph.text, total))


def _money_in(text):
    return "HK$" in text or "HKD" in text


def fill_document(info, draft):
    quarter = _quarter_template(info)
    if quarter is not None:
        info = dict(info)
        info["slip_template"] = quarter
        info["_quarter"] = True
    template = info.get("slip_template") or (home() / "templates" / "payslip_bg.docx")
    output = info.get("slip_output") or (info["output"] / "payslips.docx")
    shutil.copyfile(template, output)
    document = Document(str(output))
    known = {parse_slip_group(group)["staff_id"] for group in _slip_tables(document)}
    missing = []
    for _, row in draft.iterrows():
        if "pay_this" in draft.columns and not bool(row.pay_this):
            continue
        staff_id = _staff_id(row)
        if staff_id and staff_id not in known:
            missing.append(row)
    if missing:
        add_missing_slips(document, missing)
        document.save(str(output))
    slips = parse_slips(output)
    document = Document(str(output))
    by_id = {}
    for _, row in draft.iterrows():
        staff_id = str(row.staff_id).strip()
        if not staff_id or staff_id.lower() == "nan":
            continue
        if "pay_this" in draft.columns and not bool(row.pay_this):
            continue
        by_id[staff_id] = row
    for slip in slips:
        row = by_id.get(slip["staff_id"])
        if row is None:
            continue
        anchors = slip["anchors"]
        _put_money(document, anchors.get("basic"), row.basic_salary)
        _put_money(document, anchors.get("subtotal"), row.subtotal)
        _put_money(document, anchors.get("total"), row.net)
        _put_money(document, anchors.get("mpf_ee"), row.mpf_employee)
        _put_money(document, anchors.get("mpf_er"), row.mpf_employer)
        _put_money(document, anchors.get("rent"), row.rent)
        _put_money(document, anchors.get("water"), row.water)
        if float(getattr(row, "electricity", 0) or 0) and anchors.get("water"):
            paragraph = _paragraph(document, anchors["water"])
            if "電費" not in paragraph.text:
                set_paragraph_text(paragraph, f"{paragraph.text}  電費 HKD${float(row.electricity):,.2f}")
        _put_money(document, anchors.get("unpaid"), row.unpaid_amount)
        extra = row.stated_extra or row.other_income
        if extra:
            _put_money(document, anchors.get("other_income"), extra)
        _put_days(document, anchors.get("opening_rest"), row.opening_rest)
        _put_days(document, anchors.get("rest_entitlement"), row.rest_entitlement)
        _put_days(document, anchors.get("taken_rest"), row.taken_rest)
        _put_days(document, anchors.get("unused_rest"), row.unused_rest)
        _put_days(document, anchors.get("statutory"), row.statutory_days)
        _put_days(document, anchors.get("sick"), row.sick_days)
        _put_days(document, anchors.get("annual_taken"), row.annual_taken)
        _put_days(document, anchors.get("birthday"), row.birthday_days)
        if anchors.get("taken_label") and _text(row.taken_dates):
            paragraph = _paragraph(document, anchors["taken_label"])
            set_paragraph_text(paragraph, _after_colon(paragraph.text, _text(row.taken_dates)))
        for index, line in enumerate(slip["al_lines"]):
            column = f"al_{index + 1}_days"
            if column in row and line.get("anchor"):
                _put_days(document, line["anchor"], row[column])
        if anchors.get("bonus") is not None:
            _put_money(document, anchors["bonus"], row.bonus)
        if anchors.get("allowance") and row.allowance_amount:
            paragraph = _paragraph(document, anchors["allowance"])
            set_paragraph_text(paragraph, _replace_last_money(paragraph.text, row.allowance_amount))
        if anchors.get("period"):
            paragraph = _paragraph(document, anchors["period"])
            period = _text(row.get("period")) or info["period_text"]
            set_paragraph_text(paragraph, _after_colon(paragraph.text, period))
        ot_lines = [line for line in _text(row.ot_text).splitlines() if line.strip()]
        if float(row.ot_pay or 0) > 0:
            amount = f"HKD${float(row.ot_pay):.2f}"
            if ot_lines:
                ot_lines[0] = f"{ot_lines[0]} {amount}"
            else:
                ot_lines = [f"加班 {amount}"]
        for index, anchor in enumerate(slip["ot_anchors"]):
            _put(document, anchor, ot_lines[index] if index < len(ot_lines) else "")
        if row.absent_mins and anchors.get("absent_header"):
            paragraph = _paragraph(document, anchors["absent_header"])
            updated = re.sub(
                r"(缺勤分鐘[:：]\s*)\d*",
                rf"\g<1>{int(float(row.absent_mins))}",
                paragraph.text,
                count=1,
            )
            set_paragraph_text(paragraph, updated)
        absent_lines = [line for line in _text(row.absent_text).splitlines() if line.strip()]
        for index, anchor in enumerate(slip.get("absent_anchors") or []):
            if index < len(absent_lines):
                _put(document, anchor, absent_lines[index])

    _rewrite_autopay(document, draft, info)
    _rewrite_batch_numbers(document, draft, info)
    if info.get("_quarter"):
        _paint_quarter(document, draft, info)
    document.save(output)
    return output


def keep_person(document, staff_id):
    """Leave one slip in the document. The match is the number after the hyphen."""
    from docx.oxml.ns import qn
    body = document.element.body
    suffix = str(staff_id).split("-")[-1]
    children = [child for child in body.iterchildren() if child.tag != qn("w:sectPr")]
    blocks = []
    current_id = ""
    current = []
    for child in children:
        text = "".join(node.text or "" for node in child.iter(qn("w:t")))
        match = re.search(r"#\s*(\d+)\s*-\s*(\d+)", text)
        if match and (not current or match.group(2) != current_id):
            if current:
                blocks.append((current_id, current))
            current_id = match.group(2)
            current = [child]
        else:
            current.append(child)
    if current:
        blocks.append((current_id, current))
    keep = []
    for key, elements in blocks:
        if key == suffix:
            keep = elements
            break
    if not keep:
        return False
    for child in children:
        if child not in keep:
            body.remove(child)
    return True


def write_person_slip(info, draft, staff_id):
    """One person's Word slip, plus a PDF when Word is available."""
    person = draft[draft["staff_id"].astype(str) == str(staff_id)]
    if person.empty:
        raise SystemExit(f"找不到 {staff_id}")
    name = _text(person.iloc[0].get("slip_name")).split()[0] or staff_id
    safe = re.sub(r'[<>:"/\\|?*]', "", name).strip() or staff_id
    from payroll.staff.staff import read_batch
    batch = read_batch(info) or staff_id.split("-")[0]
    suffix = staff_id.split("-")[-1]
    folder = info["output"] / "個別"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"#{batch}_{suffix}_{safe}.docx"
    booked = dict(info)
    booked["slip_output"] = target
    fill_document(booked, draft)
    document = Document(str(target))
    keep_person(document, staff_id)
    document.save(str(target))
    pdf = target.with_suffix(".pdf")
    if _to_pdf(target, pdf):
        return pdf
    return target


def _to_pdf(source, target):
    import subprocess
    script = (
        "$word = New-Object -ComObject Word.Application; "
        "$word.Visible = $false; "
        f"$doc = $word.Documents.Open('{source}'); "
        f"$doc.SaveAs([ref]'{target}', [ref]17); "
        "$doc.Close(); $word.Quit()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return target.exists()


def allowance_rows(draft):
    """Shop allowances first, then office. Only people who are paid this month."""
    people = draft
    if "pay_this" in draft.columns:
        people = draft[draft["pay_this"].astype(bool)]
    rows = []
    for _, person in people.iterrows():
        amount = 0.0 if _blank_number(person.get("allowance_amount")) else float(person.allowance_amount)
        section = _text(person.get("allowance_section")).strip().lower()
        if amount <= 0 or section not in {"shop", "office"}:
            continue
        note = _text(person.get("allowance_note")).strip()
        rows.append({
            "section": section,
            "name": _text(person.get("slip_name")).strip(),
            "description": _text(person.get("allowance_desc")).strip(),
            "amount": amount,
            "note": "" if note.lower() == "nan" else note,
        })
    rows.sort(key=lambda row: 0 if row["section"] == "shop" else 1)
    return rows


def _blank_number(value):
    if value is None:
        return True
    try:
        if math.isnan(float(value)):
            return True
    except (TypeError, ValueError):
        return True
    return False


def write_allowance_summary(info, month_title, draft):
    book = Workbook()
    sheet = book.active
    sheet.title = "allowances"
    from payroll.staff.staff import read_refs
    _salary, allowance = read_refs(info)
    from payroll.core.settings import allowance_title
    sheet["B3"] = f"{allowance_title()} - {month_title}"
    sheet["B4"] = f"交易編號：{allowance}"
    row_number = 7
    sequence = 1
    current = None
    for row in allowance_rows(draft):
        section = row["section"]
        if section != current:
            if section == "office":
                row_number += 2
                sheet.cell(row_number, 1, "Office")
                row_number += 2
                sequence = 1
            current = section
        sheet.cell(row_number, 1, sequence)
        sheet.cell(row_number, 2, row["name"])
        sheet.cell(row_number, 6, row["description"])
        sheet.cell(row_number, 9, float(row["amount"]))
        if row["note"]:
            sheet.cell(row_number, 10, row["note"])
        sequence += 1
        row_number += 2
    path = info["output"] / "allowance_summary.xlsx"
    book.save(path)
    return path
