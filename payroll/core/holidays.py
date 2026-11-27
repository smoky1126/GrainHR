"""Public holiday dates counted for the payroll month.

The dates are not the same every year: lunar festivals and Sunday
substitutes move. These lists were checked on 19 Nov 2026. The payroll
does not fetch them while it runs, so it still works without the internet.

Statutory holidays are used for the shop payrolls. December uses
Christmas Day. Winter Solstice is the other official choice and is also
in December, so the month count is the same.

General holidays are used for the office. Sundays are already the office
weekend, so they are not in this list.
"""
from datetime import date


STATUTORY = {
    2025: (
        date(2025, 1, 1),
        date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31),
        date(2025, 4, 4),
        date(2025, 5, 1), date(2025, 5, 5), date(2025, 5, 31),
        date(2025, 7, 1),
        date(2025, 10, 1), date(2025, 10, 7), date(2025, 10, 29),
        date(2025, 12, 25), date(2025, 12, 26),
    ),
    2026: (
        date(2026, 1, 1),
        date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
        date(2026, 4, 5), date(2026, 4, 6),
        date(2026, 5, 1), date(2026, 5, 24),
        date(2026, 6, 19),
        date(2026, 7, 1),
        date(2026, 9, 26),
        date(2026, 10, 1), date(2026, 10, 18),
        date(2026, 12, 25), date(2026, 12, 26),
    ),
    2027: (
        date(2027, 1, 1),
        date(2027, 2, 6), date(2027, 2, 8), date(2027, 2, 9),
        date(2027, 3, 29),
        date(2027, 4, 5),
        date(2027, 5, 1), date(2027, 5, 13),
        date(2027, 6, 9),
        date(2027, 7, 1),
        date(2027, 9, 16),
        date(2027, 10, 1), date(2027, 10, 8),
        date(2027, 12, 25), date(2027, 12, 27),
    ),
}

GENERAL = {
    2025: (
        date(2025, 1, 1),
        date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31),
        date(2025, 4, 4),
        date(2025, 4, 18), date(2025, 4, 19), date(2025, 4, 21),
        date(2025, 5, 1), date(2025, 5, 5), date(2025, 5, 31),
        date(2025, 7, 1),
        date(2025, 10, 1), date(2025, 10, 7), date(2025, 10, 29),
        date(2025, 12, 25), date(2025, 12, 26),
    ),
    2026: (
        date(2026, 1, 1),
        date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
        date(2026, 4, 3), date(2026, 4, 4), date(2026, 4, 6), date(2026, 4, 7),
        date(2026, 5, 1), date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 1),
        date(2026, 9, 26),
        date(2026, 10, 1), date(2026, 10, 19),
        date(2026, 12, 25), date(2026, 12, 26),
    ),
    2027: (
        date(2027, 1, 1),
        date(2027, 2, 6), date(2027, 2, 8), date(2027, 2, 9),
        date(2027, 3, 26), date(2027, 3, 27), date(2027, 3, 29),
        date(2027, 4, 5),
        date(2027, 5, 1), date(2027, 5, 13),
        date(2027, 6, 9),
        date(2027, 7, 1),
        date(2027, 9, 16),
        date(2027, 10, 1), date(2027, 10, 8),
        date(2027, 12, 25), date(2027, 12, 27),
    ),
}


def holiday_known(year):
    return int(year) in STATUTORY


def _holiday_table(book):
    return GENERAL if book == "admin" else STATUTORY


def holiday_count(info, book):
    """How many holidays fall in this payroll month. 0 if the year is not listed."""
    return len(holiday_days(info["year"], info["month"], book))


def holiday_days(year, month, book):
    """Holiday dates in this payroll month. Shop uses statutory days, office uses general holidays."""
    return [day for day in _holiday_table(book).get(int(year), ()) if day.month == int(month)]


def holiday_dates(year, month, book):
    """Those dates as 25/12、26/12."""
    return "、".join(f"{day.day}/{day.month}" for day in holiday_days(year, month, book))
