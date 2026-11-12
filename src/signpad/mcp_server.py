"""SignPad as an MCP server, so Claude Code (or any MCP client) can be the agent.

The client's own model does the reasoning, so no Anthropic API key is needed
here. The tools are the same ``Session`` actions the API agent uses, with two
differences: ``open_document`` picks the file (one server can sign several in
turn), and there is no ``ask_user`` tool because the client can ask the person
in its own chat.

The signing pad runs inside this process and opens in the browser on the first
``open_document``. ``request_signature`` blocks until the person draws or
declines; there is deliberately no tool that accepts an image, so a signature
can only come from the pad.

Run with ``signpad mcp`` (stdio). Nothing may print to stdout except the
protocol itself.
"""
from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from pathlib import Path

from .agent.session import Pad, Session
from .documents import DocumentError

INSTRUCTIONS = """\
SignPad lets you help the person sign a .docx or .pdf on their computer with their own \
handwritten signature. Start with open_document, then inspect_document. The signature can only \
come from the person drawing it in the signing pad (request_signature); never substitute typed \
text, initials, or anything else, and never reuse a signature for a different signer. Change \
only what signing needs (signature slots, the signing date, fields the request asks for), leave \
boxes meant for other parties alone, ask the person in chat when the choice is genuinely theirs, \
and finish with save_and_review. The original file is never overwritten."""


class NoDocument(DocumentError):
    pass


class SigningState:
    """One pad for the server's lifetime, one open ``Session`` at a time."""

    def __init__(self, pad_factory: Callable[[], Pad] | None = None):
        self._pad_factory = pad_factory or _browser_pad
        self._pad: Pad | None = None
        self.session: Session | None = None
        self.lock = threading.Lock()

    @property
    def pad(self) -> Pad:
        if self._pad is None:
            self._pad = self._pad_factory()
        return self._pad

    def open(self, path: str, output: str | None) -> str:
        p = Path(path).expanduser()
        self.session = Session.open(p, self.pad, Path(output).expanduser() if output else None)
        url = getattr(self.pad, "url", "")
        return (f"Opened {self.session.doc.path} ({self.session.doc.kind}). "
                f"The signed copy will be saved to {self.session.output}. "
                + (f"The signing pad is open in the browser at {url} . " if url else "")
                + "Call inspect_document next.")

    def require(self) -> Session:
        if self.session is None:
            raise NoDocument("No document is open. Call open_document first.")
        return self.session

    def close(self):
        close = getattr(self._pad, "close", None)
        if close:
            close("The agent has finished. You can close this tab.")


def _browser_pad() -> Pad:
    from .pad import PadServer

    pad = PadServer(open_browser=True)
    pad.start()
    return pad


def build_server(state: SigningState | None = None):
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    state = state or SigningState()
    mcp = MCPServer("signpad", instructions=INSTRUCTIONS)

    def tool(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with state.lock:
                try:
                    return fn(*args, **kwargs)
                except DocumentError as e:
                    raise ToolError(str(e)) from e
        return mcp.tool()(wrapper)

    @tool
    def open_document(path: str, output: str | None = None) -> str:
        """Open a .docx or .pdf to sign and start the signing pad in the browser. Opening another
        file replaces the current one; signatures captured for the previous file are not carried
        over.

        Args:
            path: Absolute path of the document to sign.
            output: Where to save the signed copy. Defaults to "<name> - signed.<ext>" next to the
                original. It can never be the original file.
        """
        return state.open(path, output)

    @tool
    def inspect_document() -> str:
        """Read the open document: its text (one entry per paragraph or line, with ids like p12 or
        page 2) and the candidate slots where a signature or short text can go. Each slot has an
        id (S1, S2, ...), a kind, its label, any text already in it, and nearby text. Call this
        first, and again after edits if you need to re-check what a slot holds. For a PDF you can
        also read the file itself to see the page layout."""
        return state.require().inspect()

    @tool
    def request_signature(signer_name: str, purpose: str) -> str:
        """Ask the person to draw their handwritten signature in the signing pad, and wait until
        they do (this can take a minute). Tell them in chat to switch to the browser tab before
        calling it. This is the only way to obtain a signature. Returns a signature id, or says
        the person declined.

        Args:
            signer_name: Name of the person signing, as it appears in the document.
            purpose: One or two sentences shown in the pad: what they are signing and where it goes.
        """
        return state.require().request_signature(signer_name, purpose)

    @tool
    def place_signature(slot_id: str, signature_id: str, height_pt: float = 36) -> str:
        """Put a captured signature into a slot. Any text already in a text-box slot is replaced.

        Args:
            slot_id: Slot id from inspect_document, e.g. S3.
            signature_id: Id returned by request_signature, e.g. sig1.
            height_pt: Signature height in points. 30 to 40 suits most forms.
        """
        return state.require().place_signature(slot_id, signature_id, height_pt)

    @tool
    def fill_text(slot_id: str, text: str) -> str:
        """Write short text, such as a date or a printed name, into a slot.

        Args:
            slot_id: Slot id from inspect_document.
            text: The text to write.
        """
        return state.require().fill_text(slot_id, text)

    @tool
    def replace_text(old: str, new: str) -> str:
        """Replace existing text everywhere it appears (Word files only), e.g. an outdated date.
        Use exact text copied from inspect_document.

        Args:
            old: Exact existing text.
            new: Replacement text.
        """
        return state.require().replace_text(old, new)

    @tool
    def clear_slot(slot_id: str) -> str:
        """Empty a slot: remove text from a Word text box or table cell, or remove what SignPad
        added to a PDF slot. Use it to take out a typed name that a handwritten signature must
        replace, or to undo a misplaced signature.

        Args:
            slot_id: Slot id from inspect_document.
        """
        return state.require().clear_slot(slot_id)

    @tool
    def save_and_review(summary: str) -> str:
        """Save the signed copy (never over the original), make a PDF copy of Word files when a
        converter is available, and show the result to the person for approval in the signing pad,
        waiting for their answer. Returns the saved paths, whether they approved, and their comment.
        If they did not approve, fix what they describe and call this again.

        Args:
            summary: Plain-language list of every change you made, for the person to check.
        """
        return state.require().save_and_review(summary)

    return mcp


def main() -> int:
    state = SigningState()
    try:
        build_server(state).run("stdio")
    finally:
        state.close()
    return 0
