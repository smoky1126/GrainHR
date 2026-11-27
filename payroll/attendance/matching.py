"""Names on the roster or in DAKA that are not linked to a staff record yet."""

from payroll.core.names import chinese
from payroll.core.settings import name_aliases


def unmatched_names(roster_names, daka_names, links, aliases=None):
    """Roster names with no employee, then DAKA names that match no roster name."""
    if aliases is None:
        aliases = name_aliases()
    linked_roster = {
        name for name, link in (links or {}).items() if (link or {}).get("employee_no")
    }
    linked_numbers = {
        (link or {}).get("employee_no")
        for link in (links or {}).values()
        if (link or {}).get("employee_no")
    }
    folded = {chinese(name) for name in linked_roster if chinese(name)}
    roster_left = sorted(
        name for name in roster_names
        if name and name not in linked_roster and name not in aliases
    )
    daka_left = []
    for name in sorted({item for item in daka_names if item}):
        if name in linked_roster or (chinese(name) and chinese(name) in folded):
            continue
        target = aliases.get(name, "")
        if target and (target in linked_roster or target in linked_numbers or name in aliases):
            continue
        daka_left.append(name)
    return roster_left, daka_left
