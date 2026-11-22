"""One person edits a month at a time."""

import os
from datetime import datetime, timedelta


def _path(info):
    return info["system"] / "使用中.txt"


def _user():
    from app.auth import current_user
    return current_user() or os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def read_lock(info):
    path = _path(info)
    if not path.exists():
        return "", None
    lines = path.read_text(encoding="utf-8").splitlines()
    owner = lines[0].strip() if lines else ""
    when = None
    if len(lines) > 1:
        try:
            when = datetime.fromisoformat(lines[1].strip())
        except ValueError:
            when = None
    return owner, when


def claim(info, take_over=False):
    """Return (can_edit, owner). A lock older than two hours can be taken."""
    info["system"].mkdir(parents=True, exist_ok=True)
    owner, when = read_lock(info)
    user = _user()
    fresh = when is not None and datetime.now() - when < timedelta(hours=2)
    if owner and owner != user and fresh and not take_over:
        return False, owner
    _path(info).write_text(f"{user}\n{datetime.now().isoformat(timespec='minutes')}\n", encoding="utf-8")
    return True, user
