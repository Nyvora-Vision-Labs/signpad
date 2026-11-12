# SignPad

Agent-assisted handwritten signing for .docx and .pdf. Python package in `src/signpad`, tests in `tests/`.

## Commands

- Set up: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Test: `pytest` (no API key or browser needed; the pad is driven over HTTP and the agent's session is tested with a fake pad)
- Lint: `ruff check src tests`
- Try it: `signpad samples demo/ && signpad inspect demo/sample_agreement.docx`
- Agent run (needs Claude API credentials): `signpad agent demo/sample_agreement.docx --signer "Alex Example"`
- Claude Code as the agent (no API key): approve the `signpad` server from `.mcp.json`, then `/sign demo/sample_agreement.docx`

## Layout

- `documents/` file handlers (`base.py` interface, `docx.py`, `pdf.py`). Register new types in `documents/__init__.py`.
- `pad/` local signing web app. `server.py` (PadServer) + `static/` (index.html, app.js, style.css).
- `agent/` `session.py` (all logic, model-free), `tools.py` (`@beta_tool` wrappers), `prompts.py`, `runner.py` (SDK tool runner).
- `mcp_server.py` the Session tools over stdio MCP (`signpad mcp`) for Claude Code. `.claude/skills/sign/SKILL.md` is its prompt; keep it in step with `agent/prompts.py`.
- `convert.py` docx to pdf via LibreOffice or Word on macOS. `samples.py` builds test/demo forms. `cli.py` entry point.
- `docs/architecture.md` explains the design in detail.

## Rules that matter

- A signature must only ever come from the human drawing it in the pad. Never add a code path that generates, types or reuses a signature for the agent.
- Never overwrite the input file. Outputs go to a new path (`<name> - signed.<ext>` by default).
- Word text boxes exist twice (DrawingML + VML fallback in `mc:AlternateContent`); edit both.
- Never add an MCP tool that accepts a signature image or path; the MCP server must not print to stdout.
- Keep `agent/session.py` free of API code so it stays testable without a model.
- The Claude model is `claude-opus-5-5` (`agent/runner.py`, `cli.py`). Thinking is adaptive; effort is set explicitly; server-side refusal fallbacks are on.
- Pad API calls need the session token and a local Host header. Keep both checks.
