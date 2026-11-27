"""Company names and paths. The real file is company.toml and is not committed."""

import os
import time
import tomllib
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


_loaded = {"path": None, "stamp": None, "data": None}


def load():
    """Company settings. A saved company.toml is picked up without restarting."""
    path = _candidate()
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if _loaded["data"] is not None and _loaded["path"] == str(path) and _loaded["stamp"] == stamp:
        return _loaded["data"]
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    raw["_path"] = str(path)
    _loaded["path"] = str(path)
    _loaded["stamp"] = stamp
    _loaded["data"] = raw
    return raw


_derived = {"token": None, "at": 0.0, "keywords": None, "codes": None}


def _cached_rules(kind):
    """Reuse shop rules for a moment. A changed company file is read on the next check."""
    now = time.monotonic()
    if _derived[kind] is not None and now - _derived["at"] < 2.0:
        return _derived[kind]
    load()
    token = (_loaded["path"], _loaded["stamp"])
    if _derived["token"] != token:
        _derived["keywords"] = None
        _derived["codes"] = None
        _derived["token"] = token
    _derived["at"] = now
    return _derived[kind]


def _clear_loaded():
    _loaded["path"] = None
    _loaded["stamp"] = None
    _loaded["data"] = None
    _derived["token"] = None
    _derived["at"] = 0.0
    _derived["keywords"] = None
    _derived["codes"] = None


load.cache_clear = _clear_loaded


def books():
    return dict(load().get("books") or {})


def part_time_books():
    return dict(load().get("part_time") or {})


def match_tokens():
    return [str(token) for token in (load().get("match") or {}).get("second_company") or [] if str(token)]


def second_shop():
    return str((load().get("match") or {}).get("second_shop") or "")


def second_folder():
    return str((load().get("match") or {}).get("second_folder") or "")


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


def shop_keywords():
    """Longest place word first, and the shop code it means."""
    cached = _cached_rules("keywords")
    if cached is not None:
        return cached
    data = _loaded["data"] or {}
    rows = []
    for row in data.get("shops") or []:
        label, code = row.get("label", ""), row.get("code", "")
        if str(label or "").strip() and str(code or "").strip():
            rows.append((str(label).strip(), str(code).strip()))
    extra = data.get("punch_words") or {}
    if isinstance(extra, dict):
        for word, code in extra.items():
            if str(word).strip() and str(code).strip():
                rows.append((str(word).strip(), str(code).strip()))
    rows.sort(key=lambda item: len(item[0]), reverse=True)
    _derived["keywords"] = tuple(rows)
    return _derived["keywords"]


def code_for_shop(text):
    """Punch code for a roster shop. The longest configured key wins."""
    raw = str(text or "").strip()
    if not raw or raw.lower() == "nan":
        return ""
    rules = _code_rules()
    for key, code in rules:
        if key in raw:
            return code
    return raw.split("_")[0]


def _code_rules():
    cached = _cached_rules("codes")
    if cached is not None:
        return cached
    data = _loaded["data"] or {}
    rules = []
    mapping = data.get("shop_codes") or {}
    if isinstance(mapping, dict):
        for key, code in mapping.items():
            if isinstance(code, str) and str(key).strip() and code.strip():
                rules.append((str(key).strip(), code.strip()))
    rules.sort(key=lambda item: len(item[0]), reverse=True)
    _derived["codes"] = tuple(rules)
    return _derived["codes"]


def shares_site(left, right):
    """True when two punch codes are the same building in company.toml."""
    if not left or not right:
        return False
    if left == right:
        return True
    for group in (load().get("places") or {}).get("same_site") or []:
        members = {str(item) for item in group}
        if str(left) in members and str(right) in members:
            return True
    return False


def shop_groups():
    rows = []
    for row in load().get("shop_groups") or []:
        if not isinstance(row, dict):
            continue
        group = str(row.get("group") or "")
        tokens = tuple(str(token) for token in row.get("tokens") or [] if str(token))
        if group and tokens:
            rows.append((group, tokens))
    return tuple(rows)


def timezone_name():
    name = str((load().get("locale") or {}).get("timezone") or "").strip()
    return name or "UTC"


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


def server_settings():
    return dict(load().get("server") or {})


def _path_text(text):
    return str(text or "").strip().replace("/", "\\").rstrip("\\")


def translate_root(text, windows_root, linux_root):
    """Swap a Windows shared-drive prefix for the Linux mount. The boundary is a folder."""
    path = _path_text(text)
    root = _path_text(windows_root)
    mount = str(linux_root or "").strip().rstrip("/\\")
    if not path or not root or not mount:
        return str(text or "").strip()
    if path.lower() == root.lower():
        return mount
    prefix = root.lower() + "\\"
    if not path.lower().startswith(prefix):
        return str(text or "").strip()
    rest = path[len(root):].lstrip("\\").replace("\\", "/")
    from pathlib import PurePosixPath
    return str(PurePosixPath(mount) / rest) if rest else mount


def _stored_path(text):
    """On Linux, company.toml still holds the Windows path. Map it onto the server mount."""
    raw = str(text or "").strip()
    if os.name == "nt" or not raw:
        return raw
    server = server_settings()
    return translate_root(raw, server.get("windows_root"), server.get("linux_root"))


def _on_this_pc(path):
    """Google Drive may use another drive letter on another PC."""
    if os.name != "nt":
        return path
    if path.exists() or not path.drive or path.drive.upper() == CODE_ROOT.drive.upper():
        return path
    moved = Path(CODE_ROOT.drive + str(path)[len(path.drive):])
    return moved if moved.exists() else path


def map_server_path(text, windows_root, linux_root):
    win = str(windows_root or "").strip().rstrip("\\/")
    linux = str(linux_root or "").strip().rstrip("/")
    raw = str(text or "").strip()
    if not win or not linux or not raw:
        return raw
    normalized = raw.replace("/", "\\")
    prefix = win.replace("/", "\\")
    if not normalized.lower().startswith(prefix.lower()):
        return raw
    rest = normalized[len(prefix):]
    if rest and rest[0] not in "\\/":
        return raw
    rest = rest.lstrip("\\/").replace("\\", "/")
    return f"{linux}/{rest}" if rest else linux


def path_for(name):
    if name == "roster_sheets" and os.name != "nt":
        return None
    value = (load().get("paths") or {}).get(name)
    choices = value if isinstance(value, list) else [value]
    server = load().get("server") or {}
    windows_root = str(server.get("windows_root") or "")
    linux_root = str(server.get("linux_root") or "")
    paths = []
    for item in choices:
        raw = str(item or "").strip()
        if not raw:
            continue
        if os.name != "nt":
            raw = map_server_path(raw, windows_root, linux_root)
        paths.append(_on_this_pc(Path(raw)))
    if not paths:
        return None
    return next((found for found in paths if found.exists()), paths[0])


def daka():
    return dict(load().get("daka") or {})


def varying_pay():
    people = load().get("people") or {}
    return tuple(people.get("varying_pay") or [])


def manual_pay():
    people = load().get("people") or {}
    return dict(people.get("manual_pay") or {})


def no_monthly_pay():
    """Employee numbers who stay on the staff list and are not paid each month."""
    people = load().get("people") or {}
    return {str(item).strip() for item in (people.get("no_monthly_pay") or []) if str(item).strip()}


def users():
    return dict(load().get("users") or {})


def _user_row(username):
    table = users()
    key = str(username or "")
    row = table.get(key)
    if isinstance(row, dict):
        return row
    lowered = key.lower()
    for name, found in table.items():
        if str(name).lower() == lowered and isinstance(found, dict):
            return found
    return {}


def role_for(username):
    row = _user_row(username)
    if row.get("role"):
        role = str(row["role"])
        return "hr" if role == "viewer" else role
    if os.environ.get("GRAINHR_SERVER") == "1" and not row:
        return "none"
    return "hr" if load().get("private") else "admin"


def actor():
    """The website email, otherwise the Windows user name."""
    try:
        from app.auth import current_user
        who = current_user()
        if who:
            return who
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def display_name(username):
    row = _user_row(username)
    if row.get("name"):
        return row["name"]
    return username or "there"


def app_version():
    path = CODE_ROOT / "VERSION"
    if not path.exists():
        return "1.0.0"
    text = path.read_text(encoding="utf-8-sig").strip()
    return text or "1.0.0"


def group_label(key):
    return dict(groups()).get(str(key), str(key or ""))


def shop_label(code):
    """Chinese shop name from company.toml. Unknown codes stay as they are."""
    text = str(code or "").strip()
    if not text or text.lower() == "nan":
        return ""
    for label, coded in locations():
        if coded and coded == text:
            return label
    return text


def name_aliases():
    raw = load().get("name_aliases") or {}
    if not isinstance(raw, dict):
        return {}
    found = {}
    for key, value in raw.items():
        source = str(key).strip()
        target = str(value).strip()
        if source and target:
            found[source] = target
    return found


def privacy_words():
    return [str(word) for word in (load().get("privacy") or {}).get("words") or [] if str(word).strip()]


def is_private():
    return bool(load().get("private"))
