"""State and actions behind the agent's tools. Kept free of any API code so it
can be tested and reused without a model in the loop."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..convert import ConversionError, docx_to_pdf
from ..documents import Document, DocumentError, open_document


class Pad(Protocol):
    def status(self, message: str) -> None: ...
    def request_signature(self, signer: str, purpose: str) -> bytes | None: ...
    def request_review(self, summary: str, preview_pdf: bytes | None, files: list[str]) -> tuple[bool, str]: ...


def default_output(src: Path) -> Path:
    return src.with_name(f"{src.stem} - signed{src.suffix}")


@dataclass
class Session:
    doc: Document
    pad: Pad
    output: Path
    ask: Callable[[str], str] = input
    signatures: dict[str, bytes] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    saved: list[Path] = field(default_factory=list)
    approved: bool = False

    @classmethod
    def open(cls, path: str | Path, pad: Pad, output: str | Path | None = None, **kw) -> Session:
        doc = open_document(path)
        out = Path(output) if output else default_output(doc.path)
        if out.resolve() == doc.path.resolve():
            raise DocumentError("The output path must differ from the original; SignPad never overwrites it.")
        return cls(doc=doc, pad=pad, output=out, **kw)

    # ------------------------------------------------------------- actions
    def inspect(self) -> str:
        self.pad.status("Reading the document and looking for signature places.")
        return json.dumps({
            "file": self.doc.path.name,
            "type": self.doc.kind,
            "text": self.doc.outline(),
            "slots": [s.describe() for s in self.doc.slots()],
            "signatures_captured": list(self.signatures),
        }, ensure_ascii=False, indent=1)

    def ask_user(self, question: str) -> str:
        self.pad.status("The agent has a question for you in the terminal.")
        answer = self.ask(f"\n[SignPad] {question}\n> ").strip()
        self.log.append(f"Asked: {question} / Answer: {answer}")
        return answer or "(no answer)"

    def request_signature(self, signer_name: str, purpose: str) -> str:
        png = self.pad.request_signature(signer_name, purpose)
        if png is None:
            self.log.append("The user declined to sign.")
            return "The user declined to draw a signature. Do not sign; ask what they want instead."
        sid = f"sig{len(self.signatures) + 1}"
        self.signatures[sid] = png
        self.log.append(f"Captured signature {sid} from {signer_name}.")
        return f"Captured signature {sid}, drawn by the user. Use place_signature to put it in a slot."

    def place_signature(self, slot_id: str, signature_id: str, height_pt: float = 36) -> str:
        if signature_id not in self.signatures:
            raise DocumentError(f"Unknown signature {signature_id!r}. Call request_signature first.")
        msg = self.doc.place_image(slot_id, self.signatures[signature_id], height_pt)
        self.log.append(msg)
        return msg

    def fill_text(self, slot_id: str, text: str) -> str:
        msg = self.doc.fill_text(slot_id, text)
        self.log.append(msg)
        return msg

    def replace_text(self, old: str, new: str) -> str:
        n = self.doc.replace_text(old, new)
        if not n:
            return f"{old!r} was not found. Check the exact text with inspect_document."
        self.log.append(f"Replaced {old!r} with {new!r} ({n}x).")
        return f"Replaced {n} occurrence(s)."

    def clear_slot(self, slot_id: str) -> str:
        msg = self.doc.clear_slot(slot_id)
        self.log.append(msg)
        return msg

    def save_and_review(self, summary: str) -> str:
        out = self.doc.save(self.output)
        files = [str(out)]
        preview: bytes | None = None
        note = ""
        if self.doc.kind == "pdf":
            preview = out.read_bytes()
        else:
            self.pad.status("Saving and making a PDF copy for you to check.")
            try:
                pdf = docx_to_pdf(out)
            except ConversionError as e:
                pdf, note = None, str(e)
            if pdf:
                files.append(str(pdf))
                preview = pdf.read_bytes()
            elif not note:
                note = "No .docx to .pdf converter found (install LibreOffice, or Microsoft Word on macOS)."
        self.saved = [Path(f) for f in files]
        approved, comment = self.pad.request_review(summary, preview, files)
        self.approved = approved
        result = {"saved": files, "approved_by_user": approved, "user_comment": comment}
        if note:
            result["pdf_note"] = note
        return json.dumps(result)
