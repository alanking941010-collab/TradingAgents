"""Minimal DOCX export helpers for options research reports.

The exporter intentionally uses Python stdlib only so report generation does not
require system-level Pandoc or an extra runtime dependency. It converts the
Markdown handoff into a valid WordprocessingML document with headings,
paragraphs, and simple pipe-table support.
"""

from __future__ import annotations

import html
import zipfile
from pathlib import Path


def _xml(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _paragraph(text: str = "", *, style: str | None = None) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{style_xml}<w:r><w:t xml:space=\"preserve\">{_xml(text)}</w:t></w:r></w:p>"


def _cell(text: str) -> str:
    return f"<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>{_paragraph(text.strip())}</w:tc>"


def _table(rows: list[list[str]]) -> str:
    row_xml = []
    for row in rows:
        row_xml.append("<w:tr>" + "".join(_cell(cell) for cell in row) + "</w:tr>")
    return (
        "<w:tbl>"
        "<w:tblPr><w:tblStyle w:val=\"TableGrid\"/><w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>"
        "</w:tblBorders></w:tblPr>"
        + "".join(row_xml)
        + "</w:tbl>"
    )


def _is_separator_row(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _parse_table(lines: list[str], start: int) -> tuple[str, int] | None:
    if start + 1 >= len(lines):
        return None
    if not (lines[start].lstrip().startswith("|") and _is_separator_row(lines[start + 1])):
        return None
    rows: list[list[str]] = []
    idx = start
    while idx < len(lines) and lines[idx].lstrip().startswith("|"):
        if not _is_separator_row(lines[idx]):
            rows.append([cell.strip().strip("`") for cell in lines[idx].strip().strip("|").split("|")])
        idx += 1
    return _table(rows), idx


def markdown_to_docx_xml(markdown: str) -> str:
    """Convert a Markdown handoff into WordprocessingML body content."""
    lines = markdown.splitlines()
    parts: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip()
        parsed_table = _parse_table(lines, idx)
        if parsed_table:
            table_xml, idx = parsed_table
            parts.append(table_xml)
            continue
        if not line:
            parts.append(_paragraph())
        elif line.startswith("# "):
            parts.append(_paragraph(line[2:].strip(), style="Heading1"))
        elif line.startswith("## "):
            parts.append(_paragraph(line[3:].strip(), style="Heading2"))
        elif line.startswith("### "):
            parts.append(_paragraph(line[4:].strip(), style="Heading3"))
        elif line.startswith("- "):
            parts.append(_paragraph("• " + line[2:].strip()))
        elif line == "---":
            parts.append(_paragraph("—" * 24))
        else:
            parts.append(_paragraph(line.strip()))
        idx += 1
    return "".join(parts)


def _document_xml(markdown: str) -> str:
    body = markdown_to_docx_xml(markdown)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>'
        "</w:styles>"
    )


def write_docx_report(markdown: str, path: str | Path) -> Path:
    """Write a valid .docx report converted from Markdown and return its path."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        zf.writestr("word/document.xml", _document_xml(markdown))
        zf.writestr("word/styles.xml", _styles_xml())
    return output
