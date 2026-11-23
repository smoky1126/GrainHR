"""One person edits a month at a time."""

import os
from datetime import datetime, timedelta

IDLE = timedelta(minutes=20)
_REFRESH = timedelta(minutes=10)


def _path(info):
    return info["system"] / "使用中.txt"


def _user():
    from app.auth import current_user
    return current_user() or os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def read_lock(info):
    path = _path(info)
    if not path.exists():
        return "", None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", None
    owner = lines[0].strip() if lines else ""
    when = None
    if len(lines) > 1:
        try:
            when = datetime.fromisoformat(lines[1].strip())
        except ValueError:
            when = None
    return owner, when


def _fresh(when):
    return when is not None and datetime.now() - when < IDLE


def _write(path, user):
    """Create the lock only if it is absent, so two people cannot both take it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"{user}\n{datetime.now().isoformat(timespec='minutes')}\n"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        path.unlink(missing_ok=True)
        return False
    return True


def _replace(path, user):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(".使用中.tmp")
    temp.write_text(
        f"{user}\n{datetime.now().isoformat(timespec='minutes')}\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def claim(info, take_over=False):
    """Return (can_edit, owner). A lock idle for 20 minutes can be taken.

    The same person does not rewrite the lock on every click. A new stamp is
    written when they take over, or when the last stamp is older than 10 minutes.
    """
    info["system"].mkdir(parents=True, exist_ok=True)
    path = _path(info)
    user = _user()
    owner, when = read_lock(info)
    if owner and owner != user and _fresh(when) and not take_over:
        return False, owner
    if take_over and owner and owner != user:
        from app.errors import notify
        notify("月份被接手", f"{user} 接手了 {info.get('key', '')}，原先是 {owner}。")
    recent = owner == user and when is not None and datetime.now() - when < _REFRESH
    if recent and not take_over:
        return True, user
    if owner == user and not take_over:
        _replace(path, user)
        return True, user
    if path.exists():
        try:
            path.unlink()
        except OSError:
            owner, _when = read_lock(info)
            return owner == user, owner or user
    if _write(path, user):
        return True, user
    owner, _when = read_lock(info)
    return owner == user, owner or user


def release(info, user=None):
    path = _path(info)
    if not path.exists():
        return
    owner, _when = read_lock(info)
    if owner == (user or _user()):
        path.unlink(missing_ok=True)


def release_all(user=None):
    """Drop every month lock this person still holds. Used on logout."""
    from payroll.core.config import home
    user = user or _user()
    root = home() / "months"
    if not root.exists():
        return
    for path in root.glob("*/_system/使用中.txt"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if lines and lines[0].strip() == user:
            path.unlink(missing_ok=True)


def ensure_owner(info):
    """Refuse a save when someone else holds a fresh lock."""
    if not isinstance(info, dict) or "system" not in info:
        return
    owner, when = read_lock(info)
    if owner and owner != _user() and _fresh(when):
        raise SystemExit(f"{owner} 已接手，這次沒有儲存。")
