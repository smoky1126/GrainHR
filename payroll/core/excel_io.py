"""Excel reads cached by file time, and writes that replace the real file."""

import os
from pathlib import Path

import pandas as pd

_reads = {}


def file_stamp(path):
    stat = Path(path).stat()
    return (stat.st_mtime_ns, stat.st_size)


def read_excel(path, *args, **kwargs):
    """Read a workbook again only when its size or save time changes."""
    path = Path(path)
    stamp = file_stamp(path)
    key = (
        str(path.resolve()),
        tuple(args),
        tuple(sorted((name, repr(value)) for name, value in kwargs.items())),
    )
    found = _reads.get(key)
    if found and found[0] == stamp:
        copied = found[1].copy()
        copied.attrs = dict(getattr(found[1], "attrs", {}))
        return copied
    frame = pd.read_excel(path, *args, **kwargs)
    _reads[key] = (stamp, frame)
    copied = frame.copy()
    copied.attrs = dict(getattr(frame, "attrs", {}))
    return copied


def clear_reads():
    _reads.clear()


def _file_busy(error):
    if isinstance(error, PermissionError):
        return True
    winerror = getattr(error, "winerror", None)
    if winerror in {32, 33}:
        return True
    return getattr(error, "errno", None) in {13, 16}


def save_excel(path, frame=None, sheets=None):
    """Write a temp workbook, then swap it into place.

    A file left open in Excel becomes a short message instead of a traceback.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        if sheets is not None:
            with pd.ExcelWriter(temp, engine="openpyxl") as writer:
                for name, data in sheets.items():
                    data.to_excel(writer, sheet_name=name, index=False)
        else:
            frame.to_excel(temp, index=False, engine="openpyxl")
        os.replace(temp, path)
    except OSError as error:
        temp.unlink(missing_ok=True)
        if _file_busy(error):
            raise SystemExit(f"請先關閉 {path.name}，然後再試。") from error
        raise
    clear_reads()
    return path
