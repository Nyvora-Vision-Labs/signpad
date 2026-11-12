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


def test_waiting_tools_send_heartbeats(sample_pdf, fake_pad, tmp_path, monkeypatch):
    """A person may take a while in the pad; the client must keep hearing from the tool."""
    import time

    from mcp import Client

    import signpad.mcp_server as ms

    monkeypatch.setattr(ms, "HEARTBEAT_SECONDS", 0.05)
    slow = fake_pad.request_signature
    fake_pad.request_signature = lambda signer, purpose: (time.sleep(0.4), slow(signer, purpose))[1]
    server = build_server(SigningState(lambda: fake_pad))
    beats = []

    async def on_progress(progress, total, message):
        beats.append((progress, message))

    async def go():
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert "ctx" not in tools["request_signature"].input_schema.get("properties", {})
            await client.call_tool("open_document", {"path": str(sample_pdf), "output": str(tmp_path / "o.pdf")})
            res = await client.call_tool("request_signature", {"signer_name": "Alex", "purpose": "x"},
                                         progress_callback=on_progress)
            return res.content[0].text

    assert "sig1" in anyio.run(go)
    assert len(beats) >= 3
    assert [b[0] for b in beats] == sorted(b[0] for b in beats)
    assert "signing pad" in beats[0][1]
