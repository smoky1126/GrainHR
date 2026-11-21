"""Company names and paths. The real file is company.toml and is not committed."""

import os
import tomllib
from functools import lru_cache
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]


def _candidate():
    forced = os.environ.get("PAYROLL_COMPANY", "").strip()
    if forced:
        return Path(forced)
    local = CODE_ROOT / "company.toml"
    if local.exists():
        return local
    raw = os.environ.get("PAYROLL_HOME", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = (CODE_ROOT / path).resolve()
        found = path / "company.toml"
        if found.exists():
            return found
    return CODE_ROOT / "company.example.toml"


@lru_cache(maxsize=1)
def load():
    path = _candidate()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    raw["_path"] = str(path)
    return raw


def books():
    return dict(load().get("books") or {})


def part_time_books():
    return dict(load().get("part_time") or {})


def match_tokens():
    return [str(token) for token in (load().get("match") or {}).get("second_company") or [] if str(token)]


def allowance_title():
    return str((load().get("documents") or {}).get("allowance_title") or "Allowance Summary")


def groups():
    rows = []
    for row in load().get("groups") or []:
        rows.append((row["key"], row["label"]))
    return tuple(rows)


def prefixes():
    return {row["key"]: row.get("prefix", "") for row in load().get("groups") or []}


def locations():
    rows = []
    for row in load().get("locations") or []:
        rows.append((row["label"], row["code"]))
    return tuple(rows)


def file_places():
    rows = []
    for row in load().get("locations") or []:
        token = row.get("file_token") or ""
        if token:
            rows.append((token, row["label"]))
    return tuple(rows)


def shops():
    rows = []
    for row in load().get("shops") or []:
        rows.append((row["label"], row.get("code", "")))
    return tuple(rows)


def punch_places():
    return dict(load().get("punch_places") or {})


def roster_sources():
    rows = []
    for row in load().get("roster_sources") or []:
        rows.append((row["folder"], row["pattern"], row["code"]))
    rules = load().get("rosters") or {}
    for shop in rules.get("bread") or []:
        rows.append((f"Bread/{shop}", f"{shop}_Bread_roaster_{{year}}_{{mon}}", f"{shop}_Bread"))
    for shop in rules.get("retail") or []:
        rows.append((f"Retail/{shop}", f"{shop}_Retail_roaster_{{year}}_{{mon}}", f"{shop}_Retail"))
    return rows


def issued_through():
    return str((load().get("history") or {}).get("issued_through") or "").strip()


def _on_this_pc(path):
    """Google Drive may use another drive letter on another PC."""
    if path.exists() or not path.drive or path.drive.upper() == CODE_ROOT.drive.upper():
        return path
    moved = Path(CODE_ROOT.drive + str(path)[len(path.drive):])
    return moved if moved.exists() else path


def path_for(name):
    """A path, or a list of paths tried in order. The first one this PC can see wins.

    Shared-drive shortcuts come first so every Google account finds the same folder.
    """
    value = (load().get("paths") or {}).get(name)
    choices = value if isinstance(value, list) else [value]
    paths = [_on_this_pc(Path(str(text).strip())) for text in choices if str(text or "").strip()]
    if not paths:
        return None
    return next((path for path in paths if path.exists()), paths[0])


def daka():
    return dict(load().get("daka") or {})


def varying_pay():
    people = load().get("people") or {}
    return tuple(people.get("varying_pay") or [])


def manual_pay():
    people = load().get("people") or {}
    return dict(people.get("manual_pay") or {})


def users():
    return dict(load().get("users") or {})


def role_for(username):
    row = users().get(username) or {}
    if isinstance(row, dict) and row.get("role"):
        return row["role"]
    return "hr" if load().get("private") else "admin"


def display_name(username):
    row = users().get(username) or {}
    if isinstance(row, dict) and row.get("name"):
        return row["name"]
    return username or "there"


def privacy_words():
    return [str(word) for word in (load().get("privacy") or {}).get("words") or [] if str(word).strip()]


def is_private():
    return bool(load().get("private"))
