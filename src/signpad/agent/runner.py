"""Runs the signing agent: Claude plus SignPad's tools, through the Anthropic
SDK's tool runner."""
from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path

import anthropic

from ..pad import PadServer
from .prompts import SYSTEM_PROMPT, first_message
from .session import Session
from .tools import build_tools

DEFAULT_MODEL = "claude-opus-5-5"
MAX_PDF_BYTES = 20 * 1024 * 1024


def _user_content(session: Session, request: str | None, signer: str | None) -> list[dict]:
    today = dt.date.today().strftime("%d %B %Y").lstrip("0")
    content: list[dict] = []
    # For PDFs, let Claude see the pages too, so it can judge layout and not just text.
    if session.doc.kind == "pdf" and session.doc.path.stat().st_size <= MAX_PDF_BYTES:
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(session.doc.path.read_bytes()).decode()},
        })
    content.append({"type": "text", "text": first_message(session.doc.path.name, session.doc.kind,
                                                          request, signer, today)})
    return content


def _print_progress(message, verbose: bool):
    for block in message.content:
        if block.type == "text" and block.text.strip():
            print(f"\n{block.text.strip()}\n", flush=True)
        elif block.type == "tool_use":
            print(f"  -> {block.name}", flush=True)
            if verbose:
                print(f"     {block.input}", flush=True)


def run_agent(path: str | Path, request: str | None = None, signer: str | None = None,
              output: str | Path | None = None, model: str = DEFAULT_MODEL,
              effort: str = "high", open_browser: bool = True, verbose: bool = False) -> Session:
    client = anthropic.Anthropic()
    pad = PadServer(open_browser=open_browser)
    pad.start()
    print(f"Signing pad: {pad.url}", flush=True)
    session = Session.open(path, pad, output)
    try:
        runner = client.beta.messages.tool_runner(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=build_tools(session),
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            # If a safety classifier declines a turn, the API retries it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            max_iterations=40,
            messages=[{"role": "user", "content": _user_content(session, request, signer)}],
        )
        last = None
        for message in runner:
            last = message
            _print_progress(message, verbose)
        if last is not None and last.stop_reason == "refusal":
            print("The model declined to continue with this request.", flush=True)
        elif last is not None and last.stop_reason == "max_tokens":
            print("The agent stopped early (output limit). Run it again to continue.", flush=True)
    finally:
        pad.close("The agent has finished. You can close this tab.")
    return session
