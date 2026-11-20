import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payroll.core.holidays import GENERAL, STATUTORY, holiday_count


def main():
    if len(STATUTORY[2025]) != 14 or len(STATUTORY[2026]) != 15 or len(STATUTORY[2027]) != 15:
        raise SystemExit(f"statutory year totals: {[len(STATUTORY[y]) for y in (2025, 2026, 2027)]}")
    if any(len(GENERAL[year]) != 17 for year in (2025, 2026, 2027)):
        raise SystemExit(f"general year totals: {[len(GENERAL[y]) for y in (2025, 2026, 2027)]}")
    checks = [
        (2026, 10, "bg", 2),
        (2026, 10, "md", 2),
        (2026, 10, "admin", 2),
        (2026, 11, "bg", 0),
        (2026, 11, "admin", 0),
        (2026, 2, "bg", 3),
        (2026, 4, "bg", 2),
        (2026, 4, "admin", 4),
        (2026, 9, "bg", 1),
        (2026, 12, "bg", 2),
        (2027, 2, "bg", 3),
        (2027, 2, "admin", 3),
        (2024, 10, "bg", 0),
    ]
    for year, month, book, expected in checks:
        got = holiday_count({"year": year, "month": month}, book)
        if got != expected:
            raise SystemExit(f"{year}-{month:02d} {book}: {got}, expected {expected}")
    print("holidays ok")


if __name__ == "__main__":
    main()
