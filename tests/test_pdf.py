from pypdf import PdfReader

from signpad.documents import open_document


def test_finds_label_line_and_field_slots(sample_pdf):
    doc = open_document(sample_pdf)
    slots = doc.slots()
    kinds = {s.kind for s in slots}
    assert {"area", "line", "field"} <= kinds
    sig = next(s for s in slots if s.kind == "area" and s.label.startswith("Signature"))
    assert sig.page == 1
    assert sig.ref.x > 120          # to the right of the "Signature:" label
    field = next(s for s in slots if s.kind == "field")
    assert field.label == "guardian_signature"


def test_outline_has_page_text(sample_pdf):
    outline = open_document(sample_pdf).outline()
    assert any("Sample Consent Form" in line for line in outline)


def test_stamps_signature_and_text(sample_pdf, signature_png, tmp_path):
    doc = open_document(sample_pdf)
    sig = next(s for s in doc.slots() if s.kind == "area" and s.label.startswith("Signature"))
    date = next(s for s in doc.slots() if s.kind == "line" and "Date" in s.label)
    doc.place_image(sig.id, signature_png)
    doc.fill_text(date.id, "12 November 2026")
    out = doc.save(tmp_path / "signed.pdf")

    page = PdfReader(out).pages[0]
    assert "12 November 2026" in page.extract_text()
    xobjects = page["/Resources"]["/XObject"]
    def has_image(xo):
        for v in xo.values():
            o = v.get_object()
            if o.get("/Subtype") == "/Image":
                return True
            if o.get("/Subtype") == "/Form" and "/XObject" in o.get("/Resources", {}):
                if has_image(o["/Resources"]["/XObject"]):
                    return True
        return False
    assert has_image(xobjects)


def test_clear_removes_only_added_stamps(sample_pdf, signature_png):
    doc = open_document(sample_pdf)
    sig = next(s for s in doc.slots() if s.kind == "area")
    doc.place_image(sig.id, signature_png)
    assert "Removed" in doc.clear_slot(sig.id)
