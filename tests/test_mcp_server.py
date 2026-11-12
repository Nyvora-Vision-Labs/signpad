"""The MCP server Claude Code talks to, driven in-process with the fake pad."""
import json

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from signpad.mcp_server import SigningState, build_server

TOOLS = {"open_document", "inspect_document", "request_signature", "place_signature",
         "fill_text", "replace_text", "clear_slot", "save_and_review"}


@pytest.fixture
def server(fake_pad):
    return build_server(SigningState(lambda: fake_pad))


def call(server, name, **args):
    async def go():
        res = await server.call_tool(name, args)
        return res.content[0].text
    return anyio.run(go)


def test_tool_list_has_no_way_to_supply_a_signature(server):
    tools = anyio.run(server.list_tools)
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert not {"png", "image", "signature_path", "signature_png"} & set(t.input_schema.get("properties", {}))
    place = next(t for t in tools if t.name == "place_signature")
    assert {"slot_id", "signature_id"} <= set(place.input_schema["required"])


def test_full_flow_through_mcp(server, sample_docx, fake_pad, tmp_path, monkeypatch):
    monkeypatch.setattr("signpad.agent.session.docx_to_pdf", lambda p: None)
    out = tmp_path / "out.docx"
    assert str(out) in call(server, "open_document", path=str(sample_docx), output=str(out))
    info = json.loads(call(server, "inspect_document"))
    author = next(x for x in info["slots"] if x.get("label") == "Author signature box")
    assert "sig1" in call(server, "request_signature", signer_name="Alex Example", purpose="Sign")
    assert "Signature placed" in call(server, "place_signature", slot_id=author["id"], signature_id="sig1")
    result = json.loads(call(server, "save_and_review", summary="Signed the author box"))
    assert result["approved_by_user"] is True
    assert out.exists()


def test_errors_come_back_as_tool_errors(server, sample_docx):
    with pytest.raises(ToolError, match="open_document"):
        call(server, "inspect_document")
    with pytest.raises(ToolError, match="never overwrites"):
        call(server, "open_document", path=str(sample_docx), output=str(sample_docx))
    call(server, "open_document", path=str(sample_docx))
    with pytest.raises(ToolError, match="request_signature"):
        call(server, "place_signature", slot_id="S1", signature_id="sig9")
