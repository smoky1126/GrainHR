"""Edit Staff_info cells without resaving the workbook.

openpyxl drops the Sheet2 dropdowns when it saves. This changes only the
named cells inside the worksheet XML and copies every other zip entry as it was.
"""

import re
import zipfile
from pathlib import Path

from openpyxl import load_workbook


def _column_letter(number):
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _column_number(letters):
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - 64
    return number


def _cell_xml(ref, value):
    if value is None or str(value) == "":
        return f'<c r="{ref}"/>'
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _set_cell(inner, ref, value):
    pattern = re.compile(rf'<c r="{re.escape(ref)}"(?:\s[^>]*?)?(?:/>|>.*?</c>)', re.S)
    cell = _cell_xml(ref, value)
    if pattern.search(inner):
        return pattern.sub(cell, inner, count=1)
    return inner + cell


def _row_number(row):
    """The row index. A read-only sheet uses EmptyCell for a blank column A."""
    for cell in row:
        number = getattr(cell, "row", None)
        if number:
            return number
    return None


def _sheet_map(path, sheet_name):
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = book[sheet_name]
        header_row = None
        columns = {}
        people = []
        last = 1
        for row in sheet.iter_rows():
            row_number = _row_number(row)
            if not row_number:
                continue
            last = row_number
            if header_row is None:
                names = {}
                for cell in row:
                    column = getattr(cell, "column", None)
                    label = str(cell.value or "").strip().rstrip("*")
                    if column and label:
                        names[label] = column
                if any(name.startswith("員工編號") for name in names):
                    header_row = row_number
                    columns = names
                continue
            number = name = ""
            number_col = columns.get("員工編號")
            name_col = columns.get("中文姓名")
            for cell in row:
                column = getattr(cell, "column", None)
                if column == number_col:
                    number = str(cell.value or "").strip()
                if column == name_col:
                    name = str(cell.value or "").strip()
            if number:
                people.append((row_number, number, name))
        return header_row, columns, people, last
    finally:
        book.close()


def _sheet_part(archive, sheet_name):
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    escaped = sheet_name.replace("&", "&amp;").replace('"', "&quot;")
    found = re.search(rf'<sheet[^>]*name="{re.escape(escaped)}"[^>]*r:id="([^"]+)"', workbook)
    if not found:
        found = re.search(rf'<sheet[^>]*r:id="([^"]+)"[^>]*name="{re.escape(escaped)}"', workbook)
    if not found:
        raise SystemExit(f"找不到工作表 {sheet_name}。")
    relation = found.group(1)
    target = re.search(rf'Id="{relation}"[^>]*Target="([^"]+)"', rels)
    if not target:
        target = re.search(rf'Target="([^"]+)"[^>]*Id="{relation}"', rels)
    name = target.group(1).lstrip("/")
    if not name.startswith("xl/"):
        name = "xl/" + name
    return name


def _apply_fields(xml, row_number, columns, fields):
    pattern = re.compile(rf'(<row\b[^>]*\sr="{row_number}"[^>]*>)(.*?)(</row>)', re.S)
    match = pattern.search(xml)
    inner = match.group(2) if match else ""
    for name, value in fields.items():
        column = columns.get(name)
        if not column:
            continue
        inner = _set_cell(inner, f"{_column_letter(column)}{row_number}", value)
    if match:
        return xml[:match.start()] + match.group(1) + inner + match.group(3) + xml[match.end():]
    row = f'<row r="{row_number}">{inner}</row>'
    return xml.replace("</sheetData>", row + "</sheetData>", 1)


def _highest_column(columns, xml):
    """The last used column. A new header goes in the next one, past any note."""
    highest = max(columns.values(), default=0)
    for letters in re.findall(r'\br="([A-Z]+)\d+"', xml):
        highest = max(highest, _column_number(letters))
    dimension = re.search(r'<dimension\b[^>]*\bref="[A-Z]+\d+:([A-Z]+)\d+"', xml)
    if dimension:
        highest = max(highest, _column_number(dimension.group(1)))
    return highest


def _widen_dimension(xml, column):
    pattern = re.compile(r'(<dimension\b[^>]*\bref="[A-Z]+\d+:)([A-Z]+)(\d+")')
    match = pattern.search(xml)
    if not match or _column_number(match.group(2)) >= column:
        return xml
    letter = _column_letter(column)
    return pattern.sub(lambda found: found.group(1) + letter + found.group(3), xml, count=1)


def _ensure_column(xml, header_row, columns, name):
    """Add a header when the sheet has no column of that name."""
    if name in columns or not header_row:
        return xml, columns
    column = _highest_column(columns, xml) + 1
    columns = dict(columns)
    columns[name] = column
    xml = _apply_fields(xml, header_row, columns, {name: name})
    return _widen_dimension(xml, column), columns


def edit_staff_sheet(path, sheet_name, employee_no, name_zh, fields, action):
    """Change one person's cells. Dropdowns and the other cells stay in the file."""
    path = Path(path)
    header_row, columns, people, last = _sheet_map(path, sheet_name)
    if header_row is None:
        raise SystemExit("找不到「員工編號」標題。")
    number = str(employee_no).strip()
    person = str(name_zh).strip()
    row_number = next((row for row, found_no, found_name in people if found_no == number and found_name == person), None)
    if action == "add":
        if row_number is not None:
            raise SystemExit(f"{number} 已有在職紀錄。")
        row_number = last + 1
    elif row_number is None:
        raise SystemExit(f"找不到 {number} {person}。")
    with zipfile.ZipFile(path, "r") as archive:
        part = _sheet_part(archive, sheet_name)
        xml = archive.read(part).decode("utf-8")
        names = [item.filename for item in archive.infolist()]
        payload = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    if "離職日期" in fields:
        xml, columns = _ensure_column(xml, header_row, columns, "離職日期")
    updated = _apply_fields(xml, row_number, columns, fields)
    payload[part] = updated.encode("utf-8")
    temp = path.with_name(f".{path.name}.editing")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, payload[name])
    temp.replace(path)
    return path
