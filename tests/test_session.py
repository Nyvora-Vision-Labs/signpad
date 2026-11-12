import json

import pytest

from signpad.agent.session import Session
from signpad.documents import DocumentError


def test_full_flow_without_a_model(sample_docx, fake_pad, tmp_path, monkeypatch):
    monkeypatch.setattr("signpad.agent.session.docx_to_pdf", lambda p: None)
    s = Session.open(sample_docx, fake_pad, tmp_path / "out.docx")
    info = json.loads(s.inspect())
    author = next(x for x in info["slots"] if x.get("label") == "Author signature box")

    assert "sig1" in s.request_signature("Alex Example", "Sign the author box")
    assert "Signature placed" in s.place_signature(author["id"], "sig1")
    result = json.loads(s.save_and_review("Signed the author box"))
    assert result["approved_by_user"] is True
    assert (tmp_path / "out.docx").exists()
    assert "pdf_note" in result
    assert fake_pad.reviews[0][1] is None          # no preview without a converter


def test_declined_signature_is_reported(sample_pdf, fake_pad, tmp_path):
    fake_pad.decline = True
    s = Session.open(sample_pdf, fake_pad, tmp_path / "out.pdf")
    assert "declined" in s.request_signature("Alex", "x")
    with pytest.raises(DocumentError):
        s.place_signature("S1", "sig1")


def test_pdf_review_gets_preview(sample_pdf, fake_pad, tmp_path):
    s = Session.open(sample_pdf, fake_pad, tmp_path / "out.pdf")
    s.request_signature("Alex", "x")
    s.place_signature("S1", "sig1")
    json.loads(s.save_and_review("done"))
    assert fake_pad.reviews[0][1].startswith(b"%PDF")


def test_never_overwrites_original(sample_docx, fake_pad):
    with pytest.raises(DocumentError):
        Session.open(sample_docx, fake_pad, sample_docx)


def test_tools_build_and_report_errors(sample_docx, fake_pad, tmp_path):
    from anthropic.lib.tools import ToolError

    from signpad.agent.tools import build_tools

    s = Session.open(sample_docx, fake_pad, tmp_path / "o.docx")
    tools = {t.name: t for t in build_tools(s)}
    assert set(tools) == {"inspect_document", "ask_user", "request_signature", "place_signature",
                          "fill_text", "replace_text", "clear_slot", "save_and_review"}
    schema = tools["place_signature"].to_dict()["input_schema"]
    assert {"slot_id", "signature_id"} <= set(schema["required"])
    with pytest.raises(ToolError):
        tools["place_signature"].call({"slot_id": "S1", "signature_id": "nope"})
