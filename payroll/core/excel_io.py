"""Excel reads cached by file time, and writes that replace the real file."""

import os
import shutil
import zipfile
from pathlib import Path

import pandas as pd

_reads = {}


def file_stamp(path):
    stat = Path(path).stat()
    return (stat.st_mtime_ns, stat.st_size)


def copy_file(source, target):
    """Copy the bytes. A Drive mount rejects the extra attributes copy2 tries to read."""
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    try:
        shutil.copymode(source, target)
    except OSError:
        pass
    try:
        stat = source.stat()
        os.utime(target, (stat.st_atime, stat.st_mtime))
    except OSError:
        pass
    return target


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


def read_table(path, **kwargs):
    """A workbook, or None when the file is missing, empty, or not Excel.

    A shared-drive copy can exist before its bytes are a real workbook.
    Callers should build the month again instead of showing a crash.
    """
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size < 128:
            return None
    except OSError:
        return None
    kwargs.setdefault("engine", "openpyxl")
    try:
        return read_excel(path, **kwargs)
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    except Exception as error:
        if error.__class__.__name__ == "InvalidFileException":
            return None
        raise


def clear_reads():
    _reads.clear()


def drop_reads(path):
    """Forget cached reads of one workbook. Other files stay cached."""
    target = str(Path(path).resolve())
    for key in list(_reads):
        if key[0] == target:
            _reads.pop(key, None)


_FORMULA = ("=", "+", "-", "@")


def safe_cell(value):
    """A leading apostrophe keeps '=...' as text instead of an Excel formula."""
    if isinstance(value, str) and value[:1] in _FORMULA:
        return "'" + value
    return value


def _text_column(series):
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        return True
    return False


def safe_frame(frame):
    if frame is None:
        return frame
    out = frame.copy()
    for column in list(out.columns):
        series = out[column]
        if not _text_column(series):
            continue
        out[column] = series.map(lambda value: safe_cell(value) if isinstance(value, str) else value).astype(object)
    return out


def guard_xlsx(path):
    """Force formula-like text cells to stay text, including files not written by pandas."""
    from openpyxl import load_workbook
    book = load_workbook(path)
    changed = False
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value[:1] in _FORMULA:
                    cell.data_type = "s"
                    cell.quotePrefix = True
                    changed = True
    if changed:
        book.save(path)
    return path


def _frames_need_guard(*frames):
    for frame in frames:
        if frame is None or not hasattr(frame, "columns"):
            continue
        for column in frame.columns:
            series = frame[column]
            if not _text_column(series):
                continue
            for value in series:
                if isinstance(value, str) and value[:1] in _FORMULA:
                    return True
    return False


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
    frames = list(sheets.values()) if sheets is not None else [frame]
    if _frames_need_guard(*frames):
        guard_xlsx(path)
    drop_reads(path)
    return path
