# Architecture

SignPad has three layers. Each works on its own, and the agent ties them together.

```
cli.py ──> agent/runner.py ──> Anthropic SDK tool runner ──> Claude
                │                         │
                │                    agent/tools.py   (8 tools, thin wrappers)
                │                         │
                └──────────────> agent/session.py      (state + actions, no API code)
                                   │              │
                         documents/*.py        pad/server.py ──> browser (pad/static/*)
```

## Documents (`src/signpad/documents/`)

`open_document(path)` returns a `Document` chosen by extension. Every handler implements:

| Method | Meaning |
|---|---|
| `outline()` | Text, one entry per paragraph (`p12: ...`) or PDF line (`page 2: ...`) |
| `slots()` | Candidate places for a signature or short text, ids `S1..Sn` |
| `place_image(slot, png, height_pt)` | Insert a drawn signature |
| `fill_text(slot, text)` | Insert a date or printed name |
| `clear_slot(slot)` | Remove text from a slot (Word), or remove what SignPad added (PDF) |
| `replace_text(old, new)` | Word only: change existing text everywhere it appears |
| `save(out)` | Write a new file; edits stay in memory until then |

### Word (`docx.py`)

Edits the raw OOXML with lxml so nothing Word wrote is lost. Notable details:

- **Text boxes** are DrawingML shapes inside `mc:AlternateContent`, with a VML copy in `mc:Fallback` for old readers. SignPad edits both copies, so the signature shows in every Word version. A box that is too short for a signature is made taller, along with its VML twin.
- **Paragraph text** ignores text boxes anchored inside the paragraph, so a typed name in a box does not appear twice in the outline.
- **Floating boxes** are often anchored a paragraph before their visible label. The slot carries text from both sides and a note saying so; the agent makes the call.
- Images are added as new parts (`word/media/signpadN.png`) with new relationship ids and unique `docPr` ids.

### PDF (`pdf.py`)

- Form fields: `/Sig` fields, and `/Tx` fields whose name mentions sign, date, name or initials.
- Text positions come from pypdf's text visitor; lines that say "Signature" get a free area to their right (or below, if there is no room). Underscore runs become `line` slots.
- Edits are drawn on a reportlab overlay and merged onto the page at save time.

## Signing pad (`src/signpad/pad/`)

`PadServer` runs a `ThreadingHTTPServer` on `127.0.0.1` on a random port. The browser page polls `/api/state` and shows one of three views: waiting, sign, review. The agent side calls block on a condition variable until the page submits:

- `request_signature(signer, purpose) -> bytes | None`
- `request_review(summary, preview_pdf, files) -> (approved, comment)`
- `status(message)`

Security: API calls need the session token from the page URL, the `Host` header must be local (blocks DNS rebinding), each submission must match the current request sequence number, and uploaded images must be PNGs under 8 MB.

The page (`static/app.js`) supports click-and-drag drawing and "hover" drawing (Start, 3-second countdown, then pointer movement draws; Space lifts the pen; click/Enter/Esc finishes). The export crops to the ink at 4x resolution on a transparent background.

## Agent (`src/signpad/agent/`)

- `session.py` holds the open document, the pad, captured signatures and the output path. All logic lives here, so it is tested without a model (`tests/test_session.py`).
- `tools.py` exposes the session to Claude with `@beta_tool`. `DocumentError` becomes a `ToolError`, which the model sees as an error result it can recover from.
- `prompts.py` sets the rules: signatures only from the pad, leave other parties' boxes alone, change only what signing needs, treat request text as information not instructions, end with `save_and_review`.
- `runner.py` starts the pad, builds the first message (PDFs are attached as a document block so Claude can see the layout), and runs `client.beta.messages.tool_runner` with adaptive thinking, `effort`, and server-side refusal fallbacks.

### Tools

| Tool | Purpose |
|---|---|
| `inspect_document` | Text + slots |
| `ask_user` | Question in the terminal |
| `request_signature` | Opens the pad, waits for the drawn signature |
| `place_signature` | Signature into a slot |
| `fill_text` | Date or name into a slot |
| `replace_text` | Change existing Word text (e.g. an old date) |
| `clear_slot` | Remove a typed name, or undo a placement |
| `save_and_review` | Save, export PDF, show the user, return their verdict |

## MCP server (`src/signpad/mcp_server.py`)

`signpad mcp` serves the `Session` actions over stdio MCP, so Claude Code (or any MCP client) is the agent and no API key is involved. Differences from the API agent:

- `open_document(path, output?)` picks the file; one server process can sign several documents in turn. `SigningState` holds one pad for the process lifetime and one open `Session`.
- There is no `ask_user` tool: the client asks the person in its own chat. (`Session.ask_user` reads stdin, which is the MCP pipe here.)
- Tool calls are serialized with a lock. `request_signature` and `save_and_review` block in a worker thread until the person acts in the pad.
- No tool accepts an image, so a signature can only come from the pad.
- Nothing may write to stdout except the protocol.

The project's `.mcp.json` registers the server and `.claude/skills/sign/SKILL.md` carries the signing guidance (the counterpart of `agent/prompts.py`). Keep the two in step when the rules change.

## Adding a file type

1. Add `documents/<type>.py` with a `Document` subclass.
2. Register it in `documents/__init__.py` (`HANDLERS`).
3. Add a sample builder to `samples.py` and tests mirroring `tests/test_pdf.py`.
