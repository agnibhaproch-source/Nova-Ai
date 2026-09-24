"""Per-format text extraction into page/sheet/slide-aware segments (docs/19 §2–§3).

Runs in a worker subprocess pool: parser crashes or memory blowups can't take down the worker.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Kind = Literal["paragraph", "heading", "table", "list", "code", "notes"]
MAX_ROWS = 50_000
ROWS_PER_SEGMENT = 25


@dataclass
class Segment:
    text: str
    page_number: int | None = None
    sheet_name: str | None = None
    section_title: str | None = None
    kind: Kind = "paragraph"


@dataclass
class Extraction:
    segments: list[Segment]
    page_count: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def decode_text(raw: bytes) -> str:
    for bom, enc in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        return str(best) if best else raw.decode("latin-1", errors="replace")


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [
        [(c or "").replace("|", "\\|").replace("\n", " ").strip() for c in r]
        + [""] * (width - len(r))
        for r in rows
    ]
    head, body = norm[0], norm[1:]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    return (
        0 < len(s) <= 80
        and not s.endswith((".", ",", ";", ":"))
        and (s.isupper() or s.istitle())
        and len(s.split()) <= 10
    )


def extract_pdf(path: Path, max_pages: int) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ExtractionError("FILE_ENCRYPTED", "This PDF is password-protected.")
    out = Extraction([], page_count=len(reader.pages))
    meta = reader.metadata
    if meta:
        out.metadata = {k: str(v) for k, v in (("title", meta.title), ("author", meta.author)) if v}
    if len(reader.pages) > max_pages:
        out.warnings.append("truncated_pages")
    section: str | None = None
    empty = 0
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text = page.extract_text() or ""
        text = re.sub(r"[ \t]+\n", "\n", text)
        if len(text.strip()) < 50:
            empty += 1
        for line in text.splitlines()[:5]:
            if _looks_like_heading(line):
                section = line.strip()
                break
        if text.strip():
            out.segments.append(Segment(text, page_number=i + 1, section_title=section))
    pages = min(len(reader.pages), max_pages)
    if pages and empty / pages >= 0.8:
        raise ExtractionError(
            "NO_EXTRACTABLE_TEXT", "This PDF appears to be scanned images. OCR isn't supported yet."
        )
    return out


def extract_docx(path: Path) -> Extraction:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    out = Extraction([])
    section: str | None = None
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.startswith("Heading") or style == "Title":
                section = text
                out.segments.append(Segment(text, section_title=section, kind="heading"))
            elif "List" in style:
                out.segments.append(Segment(f"- {text}", section_title=section, kind="list"))
            else:
                out.segments.append(Segment(text, section_title=section))
        elif tag == "tbl":
            t = Table(child, d)
            rows = [[c.text for c in r.cells] for r in t.rows][:200]
            out.segments.append(Segment(_md_table(rows), section_title=section, kind="table"))
    if d.core_properties.title:
        out.metadata["title"] = d.core_properties.title
    return out


def extract_text(path: Path, markdown: bool) -> Extraction:
    text = decode_text(path.read_bytes())
    out = Extraction([])
    if not markdown:
        out.segments = [Segment(p) for p in re.split(r"\n\s*\n", text) if p.strip()]
        return out
    section: str | None = None
    for block in re.split(r"(\n```[^\n]*\n.*?\n```)", "\n" + text, flags=re.S):
        if block.startswith("\n```"):
            out.segments.append(Segment(block.strip(), section_title=section, kind="code"))
            continue
        for para in re.split(r"\n\s*\n", block):
            if not para.strip():
                continue
            m = re.match(r"^(#{1,6})\s+(.*)", para.strip())
            if m:
                section = m.group(2).strip()
                out.segments.append(Segment(para.strip(), section_title=section, kind="heading"))
            else:
                out.segments.append(Segment(para.strip(), section_title=section))
    return out


def _row_groups(name: str, rows: list[list[str]], out: Extraction) -> None:
    if not rows:
        return
    header, body = rows[0], rows[1:]
    cols = []
    for idx, col in enumerate(header):
        samples = [r[idx] for r in body[:3] if idx < len(r) and r[idx]]
        cols.append(f"- {col or f'column {idx + 1}'}: e.g. {', '.join(samples) or '—'}")
    out.segments.append(
        Segment(
            f"Sheet '{name}': {len(body)} rows, {len(header)} columns.\nColumns:\n"
            + "\n".join(cols),
            sheet_name=name,
            kind="table",
        )
    )
    for i in range(0, len(body), ROWS_PER_SEGMENT):
        out.segments.append(
            Segment(
                _md_table([header, *body[i : i + ROWS_PER_SEGMENT]]), sheet_name=name, kind="table"
            )
        )


def extract_csv(path: Path, filename: str) -> Extraction:
    text = decode_text(path.read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))[: MAX_ROWS + 1]
    out = Extraction([])
    if len(rows) > MAX_ROWS:
        out.warnings.append("truncated_rows")
    _row_groups(filename, rows, out)
    return out


def extract_xlsx(path: Path) -> Extraction:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out = Extraction([], page_count=len(wb.sheetnames), metadata={"sheets": wb.sheetnames})
    total = 0
    for ws in wb.worksheets[:100]:
        if ws.sheet_state != "visible":
            out.warnings.append(f"hidden_sheet_skipped:{ws.title}")
            continue
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            if total >= MAX_ROWS:
                out.warnings.append("truncated_rows")
                break
            vals = [
                "" if v is None else (v.isoformat() if hasattr(v, "isoformat") else str(v))
                for v in row
            ]
            if any(vals):
                rows.append(vals)
                total += 1
        _row_groups(ws.title, rows, out)
    wb.close()
    return out


def extract_pptx(path: Path) -> Extraction:
    from pptx import Presentation

    prs = Presentation(str(path))
    out = Extraction([], page_count=len(prs.slides))
    for i, slide in enumerate(prs.slides, start=1):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None else None
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                texts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[c.text for c in r.cells] for r in shape.table.rows]
                texts.append(_md_table(rows))
        if texts:
            out.segments.append(Segment("\n\n".join(texts), page_number=i, section_title=title))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                out.segments.append(
                    Segment(
                        f"Speaker notes: {notes}", page_number=i, section_title=title, kind="notes"
                    )
                )
    return out


def extract(path: Path, ext: str, filename: str, max_pages: int) -> Extraction:
    if ext == "pdf":
        return extract_pdf(path, max_pages)
    if ext == "docx":
        return extract_docx(path)
    if ext in ("md", "markdown"):
        return extract_text(path, markdown=True)
    if ext == "txt":
        return extract_text(path, markdown=False)
    if ext == "csv":
        return extract_csv(path, filename)
    if ext == "xlsx":
        return extract_xlsx(path)
    if ext == "pptx":
        return extract_pptx(path)
    raise ExtractionError("EXTRACTION_FAILED", "This file type can't be read.")
