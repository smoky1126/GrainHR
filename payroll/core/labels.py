"""Traditional Chinese text shown to HR. Stored values stay in English."""

import re

from payroll.core.settings import books as book_labels
from payroll.core.settings import manual_pay, varying_pay

REVIEW_HEADINGS = {
    "employee_no": "員工編號",
    "slip_name": "姓名",
    "roster_days": "更表日數",
    "days_worked": "出勤日數",
    "missing_text": "缺卡",
    "late_text": "遲到",
    "early_text": "早退",
    "wrong_text": "異地打卡",
    "day_off_text": "休息日有打卡",
    "leave_text": "更表假期",
    "ot_hours_detected": "加班時數",
    "review": "問題",
    "basic_salary": "基本薪金",
    "net": "淨薪金",
    "mpf_employee": "強積金",
    "bonus": "勤工獎",
    "unused_rest": "剩餘休假",
    "approved": "批准",
    "ot_choice": "加班",
    "ot_hours_paid": "支薪加班時數",
    "unpaid_days": "無薪假",
    "sick_days": "病假",
    "annual_taken": "年假",
    "birthday_days": "生日假",
    "taken_rest": "已休假",
    "taken_dates": "休假日期",
    "statutory_days": "法定假日",
    "ot_text": "加班備註",
    "bonus_override": "獎金調整",
    "manual_delta": "其他調整",
    "note": "備註",
    "roster_unpaid": "更表無薪假",
    "roster_sick": "更表病假",
    "roster_annual": "更表年假",
    "roster_birthday": "更表生日假",
    "roster_rest": "更表休假",
    "roster_rest_dates": "更表休假日期",
    "staff_id": "糧單編號",
}

PAY_HEADINGS = {
    "employee_no": "員工編號",
    "slip_name": "姓名",
    "problem": "問題",
    "roster_name": "更表姓名",
    "basic_salary": "基本薪金",
    "scheme": "計薪方式",
    "rent_amount": "租金",
    "water": "水費",
    "electricity": "電費",
    "bonus_eligible": "勤工獎",
    "rest_days_month": "每月休假",
    "allowance_desc": "津貼說明",
    "transport_amount": "交通津貼",
    "health_amount": "健康津貼",
    "allowance_section": "津貼分類",
    "allowance_note": "津貼備註",
}

DAY_HEADINGS = {
    "Name": "姓名",
    "Date": "日期",
    "Rosters": "更表",
    "Chosen shop": "採用店鋪",
    "Roster cell": "更表內容",
    "DAKA in": "上班",
    "DAKA out": "下班",
    "DAKA place": "打卡地點",
    "Status": "情況",
}

OLD_HEADINGS = {
    "Staff no": "employee_no",
    "Name": "slip_name",
    "Rosters": "roster_days",
    "Days worked": "days_worked",
    "Missing punches": "missing_text",
    "Late": "late_text",
    "Early leave": "early_text",
    "Wrong shop": "wrong_text",
    "Worked on day off": "day_off_text",
    "Leave from roster": "leave_text",
    "Overtime hours": "ot_hours_detected",
    "Problem": "review",
    "Basic salary": "basic_salary",
    "Net pay": "net",
    "MPF": "mpf_employee",
    "Attendance bonus": "bonus",
    "Unused rest days": "unused_rest",
    "Approve": "approved",
    "Overtime": "ot_choice",
    "Overtime hours paid": "ot_hours_paid",
    "Unpaid days": "unpaid_days",
    "Sick days": "sick_days",
    "Annual leave days": "annual_taken",
    "Birthday leave": "birthday_days",
    "Rest days taken": "taken_rest",
    "Rest dates": "taken_dates",
    "Statutory days": "statutory_days",
    "Overtime note": "ot_text",
    "Bonus override": "bonus_override",
    "Extra adjustment": "manual_delta",
    "Note": "note",
    "Roster unpaid": "roster_unpaid",
    "Roster sick": "roster_sick",
    "Roster annual": "roster_annual",
    "Roster birthday": "roster_birthday",
    "Roster rest": "roster_rest",
    "Roster rest dates": "roster_rest_dates",
    "Staff id": "staff_id",
    "Roster name": "roster_name",
    "Scheme": "scheme",
    "Rent rate": "rent_rate",
    "Rent base": "rent_base",
    "Water": "water",
    "Rest days per month": "rest_days_month",
    "Allowance description": "allowance_desc",
    "Allowance amount": "allowance_amount",
    "Allowance section": "allowance_section",
    "Allowance note": "allowance_note",
}

STATUS = {
    "worked": "正常",
    "missing punch": "全天缺卡",
    "missing clock-in": "上班缺卡",
    "missing clock-out": "下班缺卡",
    "leave": "請假",
    "worked on day off": "休息日有打卡",
    "punched with no shift": "無排班但有打卡",
    "not in DAKA": "DAKA 沒有此人",
    "off": "休息",
    "two shifts": "兩份更表同日有更",
}

YES = {"Y": "是", "N": "否"}
YES_STORED = {"是": "Y", "否": "N", "Y": "Y", "N": "N"}
OT = {"": "", "Pay": "支薪", "Exchange": "補鐘"}
OT_STORED = {"支薪": "Pay", "補鐘": "Exchange", "Pay": "Pay", "Exchange": "Exchange", "": ""}
SCHEME = {"mpf": "本地員工（扣強積金）", "rent": "內地勞工（扣租金）", "none": "不扣強積金"}
SCHEME_STORED = {
    "本地員工（扣強積金）": "mpf", "內地勞工（扣租金）": "rent", "不扣強積金": "none",
    "強積金": "mpf", "租金": "rent", "mpf": "mpf", "rent": "rent", "none": "none",
}
BOOKS = book_labels()
RENT_BASE = {"basic": "基本薪金", "after_unpaid": "扣無薪後"}
RENT_BASE_STORED = {"基本薪金": "basic", "扣無薪後": "after_unpaid", "basic": "basic", "after_unpaid": "after_unpaid"}
SECTION = {"": "", "shop": "店舖", "office": "寫字樓"}
SECTION_STORED = {"店舖": "shop", "寫字樓": "office", "shop": "shop", "office": "office", "": ""}

LEFT = "已離職，不發薪"
NOT_IN_STAFF = "員工檔沒有此人"
NO_ROSTER_NAME = "未連結更表姓名"
DUPLICATE = "員工編號重複"
NEW_JOINER = "新同事，未設定薪金"
VARYING_PAY = varying_pay()
VARYING_PAY_NOTE = "老闆，請核對本月基本薪金。"
MANUAL_PAY = manual_pay()
PART_TIME = "兼職，另一次過數（%s和 %s 分開）" % (BOOKS.get("bg", ""), BOOKS.get("md", ""))
NOT_LINKED = "更表姓名未連結"
VIEW_ONLY = "只供查看，請在薪酬系統內修改"

_NOTE_PATTERNS = (
    (re.compile(r"total differs from the formula by (.+)"), "總數同公式相差 {0}"),
    (re.compile(r"slip shows extra (.+) that is not in the total"), "糧單有額外 {0}，沒有計入總數"),
    (re.compile(r"rest balance on the slip is (.+), formula gives (.+)"), "糧單剩餘休假 {0}，公式 {1}"),
    (re.compile(r"attendance bonus on the slip is (.+), rule gives (.+)"), "舊糧單有勤工獎 ${0}，但按規則應為 ${1}，已沿用舊糧單金額。"),
    (re.compile(r"糧單勤工獎 (.+)，規則 (.+)"), "舊糧單有勤工獎 ${0}，但按規則應為 ${1}，已沿用舊糧單金額。"),
)


def chinese_note(text):
    """Turn the old English seed notes into Traditional Chinese. Other text is left as it is."""
    raw = "" if text is None else str(text).strip()
    if not raw or raw.lower() == "nan":
        return ""
    parts = []
    for part in re.split(r"\s*[;；]\s*", raw):
        if not part:
            continue
        changed = part
        for pattern, template in _NOTE_PATTERNS:
            match = pattern.fullmatch(part.strip())
            if match:
                changed = template.format(*match.groups())
                break
        parts.append(changed)
    return "；".join(parts)


def heading(table, key):
    return table.get(key, key)


def column_key(heading_text, table):
    text = "" if heading_text is None else str(heading_text).strip()
    if text in OLD_HEADINGS:
        return OLD_HEADINGS[text]
    reverse = {label: key for key, label in table.items()}
    return reverse.get(text, text)


def show(mapping, value):
    text = "" if value is None else str(value).strip()
    return mapping.get(text, text)


def store(mapping, value):
    text = "" if value is None else str(value).strip()
    return mapping.get(text, text)


def day_status(kind, two=False):
    text = STATUS[kind]
    if two:
        return f"{STATUS['two shifts']}；{text}"
    return text


def punch_label(day, part=""):
    if part == "in":
        return f"{day}上班"
    if part == "out":
        return f"{day}下班"
    return day
