import zipfile

import pytest
from lxml import etree

from signpad.documents import DocumentError, open_document
from signpad.documents.docx import NS


def by_label(doc, kind, text):
    return next(s for s in doc.slots() if s.kind == kind and text in s.label)


def reopen(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_finds_every_kind_of_slot(sample_docx):
    doc = open_document(sample_docx)
    kinds = {s.kind for s in doc.slots()}
    assert {"textbox", "cell", "line", "after_label"} <= kinds
    author = by_label(doc, "textbox", "Author signature box")
    assert author.current_text == "Alex Example"
    assert "Signature of Author" in author.context_after
    assert by_label(doc, "cell", "Publisher signature")
    assert by_label(doc, "line", "Witness signature")


def test_textbox_text_is_not_duplicated_in_outline(sample_docx):
    outline = open_document(sample_docx).outline()
    assert sum("Alex Example" in line for line in outline) == 1  # only "Name of author: ..."


def test_signature_replaces_typed_name_in_textbox_and_fallback(sample_docx, signature_png, tmp_path):
    doc = open_document(sample_docx)
    slot = by_label(doc, "textbox", "Author signature box")
    doc.place_image(slot.id, signature_png)
    out = doc.save(tmp_path / "signed.docx")

    parts = reopen(out)
    xml = etree.fromstring(parts["word/document.xml"])
    for content in xml.iter("{%s}txbxContent" % NS["w"]):
        if content.find(".//{%s}drawing" % NS["w"]) is not None:
            assert "Alex Example" not in "".join(content.itertext())
    assert len(xml.findall(".//pic:pic", NS)) == 2          # DrawingML box + VML fallback copy
    media = [n for n in parts if n.startswith("word/media/")]
    assert media and parts[media[0]] == signature_png
    rels = parts["word/_rels/document.xml.rels"].decode()
    assert "media/signpad1.png" in rels
    assert 'Extension="png"' in parts["[Content_Types].xml"].decode()
    ids = [e.get("id") for e in xml.iter("{%s}docPr" % NS["wp"])]
    assert len(ids) == len(set(ids))


def test_box_grows_to_fit_signature(sample_docx, signature_png, tmp_path):
    doc = open_document(sample_docx)
    slot = by_label(doc, "textbox", "Author signature box")
    doc.place_image(slot.id, signature_png, height_pt=40)
    xml = etree.fromstring(reopen(doc.save(tmp_path / "s.docx"))["word/document.xml"])
    ext = next(xml.iter("{%s}extent" % NS["wp"]))
    assert int(ext.get("cy")) >= 40 * 12700


@pytest.mark.parametrize("kind,label", [("cell", "Publisher signature"), ("line", "Witness signature"),
                                        ("after_label", "Signed")])
def test_place_in_other_slots(sample_docx, signature_png, tmp_path, kind, label):
    doc = open_document(sample_docx)
    slot = by_label(doc, kind, label)
    assert "Signature placed" in doc.place_image(slot.id, signature_png)
    xml = etree.fromstring(reopen(doc.save(tmp_path / "s.docx"))["word/document.xml"])
    assert xml.find(".//pic:pic", NS) is not None
    if kind == "line":
        assert "______" not in "".join(xml.itertext())


def test_fill_text_clear_and_replace(sample_docx, tmp_path):
    doc = open_document(sample_docx)
    date_cell = by_label(doc, "cell", "Date")
    doc.fill_text(date_cell.id, "12 November 2026")
    assert doc.replace_text("1 January 2026", "12 November 2026") == 1
    owner = by_label(doc, "textbox", "Author signature box")
    doc.clear_slot(owner.id)
    text = "".join(etree.fromstring(reopen(doc.save(tmp_path / "s.docx"))["word/document.xml"]).itertext())
    assert text.count("12 November 2026") == 2
    assert "1 January 2026" not in text
    assert text.count("Alex Example") == 1


def test_errors(sample_docx, tmp_path):
    doc = open_document(sample_docx)
    with pytest.raises(DocumentError):
        doc.place_image("S99", b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
    with pytest.raises(DocumentError):
        doc.place_image(doc.slots()[0].id, b"not a png")
    with pytest.raises(DocumentError):
        open_document(tmp_path / "missing.docx")
    (tmp_path / "x.odt").write_text("x")
    with pytest.raises(DocumentError, match="Unsupported"):
        open_document(tmp_path / "x.odt")
