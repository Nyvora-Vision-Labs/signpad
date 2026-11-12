"""The agent's tools: thin wrappers that expose ``Session`` actions to Claude."""
from __future__ import annotations

import functools

from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from ..documents import DocumentError
from .session import Session


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DocumentError as e:
            raise ToolError(f"Error: {e}") from e
    return wrapper


def build_tools(session: Session) -> list:
    @beta_tool
    @_guard
    def inspect_document() -> str:
        """Read the document: its text (one entry per paragraph or line, with ids like p12 or
        page 2) and the candidate slots where a signature or short text can go. Each slot has an
        id (S1, S2, ...), a kind, its label, any text already in it, and nearby text. Call this
        first, and again after edits if you need to re-check what a slot holds."""
        return session.inspect()

    @beta_tool
    @_guard
    def ask_user(question: str) -> str:
        """Ask the user a question in the terminal and wait for the typed answer. Use it when the
        document or the request leaves a real choice open, such as which party the user signs as.

        Args:
            question: One clear question.
        """
        return session.ask_user(question)

    @beta_tool
    @_guard
    def request_signature(signer_name: str, purpose: str) -> str:
        """Open the signing pad so the user draws their handwritten signature, and wait for it.
        This is the only way to obtain a signature. Returns a signature id, or says the user
        declined.

        Args:
            signer_name: Name of the person signing, as it appears in the document.
            purpose: One or two sentences shown to the user: what they are signing and where it goes.
        """
        return session.request_signature(signer_name, purpose)

    @beta_tool
    @_guard
    def place_signature(slot_id: str, signature_id: str, height_pt: float = 36) -> str:
        """Put a captured signature into a slot. Any text already in a text-box slot is replaced.

        Args:
            slot_id: Slot id from inspect_document, e.g. S3.
            signature_id: Id returned by request_signature, e.g. sig1.
            height_pt: Signature height in points. 30 to 40 suits most forms.
        """
        return session.place_signature(slot_id, signature_id, height_pt)

    @beta_tool
    @_guard
    def fill_text(slot_id: str, text: str) -> str:
        """Write short text, such as a date or a printed name, into a slot.

        Args:
            slot_id: Slot id from inspect_document.
            text: The text to write.
        """
        return session.fill_text(slot_id, text)

    @beta_tool
    @_guard
    def replace_text(old: str, new: str) -> str:
        """Replace existing text everywhere it appears (Word files only), e.g. an outdated date.
        Use exact text copied from inspect_document.

        Args:
            old: Exact existing text.
            new: Replacement text.
        """
        return session.replace_text(old, new)

    @beta_tool
    @_guard
    def clear_slot(slot_id: str) -> str:
        """Empty a slot: remove text from a Word text box or table cell, or remove what SignPad
        added to a PDF slot. Use it to take out a typed name that a handwritten signature must
        replace, or to undo a misplaced signature.

        Args:
            slot_id: Slot id from inspect_document.
        """
        return session.clear_slot(slot_id)

    @beta_tool
    @_guard
    def save_and_review(summary: str) -> str:
        """Save the signed copy (never over the original), make a PDF copy of Word files when a
        converter is available, and show the result to the user for approval in the signing pad.
        Returns the saved paths, whether the user approved, and their comment.

        Args:
            summary: Plain-language list of every change you made, for the user to check.
        """
        return session.save_and_review(summary)

    return [inspect_document, ask_user, request_signature, place_signature,
            fill_text, replace_text, clear_slot, save_and_review]
