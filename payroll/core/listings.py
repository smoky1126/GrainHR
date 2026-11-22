"""Short-lived memory for folder listings. A changed folder is read again immediately."""

import time
from pathlib import Path

_CACHE = {}


def remember(key, folder, build, seconds=300):
    """Return the last listing while the folder is unchanged and still fresh."""
    path = Path(folder) if folder is not None else None
    try:
        stamp = path.stat().st_mtime_ns if path is not None and path.exists() else 0
    except OSError:
        stamp = 0
    now = time.monotonic()
    found = _CACHE.get(key)
    if found and found[0] == stamp and now - found[1] < seconds:
        return found[2]
    value = build()
    _CACHE[key] = (stamp, now, value)
    return value


def clear_listings():
    _CACHE.clear()
