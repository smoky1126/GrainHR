"""Roster and DAKA name aliases saved in company.toml."""

from pathlib import Path

from payroll.core.settings import load, name_aliases


def _quote(text):
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_name_alias(source, target):
    """Remember that this roster or DAKA spelling is one employee."""
    source = str(source).strip()
    target = str(target).strip()
    if not source or not target:
        raise SystemExit("請選擇名字和員工。")
    path = Path(load()["_path"])
    if path.name != "company.toml":
        raise SystemExit("別名只寫入 company.toml。請先建立公司設定。")
    current = name_aliases()
    current[source] = target
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    kept = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped == "[name_aliases]"
            if skipping:
                continue
        if skipping:
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    block = ["[name_aliases]"]
    for key, value in current.items():
        block.append(f"{_quote(key)} = {_quote(value)}")
    kept.extend(["", *block])
    path.write_text(newline.join(kept) + newline, encoding="utf-8")
    load.cache_clear()
    return current
