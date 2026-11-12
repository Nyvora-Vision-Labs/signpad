"""Word (.docx) support: find signature slots and insert drawn signatures.

Works directly on the OOXML with lxml so that everything Word wrote (text
boxes, ``mc:AlternateContent`` fallbacks, custom XML) survives untouched.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from .base import Document, DocumentError, Slot, png_size

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
}
W = "{%s}" % NS["w"]
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
EMU_PER_PT = 12700

LABEL_RE = re.compile(r"\b(sign(ature|ed)?|signatory|date|name|initials?)\b", re.I)
SIGN_RE = re.compile(r"\b(sign(ature|ed)?|signatory|sign here)\b", re.I)
UNDERSCORES = re.compile(r"_{5,}")


def _inside(el, tags) -> bool:
    return any(anc.tag in tags for anc in el.iterancestors())


_SKIP = {W + "txbxContent", "{%s}Fallback" % NS["mc"]}


def _text(el, skip_nested=True) -> str:
    """Text of a paragraph or cell, ignoring text boxes anchored inside it."""
    out = []
    for t in el.iter(W + "t", W + "tab"):
        if skip_nested and _nested_between(t, el):
            continue
        out.append("\t" if t.tag == W + "tab" else (t.text or ""))
    return "".join(out).strip()


def _nested_between(node, top) -> bool:
    for anc in node.iterancestors():
        if anc is top:
            return False
        if anc.tag in _SKIP:
            return True
    return False


def _has_drawing(el) -> bool:
    return el.find(".//" + W + "drawing") is not None or el.find(".//" + W + "pict") is not None


class DocxDocument(Document):
    kind = "docx"

    def __init__(self, path):
        super().__init__(path)
        with zipfile.ZipFile(self.path) as z:
            self._names = z.namelist()
            self._parts = {n: z.read(n) for n in self._names}
        self.root = etree.fromstring(self._parts["word/document.xml"])
        self.rels = etree.fromstring(self._parts["word/_rels/document.xml.rels"])
        self.types = etree.fromstring(self._parts["[Content_Types].xml"])
        self.body = self.root.find(W + "body")
        self._slots: list[Slot] | None = None
        self._next_media = 1

    # ---------------------------------------------------------------- reading
    def _paragraphs(self):
        """Body paragraphs in reading order, including ones in tables,
        excluding paragraphs that live inside text boxes."""
        return [p for p in self.body.iter(W + "p") if not _inside(p, _SKIP)]

    def outline(self) -> list[str]:
        lines = []
        for i, p in enumerate(self._paragraphs()):
            t = _text(p)
            if t:
                lines.append(f"p{i}: {t[:300]}")
        return lines

    def slots(self) -> list[Slot]:
        if self._slots is None:
            self._slots = self._find_slots()
        return self._slots

    def _find_slots(self) -> list[Slot]:
        paras = self._paragraphs()
        index = {id(p): i for i, p in enumerate(paras)}
        texts = [_text(p) for p in paras]

        def near(i, step):
            j = i + step
            while 0 <= j < len(paras):
                if texts[j]:
                    return f"p{j}: {texts[j][:160]}"
                j += step
            return ""

        found: list[Slot] = []

        # 1. Text boxes (DrawingML shapes, usually wrapped in mc:AlternateContent)
        for txbx in self.body.iter("{%s}txbx" % NS["wps"]):
            if _inside(txbx, {"{%s}Fallback" % NS["mc"]}):
                continue
            anchor = next(txbx.iterancestors("{%s}anchor" % NS["wp"], "{%s}inline" % NS["wp"]), None)
            docpr = anchor.find("wp:docPr", NS) if anchor is not None else None
            name = docpr.get("name") if docpr is not None else "text box"
            p = next((a for a in txbx.iterancestors(W + "p") if id(a) in index), None)
            i = index.get(id(p), 0)
            ext = anchor.find("wp:extent", NS) if anchor is not None else None
            size = ""
            if ext is not None:
                size = f"{int(ext.get('cx')) / EMU_PER_PT:.0f}x{int(ext.get('cy')) / EMU_PER_PT:.0f}pt"
            notes = f"Word shape {name!r}, {size}, anchored at p{i}."
            if anchor is not None and anchor.tag.endswith("anchor"):
                notes += (" Floating boxes are often anchored one paragraph before or after the"
                          " label they sit next to, so read context on both sides.")
            found.append(Slot(
                id="", kind="textbox", label=name,
                current_text=_text(txbx.find(".//" + W + "txbxContent"), skip_nested=False),
                context_before=(f"p{i}: {texts[i][:160]}" if texts[i] else near(i, -1)),
                context_after=near(i, +1), notes=notes,
                ref={"txbx": txbx, "anchor": anchor, "para": p}))

        # 2. Table cells: empty cell to the right of / below a label cell
        for tbl in self.body.iter(W + "tbl"):
            if _inside(tbl, _SKIP):
                continue
            rows = tbl.findall(W + "tr")
            grid = [r.findall(W + "tc") for r in rows]
            for ri, cells in enumerate(grid):
                for ci, tc in enumerate(cells):
                    if _text(tc) or _has_drawing(tc):
                        continue
                    label = ""
                    if ci > 0 and LABEL_RE.search(_text(cells[ci - 1])):
                        label = _text(cells[ci - 1])
                    elif ri > 0 and ci < len(grid[ri - 1]) and LABEL_RE.search(_text(grid[ri - 1][ci])):
                        label = _text(grid[ri - 1][ci])
                    if label:
                        found.append(Slot(id="", kind="cell", label=label[:120],
                                          notes=f"Empty table cell (row {ri + 1}, column {ci + 1}).",
                                          ref={"tc": tc}))

        # 3. Underscore lines and 4. empty space after a signature label
        for i, p in enumerate(paras):
            t = texts[i]
            if UNDERSCORES.search(t) and not _inside(p, {W + "tc"}):
                found.append(Slot(id="", kind="line", label=t[:160],
                                  context_before=near(i, -1), context_after=near(i, +1),
                                  notes=f"Underscore line in p{i}.", ref={"para": p}))
            elif SIGN_RE.search(t) and len(t) <= 80 and not _inside(p, {W + "tc"}):
                nxt = paras[i + 1] if i + 1 < len(paras) else None
                target = nxt if (nxt is not None and not texts[i + 1] and not _has_drawing(nxt)) else p
                found.append(Slot(id="", kind="after_label", label=t,
                                  context_after=near(i, +1),
                                  notes=("Empty paragraph after the label." if target is nxt
                                         else "Goes at the end of the label paragraph."),
                                  ref={"para": target}))

        for n, s in enumerate(found, 1):
            s.id = f"S{n}"
        return found

    # ---------------------------------------------------------------- editing
    def _add_image_part(self, png: bytes) -> str:
        while f"word/media/signpad{self._next_media}.png" in self._parts:
            self._next_media += 1
        name = f"signpad{self._next_media}.png"
        self._parts[f"word/media/{name}"] = png
        ids = {r.get("Id") for r in self.rels}
        n = 1
        while f"rIdSignPad{n}" in ids:
            n += 1
        rid = f"rIdSignPad{n}"
        etree.SubElement(self.rels, "{%s}Relationship" % REL_NS,
                         Id=rid, Type=IMAGE_REL, Target=f"media/{name}")
        if not any(d.get("Extension", "").lower() == "png" for d in self.types):
            etree.SubElement(self.types, "{%s}Default" % CT_NS, Extension="png", ContentType="image/png")
        return rid

    def _next_docpr_id(self) -> int:
        ids = [int(e.get("id")) for e in self.root.iter("{%s}docPr" % NS["wp"]) if e.get("id", "").isdigit()]
        return max(ids, default=0) + 1

    def _picture_run(self, rid: str, cx: int, cy: int):
        pid = self._next_docpr_id()
        xml = (
            f'<w:r xmlns:w="{NS["w"]}" xmlns:wp="{NS["wp"]}" xmlns:a="{NS["a"]}" '
            f'xmlns:pic="{NS["pic"]}" xmlns:r="{NS["r"]}"><w:rPr><w:noProof/></w:rPr><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="Signature {pid}" descr="Handwritten signature"/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="signature.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
        )
        return etree.fromstring(xml)

    @staticmethod
    def _text_run(text: str):
        r = etree.Element(W + "r")
        t = etree.SubElement(r, W + "t")
        t.text = text
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return r

    @staticmethod
    def _clear_runs(p):
        for child in list(p):
            if child.tag != W + "pPr":
                p.remove(child)

    def _textbox_copies(self, slot: Slot):
        """The DrawingML txbxContent plus its VML fallback twin, if any."""
        txbx = slot.ref["txbx"]
        contents = [txbx.find(".//" + W + "txbxContent")]
        alt = next(txbx.iterancestors("{%s}AlternateContent" % NS["mc"]), None)
        if alt is not None:
            fb = alt.find("mc:Fallback", NS)
            if fb is not None:
                contents += fb.findall(".//" + W + "txbxContent")
        return [c for c in contents if c is not None], alt

    def _fill_textbox(self, slot: Slot, make_run, needed_height_emu: int | None):
        contents, alt = self._textbox_copies(slot)
        for c in contents:
            ps = c.findall(W + "p")
            for extra in ps[1:]:
                c.remove(extra)
            self._clear_runs(ps[0])
            ps[0].append(make_run())
        if needed_height_emu:
            self._grow_box(slot, alt, needed_height_emu)

    def _grow_box(self, slot: Slot, alt, needed: int):
        anchor = slot.ref["anchor"]
        pad = 2 * EMU_PER_PT
        txbx = slot.ref["txbx"]
        wsp = txbx.getparent()
        body_pr = wsp.find("wps:bodyPr", NS) if wsp is not None else None
        if body_pr is not None:
            body_pr.set("tIns", str(pad))
            body_pr.set("bIns", str(pad))
        ext = anchor.find("wp:extent", NS) if anchor is not None else None
        if ext is None or int(ext.get("cy")) >= needed + 2 * pad:
            return
        new_cy = needed + 2 * pad
        ext.set("cy", str(new_cy))
        if wsp is not None:
            a_ext = wsp.find("wps:spPr/a:xfrm/a:ext", NS)
            if a_ext is not None:
                a_ext.set("cy", str(new_cy))
        if alt is not None:
            for shape in alt.iter():
                style = shape.get("style")
                if style and "height:" in style:
                    shape.set("style", re.sub(r"height:[\d.]+pt", f"height:{new_cy / EMU_PER_PT:.1f}pt", style))

    def place_image(self, slot_id, png, height_pt=36):
        slot = self.slot(slot_id)
        w, h = png_size(png)
        cy = int(height_pt * EMU_PER_PT)
        cx = int(cy * w / h)
        max_cx = int(4.5 * 72 * EMU_PER_PT)
        if slot.kind == "textbox" and slot.ref["anchor"] is not None:
            ext = slot.ref["anchor"].find("wp:extent", NS)
            if ext is not None:
                max_cx = int(ext.get("cx")) - 2 * 91440
        if cx > max_cx:
            cx, cy = max_cx, int(max_cx * h / w)
        rid = self._add_image_part(png)
        make = lambda: self._picture_run(rid, cx, cy)  # noqa: E731

        if slot.kind == "textbox":
            self._fill_textbox(slot, make, cy)
        elif slot.kind == "cell":
            p = slot.ref["tc"].find(W + "p")
            if p is None:
                p = etree.SubElement(slot.ref["tc"], W + "p")
            p.append(make())
        elif slot.kind == "line":
            self._into_underscores(slot.ref["para"], make())
        elif slot.kind == "after_label":
            p = slot.ref["para"]
            if _text(p):
                p.append(self._text_run(" "))
            p.append(make())
        slot.filled_with = "signature image"
        return f"Signature placed in {slot.id} ({slot.kind} {slot.label!r}), {cx / EMU_PER_PT:.0f}x{cy / EMU_PER_PT:.0f}pt."

    def _into_underscores(self, p, new_run):
        for r in p.findall(W + "r"):
            t = r.find(W + "t")
            if t is not None and t.text and UNDERSCORES.search(t.text):
                before, after = UNDERSCORES.split(t.text, maxsplit=1)
                t.text = before
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                idx = list(p).index(r)
                p.insert(idx + 1, new_run)
                if after:
                    tail = self._text_run(after)
                    p.insert(idx + 2, tail)
                return
        p.append(new_run)

    def fill_text(self, slot_id, text):
        slot = self.slot(slot_id)
        make = lambda: self._text_run(text)  # noqa: E731
        if slot.kind == "textbox":
            self._fill_textbox(slot, make, None)
        elif slot.kind == "cell":
            p = slot.ref["tc"].find(W + "p")
            p.append(make())
        elif slot.kind == "line":
            self._into_underscores(slot.ref["para"], make())
        else:
            p = slot.ref["para"]
            p.append(self._text_run((" " if _text(p) else "") + text))
        slot.filled_with = f"text {text!r}"
        slot.current_text = text
        return f"Wrote {text!r} into {slot.id}."

    def clear_slot(self, slot_id):
        slot = self.slot(slot_id)
        if slot.kind == "textbox":
            contents, _ = self._textbox_copies(slot)
            for c in contents:
                for p in c.findall(W + "p"):
                    self._clear_runs(p)
        elif slot.kind == "cell":
            for p in slot.ref["tc"].findall(W + "p"):
                self._clear_runs(p)
        else:
            raise DocumentError("Only text boxes and table cells can be cleared; use replace_text for other text.")
        slot.current_text = ""
        slot.filled_with = ""
        return f"Cleared {slot.id}."

    def replace_text(self, old, new):
        """Replace text everywhere it appears (body, tables, text boxes and their
        fallbacks). Text split across runs is merged into the first run."""
        if not old:
            raise DocumentError("old text must not be empty")
        count = 0
        for p in self.root.iter(W + "p"):
            runs = [t for t in p.iter(W + "t") if not _nested_between(t, p)]
            joined = "".join(t.text or "" for t in runs)
            if old not in joined:
                continue
            single = [t for t in runs if t.text and old in t.text]
            if single:
                for t in single:
                    count += t.text.count(old)
                    t.text = t.text.replace(old, new)
            else:
                count += joined.count(old)
                runs[0].text = joined.replace(old, new)
                runs[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for t in runs[1:]:
                    t.text = ""
        return count

    def save(self, out):
        out = Path(out)
        self._parts["word/document.xml"] = etree.tostring(self.root, xml_declaration=True,
                                                          encoding="UTF-8", standalone=True)
        self._parts["word/_rels/document.xml.rels"] = etree.tostring(self.rels, xml_declaration=True,
                                                                     encoding="UTF-8", standalone=True)
        self._parts["[Content_Types].xml"] = etree.tostring(self.types, xml_declaration=True,
                                                            encoding="UTF-8", standalone=True)
        names = self._names + [n for n in self._parts if n not in self._names]
        tmp = out.with_name(out.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for n in names:
                z.writestr(n, self._parts[n])
        tmp.replace(out)
        return out
