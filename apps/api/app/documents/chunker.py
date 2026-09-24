"""Normalization + structure-aware chunking (docs/19 §4–§5)."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.ai.tokens import estimate
from app.documents.extract import Segment

TARGET = 512
MAX = 800
OVERLAP = 64
MIN_TAIL = 100
_SENT = re.compile(r"(?<=[.!?।])\s+")


def normalize_text(text: str, code: bool = False) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    text = text.replace(" ", " ").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    if not code:
        text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_repeated_page_lines(segments: list[Segment]) -> list[Segment]:
    """Remove headers/footers that repeat on ≥50% of PDF pages."""
    paged = [s for s in segments if s.page_number is not None and s.kind == "paragraph"]
    if len(paged) < 4:
        return segments
    counts: Counter[str] = Counter()
    for s in paged:
        lines = [ln.strip() for ln in s.text.splitlines() if ln.strip()]
        counts.update(set(lines[:2] + lines[-2:]))
    repeated = {ln for ln, n in counts.items() if n >= len(paged) / 2 and len(ln) < 120}
    if not repeated:
        return segments
    for s in paged:
        s.text = "\n".join(ln for ln in s.text.splitlines() if ln.strip() not in repeated)
    return segments


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int
    page_number: int | None
    sheet_name: str | None
    section_title: str | None
    char_start: int
    char_end: int


def _split(text: str, limit: int) -> list[str]:
    """Split text into pieces ≤ limit tokens, preferring paragraph > line > sentence > word."""
    if estimate(text) <= limit:
        return [text]
    for sep in ("\n\n", "\n", None, " "):
        parts = _SENT.split(text) if sep is None else text.split(sep)
        if len(parts) > 1:
            joiner = " " if sep is None else sep
            out, cur = [], ""
            for p in parts:
                cand = f"{cur}{joiner}{p}" if cur else p
                if estimate(cand) <= limit:
                    cur = cand
                else:
                    if cur:
                        out.append(cur)
                    cur = p
            if cur:
                out.append(cur)
            if all(estimate(o) <= limit for o in out):
                return out
            return [x for o in out for x in _split(o, limit)]
    step = int(limit * 3)
    return [text[i : i + step] for i in range(0, len(text), step)]


def _overlap_tail(text: str) -> str:
    sentences = _SENT.split(text)
    tail = ""
    for s in reversed(sentences):
        cand = f"{s} {tail}".strip()
        if estimate(cand) > OVERLAP:
            break
        tail = cand
    return tail


def chunk(segments: list[Segment], filename: str) -> list[Chunk]:
    segments = strip_repeated_page_lines(segments)
    chunks: list[Chunk] = []
    offset = 0
    groups: list[tuple[tuple[int | None, str | None], list[Segment]]] = []
    for s in segments:
        s.text = normalize_text(s.text, code=s.kind == "code")
        if not s.text:
            continue
        key = (s.page_number, s.sheet_name)
        if groups and groups[-1][0] == key and s.kind != "table":
            groups[-1][1].append(s)
        else:
            groups.append((key, [s]))

    for (page, sheet), segs in groups:
        section = next((s.section_title for s in reversed(segs) if s.section_title), None)
        body = "\n\n".join(s.text for s in segs)
        pieces = _split(body, TARGET) if segs[0].kind != "table" else _split(body, MAX)
        prev_tail = ""
        for piece in pieces:
            if (
                chunks
                and estimate(piece) < MIN_TAIL
                and chunks[-1].page_number == page
                and chunks[-1].sheet_name == sheet
                and chunks[-1].token_count + estimate(piece) < MAX
            ):
                last = chunks[-1]
                last.content += "\n\n" + piece
                last.token_count = estimate(last.content)
                last.char_end += len(piece) + 2
                continue
            header = " · ".join(
                x
                for x in (
                    filename,
                    f"p.{page}" if page else None,
                    f"sheet {sheet}" if sheet else None,
                    section,
                )
                if x
            )
            text = (f"{prev_tail}\n{piece}" if prev_tail else piece).strip()
            content = f"[{header}]\n{text}"
            chunks.append(
                Chunk(
                    len(chunks),
                    content,
                    max(1, estimate(content)),
                    page,
                    sheet,
                    (section or "")[:300] or None,
                    offset,
                    offset + len(piece),
                )
            )
            offset += len(piece) + 2
            prev_tail = _overlap_tail(piece)
    return chunks


def strip_header(content: str) -> str:
    return content.split("\n", 1)[1] if content.startswith("[") and "\n" in content else content
