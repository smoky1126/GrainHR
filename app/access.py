"""The signed-in role, and whether this person may see office pay."""

from payroll.core.access import can_see_pay, hide_office_file, scrub_office_row, visible_books
from payroll.core.labels import BOOKS
from payroll.core.settings import role_for


def current_role():
    from app.lock import _user
    return role_for(_user())


def see_pay(book_or_group):
    return can_see_pay(book_or_group, current_role())


def books():
    return visible_books(BOOKS, current_role())
