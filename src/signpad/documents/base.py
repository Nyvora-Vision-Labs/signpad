"""Common types for documents that SignPad can sign."""
from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class DocumentError(Exception):
    """Raised when an operation cannot be applied to a document."""


@dataclass
class Slot:
    """A place in a document where a signature or short text can go.

    ``kind`` is one of:
      textbox      a drawn box (Word text box), often holding a typed name
      cell         an empty table cell next to or under a label
      line         a run of underscores, e.g. "Signature: ________"
      after_label  the space right after a label paragraph such as "Signature:"
      field        a PDF form field (signature or text)
      area         a PDF region next to or under a label, found from text positions
    """

    id: str
    kind: str
    label: str = ""
    current_text: str = ""
    context_before: str = ""
    context_after: str = ""
    page: int | None = None
    notes: str = ""
    filled_with: str = ""
    ref: Any = field(default=None, repr=False, compare=False)

    def describe(self) -> dict:
        d = asdict(self)
        d.pop("ref", None)
        return {k: v for k, v in d.items() if v not in ("", None)}


class Document(ABC):
    """A signable document loaded in memory. Edits apply in memory until ``save``."""

    kind: str = ""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @abstractmethod
    def outline(self) -> list[str]:
        """Readable text of the document, one entry per paragraph or line."""

    @abstractmethod
    def slots(self) -> list[Slot]:
        """Candidate places for a signature or short text."""

    @abstractmethod
    def place_image(self, slot_id: str, png: bytes, height_pt: float = 36) -> str:
        """Put a PNG (a drawn signature) into a slot. Returns a short description."""

    @abstractmethod
    def fill_text(self, slot_id: str, text: str) -> str:
        """Put short text (a name, a date) into a slot."""

    def clear_slot(self, slot_id: str) -> str:
        raise DocumentError(f"Clearing slots is not supported for {self.kind} files.")

    def replace_text(self, old: str, new: str) -> int:
        raise DocumentError(f"Replacing existing text is not supported for {self.kind} files.")

    @abstractmethod
    def save(self, out: str | Path) -> Path:
        """Write the edited document to ``out`` and return the path."""

    def slot(self, slot_id: str) -> Slot:
        for s in self.slots():
            if s.id == slot_id:
                return s
        raise DocumentError(f"No slot with id {slot_id!r}. Call inspect again to list slots.")


def png_size(png: bytes) -> tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise DocumentError("Signature image must be a PNG.")
    return struct.unpack(">II", png[16:24])
