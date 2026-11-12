"""Document handlers. ``open_document`` picks one from the file extension."""
from __future__ import annotations

from pathlib import Path

from .base import Document, DocumentError, Slot
from .docx import DocxDocument
from .pdf import PdfDocument

HANDLERS = {".docx": DocxDocument, ".pdf": PdfDocument}
SUPPORTED = tuple(HANDLERS)


def open_document(path: str | Path) -> Document:
    path = Path(path).expanduser()
    if not path.exists():
        raise DocumentError(f"File not found: {path}")
    handler = HANDLERS.get(path.suffix.lower())
    if handler is None:
        raise DocumentError(
            f"Unsupported file type {path.suffix!r}. Supported: {', '.join(SUPPORTED)}. "
            "For .doc, .odt or .pages files, export to .docx or .pdf first."
        )
    return handler(path)


__all__ = ["Document", "DocumentError", "Slot", "DocxDocument", "PdfDocument", "open_document", "SUPPORTED"]
