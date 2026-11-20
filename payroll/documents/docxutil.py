"""Walk pay-slip tables the same way in the parser and the filler."""

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def iter_unique_cells(table):
    """Cells in reading order, skipping repeats caused by merged cells."""
    for ri, row in enumerate(table.rows):
        seen = set()
        ci = 0
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            yield ri, ci, cell
            ci += 1


def paragraph_at(doc, table_i, row, col, para):
    table = doc.tables[table_i]
    for ri, ci, cell in iter_unique_cells(table):
        if ri == row and ci == col:
            return cell.paragraphs[para]
    raise KeyError(f"missing cell {table_i}:{row},{col}")


def set_paragraph_text(paragraph, text):
    text = "" if text is None else str(text)
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""
