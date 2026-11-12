"""Generate small sample forms (.docx and .pdf) for demos and tests."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{_W}" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'mc:Ignorable="w14"><w:body>'
)


def _p(text: str = "", bold: bool = False) -> str:
    if not text:
        return "<w:p/>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p><w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _textbox(name: str, shape_id: int, text: str) -> str:
    """A floating Word text box with a VML fallback, the way Word writes one."""
    inner = f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' if text else "<w:p/>"
    return (
        '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
        '<wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="1" '
        'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="column"><wp:posOffset>1600000</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        '<wp:extent cx="3600000" cy="350000"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{shape_id}" name="{name}"/><wp:cNvGraphicFramePr/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3600000" cy="350000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="6350"><a:solidFill><a:srgbClr val="000000"/>'
        '</a:solidFill></a:ln></wps:spPr>'
        f'<wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx>'
        '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="ctr"/>'
        '</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
        '<mc:Fallback><w:pict><v:rect style="position:absolute;margin-left:126pt;width:283.5pt;height:27.6pt">'
        f'<v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:rect></w:pict></mc:Fallback>'
        '</mc:AlternateContent></w:r></w:p>'
    )


def build_sample_docx(path: str | Path, signer: str = "Alex Example") -> Path:
    """A one-page agreement with four kinds of signature places."""
    body = "".join([
        _p("Sample Licence Agreement", bold=True),
        _p("The Author grants the Publisher a licence to publish the Work under CC BY 4.0."),
        _p(f"Name of author: {signer}"),
        _p("Date: 1 January 2026"),
        _p(),
        _textbox("Author signature box", 10, signer),
        _p("Signature of Author:"),
        _p(),
        _textbox("Copyright owner box", 11, ""),
        _p("Signature of Copyright Owner (if not the author):"),
        _p(),
        _p("Witness signature: ______________________"),
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/>'
        '<w:gridCol w:w="4000"/></w:tblGrid>'
        '<w:tr><w:tc><w:p><w:r><w:t>Publisher signature</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Date</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>',
        _p(),
        _p("Signed"),
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>',
    ])
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>'),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'),
        "word/document.xml": _HEAD + body + "</w:body></w:document>",
    }
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def build_sample_pdf(path: str | Path, signer: str = "Alex Example") -> Path:
    """A one-page PDF form with a label, an underscore line and a signature form field."""
    path = Path(path)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 780, "Sample Consent Form")
    c.setFont("Helvetica", 11)
    c.drawString(72, 750, "I agree to the terms described in the attached information sheet.")
    c.drawString(72, 720, f"Name: {signer}")
    c.drawString(72, 690, "Signature:")
    c.drawString(72, 620, "Witness: ____________________________")
    c.drawString(72, 560, "Date: ______________")
    c.drawString(72, 500, "Parent or guardian (if under 18):")
    c.acroForm.textfield(name="guardian_signature", x=280, y=490, width=220, height=30, borderWidth=1)
    c.save()
    path.write_bytes(buf.getvalue())
    return path


def build_sample_signature(path: str | Path | None = None) -> bytes:
    """A small transparent PNG with a wavy stroke, standing in for a drawn signature."""
    import math
    import struct
    import zlib

    w, h = 300, 90
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            yy = 45 + 28 * math.sin(x / 22) * math.exp(-x / 400)
            row += bytes([11, 42, 138, 255] if abs(y - yy) < 2.5 else [0, 0, 0, 0])
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    if path:
        Path(path).write_bytes(png)
    return png
