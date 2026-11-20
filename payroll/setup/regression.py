"""Compare a generated October run with the saved check sheet and #243."""

from openpyxl import load_workbook

from payroll.core.config import REFERENCE_CHECK, REFERENCE_SLIPS
from payroll.documents.parse_slips import parse_slips


def _norm(value):
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def attendance_differences(generated, reference=REFERENCE_CHECK, limit=21):
    left = load_workbook(reference, data_only=True)
    right = None
    try:
        right = load_workbook(generated, data_only=True)
        differences = []
        if left.sheetnames != right.sheetnames:
            differences.append(f"sheets {left.sheetnames} vs {right.sheetnames}")
        for name in left.sheetnames:
            if name not in right.sheetnames:
                continue
            a, b = left[name], right[name]
            for row in range(1, max(a.max_row, b.max_row) + 1):
                for col in range(1, max(a.max_column, b.max_column) + 1):
                    if _norm(a.cell(row, col).value) != _norm(b.cell(row, col).value):
                        differences.append(f"{name} {row},{col}")
                        if len(differences) >= limit:
                            return differences
        return differences
    finally:
        left.close()
        if right is not None:
            right.close()


def pay_differences(draft, slips=None):
    if slips is None:
        slips = parse_slips(REFERENCE_SLIPS)
    problems = []
    for slip in slips:
        rows = draft[draft["staff_id"].astype(str) == slip["staff_id"]]
        if rows.empty:
            problems.append(f"{slip['staff_id']} missing from draft")
            continue
        row = rows.iloc[0]
        checks = [
            ("net", row.net, slip["net"]),
            ("basic", row.basic_salary, slip["basic_salary"]),
            ("mpf", row.mpf_employee, slip["mpf_employee"]),
            ("rent", row.rent, slip["rent"]),
            ("water", row.water, slip["water"]),
        ]
        if slip["bonus"] is not None:
            checks.append(("bonus", row.bonus, slip["bonus"]))
        for label, got, expected in checks:
            if abs(float(got or 0) - float(expected or 0)) > 0.02:
                problems.append(
                    f"{slip['staff_id']} {slip['slip_name']} {label}: draft {got} slip {expected}"
                )
    return problems
