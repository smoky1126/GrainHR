"""Change Staff_info cells inside the xlsx file and leave every other byte alone.

openpyxl rewrites the workbook and drops the Sheet2 dropdowns. This editor
replaces only the cells HR changed.
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _tag(name):
    return f"{{{_MAIN}}}{name}"


def _column(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _cell(ref, text):
    if text == "":
        return f'<c r="{ref}"/>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_escape(text)}</t></is></c>'


def _sheet_target(files, sheet_name):
    workbook = ET.fromstring(files["xl/workbook.xml"])
    rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {}
    for node in rels:
        targets[node.attrib.get("Id")] = node.attrib.get("Target")
    for sheet in workbook.findall(_tag("sheets"))[0]:
        if sheet.attrib.get("name") != sheet_name:
            continue
        relation = sheet.attrib.get(f"{{{_OFFICE}}}id")
        target = targets[relation].lstrip("/")
        if not target.startswith("xl/"):
            target = posix_join("xl", target)
        return target
    raise SystemExit(f"找不到工作表 {sheet_name}。")


def posix_join(left, right):
    return str(Path(left, right).as_posix())


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _shared_strings(files):
    raw = files.get("xl/sharedStrings.xml")
    if not raw:
        return []
    root = ET.fromstring(raw)
    found = []
    for item in root.findall(_tag("si")):
        texts = [node.text or "" for node in item.iter(_tag("t"))]
        found.append("".join(texts))
    return found


def _text_of(cell, strings):
    kind = cell.attrib.get("t")
    node = cell.find(_tag("is"))
    if kind == "inlineStr" and node is not None:
        parts = [item.text or "" for item in node.iter() if _local(item.tag) == "t"]
        return "".join(parts)
    value = cell.find(_tag("v"))
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return strings[int(value.text)]
        except (ValueError, IndexError):
            return value.text
    return value.text


def _grid(sheet_xml, strings):
    root = ET.fromstring(sheet_xml)
    rows = []
    for row in root.iter(_tag("row")):
        number = int(row.attrib.get("r") or "0")
        cells = {}
        for cell in row.findall(_tag("c")):
            ref = cell.attrib.get("r") or ""
            letters = "".join(ch for ch in ref if ch.isalpha())
            cells[letters] = _text_of(cell, strings)
        rows.append((number, cells))
    return rows


def _header(rows):
    for number, cells in rows[:15]:
        for letters, text in cells.items():
            if str(text).strip().startswith("員工編號"):
                return number, cells
    raise SystemExit("找不到「員工編號」標題。")


def _replace_cell(xml, ref, text):
    pattern = re.compile(
        rf'<c\b[^>]*\br="{re.escape(ref)}"[^>]*/>|<c\b[^>]*\br="{re.escape(ref)}"[^>]*>.*?</c>',
        re.DOTALL,
    )
    replacement = _cell(ref, text)
    updated, count = pattern.subn(replacement, xml, count=1)
    if count:
        return updated
    row_number = "".join(ch for ch in ref if ch.isdigit())
    row_pattern = re.compile(rf'(<row\b[^>]*\br="{row_number}"[^>]*>)(.*?)(</row>)', re.DOTALL)
    match = row_pattern.search(updated)
    if not match:
        raise SystemExit(f"找不到儲存格 {ref}。")
    return updated[:match.start(2)] + match.group(2) + replacement + updated[match.end(2):]


def _person_row(rows, header_row, columns, number, name):
    number_col = columns.get("員工編號")
    name_col = columns.get("中文姓名")
    for row_number, cells in rows:
        if row_number <= header_row:
            continue
        if cells.get(number_col, "").strip() == number and cells.get(name_col, "").strip() == name:
            return row_number
    return 0


def _last_row(rows, header_row, number_col):
    last = header_row
    for row_number, cells in rows:
        if row_number > header_row and cells.get(number_col, "").strip():
            last = row_number
    return last


def _append_row(xml, row_number, values):
    cells = "".join(_cell(f"{letters}{row_number}", text) for letters, text in values)
    row = f'<row r="{row_number}">{cells}</row>'
    return xml.replace("</sheetData>", row + "</sheetData>", 1)


def apply_staff_edit(payload):
    path = Path(payload["path"])
    try:
        with zipfile.ZipFile(path) as book:
            files = {name: book.read(name) for name in book.namelist()}
    except PermissionError as error:
        raise SystemExit(f"請先關閉 {path.name}，然後再試。") from error
    target = _sheet_target(files, payload["sheet"])
    xml = files[target].decode("utf-8")
    rows = _grid(xml, _shared_strings(files))
    header_row, header_cells = _header(rows)
    columns = {}
    for letters, text in header_cells.items():
        name = str(text).strip().rstrip("*")
        if name and name not in columns:
            columns[name] = letters
    fields = payload.get("fields") or {}
    if payload.get("action") == "add":
        row_number = _last_row(rows, header_row, columns["員工編號"]) + 1
        values = [
            (columns[name], "" if value is None else str(value))
            for name, value in fields.items()
            if name in columns
        ]
        xml = _append_row(xml, row_number, values)
    else:
        row_number = _person_row(rows, header_row, columns, str(payload["employee_no"]), str(payload["name_zh"]))
        if not row_number:
            raise SystemExit(f"找不到 {payload['employee_no']} {payload['name_zh']}。")
        for name, value in fields.items():
            letters = columns.get(name)
            if not letters:
                continue
            xml = _replace_cell(xml, f"{letters}{row_number}", "" if value is None else str(value))
    files[target] = xml.encode("utf-8")
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with zipfile.ZipFile(temp, "w") as book:
            for name, data in files.items():
                book.writestr(name, data)
        temp.replace(path)
    except PermissionError as error:
        temp.unlink(missing_ok=True)
        raise SystemExit(f"請先關閉 {path.name}，然後再試。") from error
