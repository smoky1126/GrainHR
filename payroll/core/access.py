"""Who may see office pay. Admin can. HR staff cannot."""

OFFICE = "admin"
_OFFICE_FILES = ("payslips_admin.xlsx", "pay_table_admin.xlsx", "payroll_draft.xlsx")


def can_see_pay(book_or_group, role):
    """Office pay is the admin staff group and the office payroll book."""
    if str(role or "") == "admin":
        return True
    return str(book_or_group or "").strip() != OFFICE


def visible_books(books, role):
    return {key: label for key, label in books.items() if can_see_pay(key, role)}


def hide_office_file(name, role):
    text = str(name or "")
    if can_see_pay(OFFICE, role):
        return False
    return text in _OFFICE_FILES or "寫字樓" in text


def visible_audit(frame, role, office_ids):
    """Drop office payroll adjustments for anyone who is not an admin."""
    if can_see_pay(OFFICE, role) or frame is None or not len(frame) or "staff_id" not in frame.columns:
        return frame
    blocked = {str(item).strip() for item in office_ids if str(item).strip()}
    if not blocked:
        return frame
    keep = ~frame["staff_id"].map(lambda value: str(value).strip() in blocked)
    return frame.loc[keep].copy()


def scrub_office_row(row, role):
    """Blank office salary fields. Attendance and leave stay."""
    if can_see_pay(row.get("group") or row.get("book"), role):
        return row
    hidden = dict(row)
    for key in ("salary", "net", "mpf_employee", "mpf_employer", "bank_name", "bank_account", "account", "bank"):
        if key in hidden:
            hidden[key] = None
    return hidden
