"""Read the full-time salary-slip document into one record per person."""

import re
from docx import Document

from payroll.documents.docxutil import iter_unique_cells

MONEY = re.compile(r"([+-])?\s*(?:HKD|HK)\s*\$?\s*([0-9,]+\.\d{2})")
DAYS = re.compile(r"(-?\d+(?:\.\d+)?)\s*Days?", re.I)
FILE_NO = re.compile(r"#\s*(\d+)\s*-\s*(\d+)")


def _money_values(text):
    found = []
    for sign, num in MONEY.findall(text or ""):
        value = float(num.replace(",", ""))
        if sign == "-":
            value = -value
        found.append(value)
    return found


def _first_days(text):
    match = DAYS.search(text or "")
    return float(match.group(1)) if match else None


def _clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def split_name(employee_line):
    raw = employee_line.split("：", 1)[-1].split(":", 1)[-1].strip()
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", raw))
    english = re.sub(r"[\u4e00-\u9fff]", " ", raw)
    english = re.sub(r"\s+", " ", english).strip(" :-")
    return raw, english, chinese


def _slip_tables(doc):
    groups = []
    current = []
    for index, table in enumerate(doc.tables):
        blob = "\n".join(cell.text for _, _, cell in iter_unique_cells(table))
        if "Employee員工" in blob.replace(" ", "") or "Employee員工" in blob:
            if current:
                groups.append(current)
            current = [(index, table)]
        elif current:
            current.append((index, table))
    if current:
        groups.append(current)
    return groups


def _items(table, table_index):
    items = []
    for row, col, cell in iter_unique_cells(table):
        for para_i, paragraph in enumerate(cell.paragraphs):
            text = paragraph.text.strip()
            if not text:
                continue
            items.append({
                "table": table_index,
                "row": row,
                "col": col,
                "para": para_i,
                "text": text,
            })
    return items


def _anchor(item):
    return {key: item[key] for key in ("table", "row", "col", "para")}


def _near_label(items, label_pred, value_pred=None):
    """Value paragraph after a label, in the same row if possible."""
    for index, item in enumerate(items):
        if not label_pred(item["text"]):
            continue
        same_row = [
            other for other in items[index + 1:]
            if other["row"] == item["row"] and other["table"] == item["table"]
        ]
        pool = same_row or items[index + 1:index + 4]
        for other in pool:
            if value_pred is None or value_pred(other["text"]):
                return item, other
        return item, None
    return None, None


def parse_slip_group(tables):
    items = []
    for index, table in tables:
        items.extend(_items(table, index))
    texts = [item["text"] for item in items]
    blob = "\n".join(texts)

    name_item = next(item for item in items if item["text"].startswith("Employee"))
    raw_name, english, chinese = split_name(name_item["text"])
    if not chinese and not english:
        for other in items:
            if other["table"] != name_item["table"] or other["row"] != name_item["row"]:
                continue
            if other is name_item or "部門" in other["text"] or other["text"].startswith("Department"):
                continue
            raw_name, english, chinese = split_name("：" + other["text"])
            if chinese or english:
                name_item = other
                break
    file_match = FILE_NO.search(blob)
    staff_id = f"{file_match.group(1)}-{file_match.group(2)}" if file_match else ""

    def after_colon(prefix):
        for text in texts:
            if prefix in text:
                return text.split("：", 1)[-1].split(":", 1)[-1].strip()
        return ""

    department = after_colon("部門")
    position = after_colon("職位")
    join_date = after_colon("入職日期").lstrip("：: ")
    period = ""
    for text in texts:
        if "計薪周期" in text or "薪周期" in text:
            period = text
            break

    _, basic_item = _near_label(
        items,
        lambda text: text.startswith("Basic Salary"),
        lambda text: bool(_money_values(text)) and not text.startswith("Basic"),
    )
    basic = _money_values(basic_item["text"])[0] if basic_item else 0.0

    pay_items = [item for item in items if basic_item and item["row"] == basic_item["row"] and item["table"] == basic_item["table"]]
    stated_extra = 0.0
    other_income_anchor = None
    for item in pay_items:
        if item is basic_item or item["text"].startswith(("Basic", "Overtime", "OT")):
            continue
        for value in _money_values(item["text"]):
            if value > 0 and abs(value - basic) > 0.001:
                stated_extra += value
                other_income_anchor = item

    basic_col = basic_item["col"] if basic_item else 0
    deduction_items = [item for item in pay_items if item["col"] > basic_col]
    deduction_text = "\n".join(item["text"] for item in deduction_items)
    label_items = [item for item in deduction_items if not _money_values(item["text"]) and not item["text"].startswith("-HK")]
    amount_items = [item for item in deduction_items if _money_values(item["text"]) or item["text"].strip() in {"-HKD$", "-HKD", "-", "–"}]
    # Keep label order and amount order, which the slips list side by side.
    labels = [item["text"] for item in label_items if not item["text"].startswith("(")]
    amounts = []
    amount_anchors = []
    for item in amount_items:
        values = _money_values(item["text"])
        amounts.append(abs(values[-1]) if values else None)
        amount_anchors.append(item)

    unpaid_days = 0.0
    unpaid_match = re.search(r"無薪假\s*(\d+(?:\.\d+)?)\s*天", deduction_text)
    if not unpaid_match:
        unpaid_match = re.search(r"無薪假[:：]?\s*(\d+(?:\.\d+)?)\s*Day", blob)
    if unpaid_match:
        unpaid_days = float(unpaid_match.group(1))
    absent_days = 0.0
    absent_note = ""
    absent_label, absent_value = _near_label(
        items,
        lambda text: text.startswith("缺勤") and "分鐘" not in text,
        lambda text: _first_days(text) is not None,
    )
    if absent_label:
        absent_note = absent_label["text"]
        absent_days = _first_days(absent_value["text"]) if absent_value else 0.0

    def _paired(keyword):
        for index, label in enumerate(labels):
            if keyword in label and index < len(amounts):
                return amounts[index], amount_anchors[index]
        return None, None

    rent, rent_anchor = _paired("租金")
    rent = rent or 0.0
    water, water_anchor = _paired("水費")
    water = water or 0.0
    if water == 0:
        for amount, anchor in zip(amounts, amount_anchors):
            if amount is not None and 0 < amount < 30:
                water = amount
                water_anchor = anchor

    unpaid_amt, unpaid_anchor = (0.0, None)
    if unpaid_days:
        expected = round(basic / 31 * unpaid_days, 2)
        for amount, anchor in zip(amounts, amount_anchors):
            if amount is not None and abs(amount - expected) < 0.05:
                unpaid_amt = amount
                unpaid_anchor = anchor
                break
        if unpaid_amt == 0:
            unpaid_amt = expected

    minute_match = re.search(r"缺勤分鐘[:：]?\s*(\d+)", blob)
    absent_mins = float(minute_match.group(1)) if minute_match else 0.0
    absent_lines = []
    absent_anchors = []
    absent_header = None
    capture = False
    for item in items:
        if "缺勤分鐘" in item["text"]:
            absent_header = item
            capture = True
            rest = re.sub(r"^.*?缺勤分鐘[:：]?\s*\d*\s*", "", item["text"]).strip()
            if re.search(r"\d", rest) and "HKD" not in rest and "HK$" not in rest:
                absent_lines.append(item["text"])
                absent_anchors.append(_anchor(item))
            continue
        if capture:
            if item["text"].startswith("HK") or item["text"].startswith("-HK") or item["text"].startswith("+HK"):
                break
            if re.match(r"^\d{1,2}/\d{1,2}", item["text"]) or "無薪" in item["text"]:
                if "無薪" in item["text"]:
                    break
                absent_lines.append(item["text"])
                absent_anchors.append(_anchor(item))
            else:
                break

    ot_lines = []
    for item in items:
        if item["text"].startswith("OT (") or re.match(r"^\d{1,2}/\d{1,2}", item["text"]) or "已補" in item["text"]:
            if "缺勤分鐘" in item["text"]:
                continue
            ot_lines.append(item["text"])
    ot_net = None
    ot_formula = ""
    for line in ot_lines:
        if line.startswith("OT"):
            ot_formula = line
            match = re.search(r"=\s*(-?\d+(?:\.\d+)?)\s*$", line.replace("（", "("))
            if not match:
                match = re.search(r"=\s*(-?\d+(?:\.\d+)?)", line)
            if match:
                ot_net = float(match.group(1))

    mpf_ee = mpf_er = 0.0
    mpf_ee_anchor = mpf_er_anchor = None
    scheme = "rent" if "租金" in deduction_text else "mpf"
    for item in items:
        values = _money_values(item["text"])
        if "僱員供款" in item["text"] and values:
            mpf_ee = abs(values[-1])
            mpf_ee_anchor = item
        elif item["text"].startswith("-HK") and mpf_ee_anchor and item["table"] == mpf_ee_anchor["table"] and mpf_ee == 0:
            mpf_ee = abs(_money_values(item["text"])[-1])
            mpf_ee_anchor = item
        if "僱主供款" in item["text"] and values:
            mpf_er = abs(values[-1])
            mpf_er_anchor = item
    # MPF amounts usually sit in the next cell, not inside the label.
    if scheme == "mpf":
        for label, holder in (("僱員供款", "ee"), ("僱主供款", "er")):
            label_item, value_item = _near_label(items, lambda text, label=label: label in text, lambda text: bool(_money_values(text)))
            if value_item:
                amount = abs(_money_values(value_item["text"])[-1])
                if holder == "ee":
                    mpf_ee = amount
                    mpf_ee_anchor = value_item
                else:
                    mpf_er = amount
                    mpf_er_anchor = value_item

    total = None
    total_anchor = None
    _, total_item = _near_label(items, lambda text: text.startswith("Total"), lambda text: bool(_money_values(text)))
    if total_item:
        total = abs(_money_values(total_item["text"])[-1])
        total_anchor = total_item
    subtotal = None
    subtotal_anchor = None
    _, sub_item = _near_label(items, lambda text: "小計" in text, lambda text: bool(_money_values(text)))
    if sub_item:
        subtotal = abs(_money_values(sub_item["text"])[-1])
        subtotal_anchor = sub_item

    if "租金" in deduction_text and not rent and total is not None:
        inferred = round(basic * 0.1, 2)
        trial = basic - inferred - unpaid_amt - water - mpf_ee
        if abs(trial - total) < 0.05:
            rent = inferred
    formula_core = basic - rent - unpaid_amt - water - mpf_ee
    other_income = 0.0
    if stated_extra and total is not None and abs(formula_core + stated_extra - total) < 0.05:
        other_income = stated_extra
    manual_delta = round((total or 0) - (formula_core + other_income), 2) if total is not None else 0.0

    bonus = None
    bonus_anchor = None
    bonus_lines = {}
    bonus_overall = None
    for item in items:
        values = _money_values(item["text"])
        month_line = re.search(r"(\d{1,2})月份勤工獎金", item["text"])
        if month_line and values:
            bonus_lines[int(month_line.group(1))] = abs(values[-1])
        if "總獎金" in item["text"] and values:
            bonus_overall = abs(values[-1])
        if "勤工獎金" in item["text"] and "OCT" in item["text"].upper() or (
            "10月份勤工獎金" in item["text"]
        ):
            if values and bonus is None:
                bonus = abs(values[-1])
                bonus_anchor = item
    bonus_eligible = bonus is not None

    allowance_amount = 0.0
    allowance_desc = ""
    allowance_anchor = None
    pay_tables = {item["table"] for item in items if item["text"].startswith("Basic Salary")}
    for item in items:
        if item["table"] in pay_tables:
            continue
        if not any(word in item["text"] for word in ("健康津貼", "交通津貼", "Health Allowance", "交通")):
            continue
        if "勤工" in item["text"] or "超時" in item["text"]:
            continue
        allowance_desc = item["text"]
        money_items = [
            other for other in items
            if other["table"] == item["table"] and _money_values(other["text"])
        ]
        if not money_items:
            continue
        allowance_anchor = money_items[-1]
        allowance_amount = max(abs(value) for other in money_items for value in _money_values(other["text"]))
        break

    def days_for(pred):
        label, value = _near_label(items, pred, lambda text: _first_days(text) is not None)
        number = _first_days(value["text"]) if value else None
        return label, value, number

    al_lines = []
    for item in items:
        if "未使用年假" in item["text"]:
            _, value, number = days_for(lambda text, item=item: text == item["text"])
            if number is not None:
                al_lines.append({"label": item["text"], "days": number, "anchor": _anchor(value) if value else None, "label_anchor": _anchor(item)})

    opening_label, opening_value, opening_rest = days_for(lambda text: "上月剩餘例假" in text)
    ent_label, ent_value, rest_entitlement = days_for(lambda text: "本月例假" in text)
    taken_label, taken_value, taken_rest = days_for(lambda text: "已放" in text)
    unused_label, unused_value, unused_rest = days_for(lambda text: "未使用例假" in text)
    sh_label, sh_value, statutory = days_for(lambda text: "法定" in text)
    sick_label, sick_value, sick = days_for(lambda text: "病假" in text)
    _, al_taken_value, al_taken = days_for(lambda text: text.startswith("Annual Leave") or text.startswith("年假"))
    bdl_label, bdl_value, birthday = days_for(lambda text: "生日" in text or text.startswith("BDL") or text.startswith("BL"))

    taken_dates = ""
    if taken_label:
        taken_dates = re.sub(r"^.*?[：:]\s*", "", taken_label["text"])
        if taken_dates == taken_label["text"]:
            taken_dates = ""

    anchors = {
        "name": _anchor(name_item),
        "basic": _anchor(basic_item) if basic_item else None,
        "total": _anchor(total_anchor) if total_anchor else None,
        "subtotal": _anchor(subtotal_anchor) if subtotal_anchor else None,
        "mpf_ee": _anchor(mpf_ee_anchor) if mpf_ee_anchor else None,
        "mpf_er": _anchor(mpf_er_anchor) if mpf_er_anchor else None,
        "bonus": _anchor(bonus_anchor) if bonus_anchor else None,
        "opening_rest": _anchor(opening_value) if opening_value else None,
        "rest_entitlement": _anchor(ent_value) if ent_value else None,
        "taken_rest": _anchor(taken_value) if taken_value else None,
        "taken_label": _anchor(taken_label) if taken_label else None,
        "unused_rest": _anchor(unused_value) if unused_value else None,
        "statutory": _anchor(sh_value) if sh_value else None,
        "sick": _anchor(sick_value) if sick_value else None,
        "annual_taken": _anchor(al_taken_value) if al_taken_value else None,
        "birthday": _anchor(bdl_value) if bdl_value else None,
        "period": _anchor(next(item for item in items if item["text"] == period)) if period else None,
        "rent": _anchor(rent_anchor) if rent_anchor else None,
        "water": _anchor(water_anchor) if water_anchor else None,
        "unpaid": _anchor(unpaid_anchor) if unpaid_anchor else None,
        "other_income": _anchor(other_income_anchor) if other_income_anchor else None,
        "allowance": _anchor(allowance_anchor) if allowance_anchor else None,
        "absent_header": _anchor(absent_header) if absent_header else None,
    }
    ot_anchors = [_anchor(item) for item in items if item["text"] in ot_lines or item["text"].startswith("OT (")]

    rent_base = "basic"
    if rent and unpaid_amt and abs(rent - round((basic - unpaid_amt) * 0.1, 2)) < 0.02:
        rent_base = "after_unpaid"
    elif rent and abs(rent - round(basic * 0.1, 2)) < 0.02:
        rent_base = "basic"

    return {
        "staff_id": staff_id,
        "slip_name": raw_name,
        "name_en": english,
        "name_zh": chinese,
        "department": department,
        "position": position,
        "join_date": join_date,
        "period": period,
        "basic_salary": basic,
        "scheme": scheme,
        "rent": rent,
        "rent_base": rent_base if rent else "",
        "water": water,
        "unpaid_days": unpaid_days,
        "unpaid_amount": unpaid_amt,
        "absent_days": absent_days,
        "absent_note": absent_note,
        "absent_mins": absent_mins,
        "absent_lines": absent_lines,
        "absent_anchors": absent_anchors,
        "other_income": other_income,
        "stated_extra": stated_extra,
        "manual_delta": manual_delta,
        "ot_lines": ot_lines,
        "ot_formula": ot_formula,
        "ot_net": ot_net,
        "ot_anchors": ot_anchors,
        "mpf_employee": mpf_ee,
        "mpf_employer": mpf_er,
        "subtotal": subtotal,
        "net": total,
        "bonus": bonus,
        "bonus_lines": bonus_lines,
        "bonus_overall": bonus_overall,
        "bonus_eligible": bonus_eligible,
        "allowance_desc": allowance_desc,
        "allowance_amount": allowance_amount,
        "opening_rest": opening_rest or 0,
        "rest_entitlement": rest_entitlement or 0,
        "taken_rest": taken_rest or 0,
        "taken_dates": taken_dates,
        "unused_rest": unused_rest or 0,
        "statutory_days": statutory or 0,
        "sick_days": sick or 0,
        "sick_label": sick_label["text"] if sick_label else "",
        "annual_taken": al_taken or 0,
        "annual_label": "",
        "al_lines": al_lines,
        "birthday_days": birthday or 0,
        "anchors": anchors,
    }


def parse_slips(path):
    document = Document(str(path))
    slips = []
    for group in _slip_tables(document):
        slips.append(parse_slip_group(group))
    return slips


def load_allowances(path):
    import openpyxl
    book = openpyxl.load_workbook(path, data_only=True)
    sheet = book.active
    rows = []
    section = "shop"
    for row in sheet.iter_rows(min_row=1, max_col=12, values_only=True):
        if row[0] == "Office":
            section = "office"
            continue
        if not isinstance(row[0], (int, float)):
            continue
        rows.append({
            "section": section,
            "seq": int(row[0]),
            "name": _clean(row[1]),
            "description": _clean(row[5]),
            "amount": float(row[8] or 0),
            "note": _clean(row[9]) if len(row) > 9 and row[9] else "",
        })
    book.close()
    return rows
