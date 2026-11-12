"""PDF support: find signature slots from form fields and text positions, and
stamp drawn signatures or text onto the page as an overlay."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .base import Document, DocumentError, Slot, png_size

SIGN_RE = re.compile(r"\b(sign(ature|ed)?|signatory|sign here)\b", re.I)
UNDERSCORES = re.compile(r"_{5,}")


@dataclass
class Box:
    page: int
    x: float
    y: float          # bottom (baseline) in PDF points
    w: float
    h: float


@dataclass
class _Frag:
    text: str
    x: float
    y: float
    size: float


def _fragments(page) -> list[_Frag]:
    frags: list[_Frag] = []

    def visit(text, cm, tm, font, size):
        if not text or not text.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        scale = (tm[0] * cm[0]) or 1
        frags.append(_Frag(text.strip("\n"), x, y, (size or 10) * abs(scale)))

    page.extract_text(visitor_text=visit)
    return frags


def _lines(frags: list[_Frag]) -> list[list[_Frag]]:
    lines: list[list[_Frag]] = []
    for f in sorted(frags, key=lambda f: (-round(f.y), f.x)):
        if lines and abs(lines[-1][0].y - f.y) < 2:
            lines[-1].append(f)
        else:
            lines.append([f])
    return lines


def _width(f: _Frag) -> float:
    return len(f.text) * f.size * 0.5


class PdfDocument(Document):
    kind = "pdf"

    def __init__(self, path):
        super().__init__(path)
        self.reader = PdfReader(str(self.path))
        self._slots: list[Slot] | None = None
        self._stamps: dict[int, list] = {}     # page -> [(kind, payload, Box)]

    def outline(self) -> list[str]:
        out = []
        for n, page in enumerate(self.reader.pages, 1):
            for line in (page.extract_text() or "").splitlines():
                if line.strip():
                    out.append(f"page {n}: {line.strip()[:300]}")
        return out

    def slots(self) -> list[Slot]:
        if self._slots is None:
            self._slots = self._find_slots()
        return self._slots

    def _find_slots(self) -> list[Slot]:
        found: list[Slot] = []

        # 1. Form fields: signature fields, and text fields whose name suggests a signature/date/name
        for n, page in enumerate(self.reader.pages):
            for annot in page.get("/Annots") or []:
                a = annot.get_object()
                if a.get("/Subtype") != "/Widget":
                    continue
                parent = a.get("/Parent")
                ft = a.get("/FT") or (parent.get_object().get("/FT") if parent else None)
                name = str(a.get("/T") or (parent.get_object().get("/T") if parent else "") or "")
                if ft == "/Sig" or (ft == "/Tx" and re.search(r"sign|date|name|initial", name, re.I)):
                    x0, y0, x1, y1 = (float(v) for v in a["/Rect"])
                    found.append(Slot(
                        id="", kind="field", label=name, page=n + 1,
                        current_text=str(a.get("/V") or ""),
                        notes=("Signature field" if ft == "/Sig" else "Text field")
                        + f" at ({x0:.0f},{y0:.0f}) size {x1 - x0:.0f}x{y1 - y0:.0f}pt.",
                        ref=Box(n, min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))))

        # 2. Text: underscore lines and "Signature" labels
        for n, page in enumerate(self.reader.pages):
            pw = float(page.mediabox.width)
            lines = _lines(_fragments(page))
            for li, line in enumerate(lines):
                text = " ".join(f.text for f in line).strip()
                before = " ".join(f.text for f in lines[li - 1]) if li else ""
                after = " ".join(f.text for f in lines[li + 1]) if li + 1 < len(lines) else ""
                under = next((f for f in line if UNDERSCORES.search(f.text)), None)
                if under:
                    m = UNDERSCORES.search(under.text)
                    cw = under.size * 0.5
                    x = under.x + m.start() * cw
                    found.append(Slot(id="", kind="line", label=text[:160], page=n + 1,
                                      context_before=before[:160], context_after=after[:160],
                                      notes="Underscore line; the signature sits on it.",
                                      ref=Box(n, x, under.y, max((m.end() - m.start()) * cw, 120), 34)))
                elif SIGN_RE.search(text) and len(text) <= 80:
                    end = max(f.x + _width(f) for f in line)
                    right_room = pw - 36 - end
                    if right_room >= 140:
                        box = Box(n, end + 8, line[0].y - 6, min(right_room - 8, 260), 36)
                        where = "to the right of the label"
                    else:
                        box = Box(n, line[0].x, line[0].y - 44, 260, 36)
                        where = "below the label"
                    found.append(Slot(id="", kind="area", label=text, page=n + 1,
                                      context_before=before[:160], context_after=after[:160],
                                      notes=f"Free area {where}, estimated from text positions.",
                                      ref=box))
        for i, s in enumerate(found, 1):
            s.id = f"S{i}"
        return found

    def place_image(self, slot_id, png, height_pt=36):
        slot = self.slot(slot_id)
        box: Box = slot.ref
        w, h = png_size(png)
        hh = min(height_pt, box.h if slot.kind == "field" else height_pt)
        ww = hh * w / h
        if ww > box.w:
            ww, hh = box.w, box.w * h / w
        y = box.y + (box.h - hh) / 2 if slot.kind == "field" else box.y + 1
        self._stamps.setdefault(box.page, []).append(("image", png, Box(box.page, box.x, y, ww, hh)))
        slot.filled_with = "signature image"
        return f"Signature placed in {slot.id} on page {box.page + 1}, {ww:.0f}x{hh:.0f}pt."

    def fill_text(self, slot_id, text):
        slot = self.slot(slot_id)
        box: Box = slot.ref
        y = box.y + 2 if slot.kind != "field" else box.y + (box.h - 10) / 2
        self._stamps.setdefault(box.page, []).append(("text", text, Box(box.page, box.x + 2, y, box.w, 11)))
        slot.filled_with = f"text {text!r}"
        return f"Wrote {text!r} into {slot.id}."

    def clear_slot(self, slot_id):
        slot = self.slot(slot_id)
        page = self._stamps.get(slot.ref.page, [])
        before = len(page)
        page[:] = [s for s in page if not (abs(s[2].x - slot.ref.x) < 3 and abs(s[2].y - slot.ref.y) < 50)]
        if len(page) == before:
            raise DocumentError("Only things SignPad added can be removed from a PDF; existing PDF text cannot be erased.")
        slot.filled_with = ""
        return f"Removed what SignPad had added to {slot.id}."

    def save(self, out):
        out = Path(out)
        writer = PdfWriter(clone_from=self.reader)
        for n, stamps in self._stamps.items():
            page = writer.pages[n]
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(pw, ph))
            for kind, payload, b in stamps:
                if kind == "image":
                    c.drawImage(ImageReader(io.BytesIO(payload)), b.x, b.y, b.w, b.h, mask="auto")
                else:
                    c.setFont("Helvetica", 11)
                    c.drawString(b.x, b.y, payload)
            c.save()
            page.merge_page(PdfReader(buf).pages[0])
        tmp = out.with_name(out.name + ".part")
        with open(tmp, "wb") as fh:
            writer.write(fh)
        tmp.replace(out)
        return out
