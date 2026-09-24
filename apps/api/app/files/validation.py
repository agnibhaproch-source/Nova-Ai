"""Upload validation: extension/MIME/magic/zip-bomb/image checks (docs/18 §2, §4)."""

from __future__ import annotations

import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import magic

from app.core.errors import AppError, ErrorCode

OOXML = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}


@dataclass(frozen=True)
class TypeRule:
    kind: str
    declared: frozenset[str]
    detected_prefixes: tuple[str, ...]


RULES: dict[str, TypeRule] = {
    "pdf": TypeRule("document", frozenset({"application/pdf"}), ("application/pdf",)),
    "docx": TypeRule(
        "document",
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml", "application/zip"),
    ),
    "xlsx": TypeRule(
        "document",
        frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml", "application/zip"),
    ),
    "pptx": TypeRule(
        "document",
        frozenset({"application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
        ("application/vnd.openxmlformats-officedocument.presentationml", "application/zip"),
    ),
    "txt": TypeRule("document", frozenset({"text/plain"}), ("text/",)),
    "md": TypeRule(
        "document", frozenset({"text/markdown", "text/plain", "text/x-markdown"}), ("text/",)
    ),
    "markdown": TypeRule(
        "document", frozenset({"text/markdown", "text/plain", "text/x-markdown"}), ("text/",)
    ),
    "csv": TypeRule(
        "document",
        frozenset({"text/csv", "application/vnd.ms-excel", "text/plain"}),
        ("text/", "application/csv"),
    ),
    "png": TypeRule("image", frozenset({"image/png"}), ("image/png",)),
    "jpg": TypeRule("image", frozenset({"image/jpeg"}), ("image/jpeg",)),
    "jpeg": TypeRule("image", frozenset({"image/jpeg"}), ("image/jpeg",)),
    "webp": TypeRule("image", frozenset({"image/webp"}), ("image/webp",)),
    "gif": TypeRule("image", frozenset({"image/gif"}), ("image/gif",)),
}


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch not in '<>:"|?*')
    name = name.strip(" .") or "file"
    while len(name.encode()) > 255:
        name = name[:-1]
    return name


def classify(filename: str, declared_mime: str) -> tuple[str, str, TypeRule]:
    """Returns (sanitized name, extension, rule) or raises 415."""
    clean = sanitize_filename(filename)
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    rule = RULES.get(ext)
    if rule is None:
        raise AppError(ErrorCode.UNSUPPORTED_FILE_TYPE)
    if declared_mime.split(";")[0].strip().lower() not in rule.declared:
        raise AppError(ErrorCode.FILE_TYPE_MISMATCH)
    return clean, ext, rule


class FileRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def verify_content(path: Path, ext: str) -> str:
    """Magic-byte and structural checks on the stored bytes (worker side). Returns detected MIME."""
    rule = RULES[ext]
    detected = magic.from_file(str(path), mime=True)
    if not detected.startswith(rule.detected_prefixes):
        raise FileRejected("FILE_TYPE_MISMATCH", "The file's contents don't match its type.")
    if ext in OOXML:
        _check_zip(path, OOXML[ext])
    if rule.kind == "image":
        _check_image(path)
    return detected


def _check_zip(path: Path, required: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
            total = sum(i.file_size for i in infos)
            compressed = max(1, sum(i.compress_size for i in infos))
    except zipfile.BadZipFile as e:
        raise FileRejected("FILE_TYPE_MISMATCH", "The document is damaged.") from e
    if required not in names or "[Content_Types].xml" not in names:
        raise FileRejected("FILE_TYPE_MISMATCH", "The file's contents don't match its type.")
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        raise FileRejected("FILE_TOO_COMPLEX", "The document structure is invalid.")
    if len(infos) > 10_000 or total > 500 * 1024 * 1024 or total > 20 * compressed + 10_000_000:
        raise FileRejected("FILE_TOO_COMPLEX", "The document is too complex to process.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise FileRejected("FILE_TYPE_MISMATCH", "Macro-enabled documents aren't supported.")


def _check_image(path: Path) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception as e:
        raise FileRejected("FILE_TYPE_MISMATCH", "The image is damaged or too large.") from e
