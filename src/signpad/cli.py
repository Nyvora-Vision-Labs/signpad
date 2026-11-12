"""Command line: ``signpad agent | mcp | inspect | place | pad | convert | samples``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .documents import DocumentError, open_document


def _cmd_agent(a):
    from .agent import run_agent

    request = None
    if a.request:
        request = Path(a.request).read_text(encoding="utf-8")
    elif a.request_text:
        request = a.request_text
    session = run_agent(a.file, request=request, signer=a.signer, output=a.output,
                        model=a.model, effort=a.effort, open_browser=not a.no_browser,
                        verbose=a.verbose)
    if session.saved:
        print("\nSaved:\n  " + "\n  ".join(str(p) for p in session.saved))
    return 0 if session.approved else 1


def _cmd_mcp(a):
    from .mcp_server import main as serve

    return serve()


def _cmd_inspect(a):
    doc = open_document(a.file)
    print(f"{doc.path.name} ({doc.kind})\n")
    slots = doc.slots()
    if not slots:
        print("No signature places found.")
    for s in slots:
        where = f" page {s.page}" if s.page else ""
        print(f"{s.id:>4}  {s.kind:<11}{where}  {s.label[:60]!r}")
        if s.current_text:
            print(f"      holds: {s.current_text!r}")
        for ctx in (s.context_before, s.context_after):
            if ctx:
                print(f"      near:  {ctx[:90]}")
    if a.text:
        print("\n" + "\n".join(doc.outline()))
    return 0


def _cmd_place(a):
    doc = open_document(a.file)
    png = Path(a.signature).read_bytes()
    if a.clear:
        doc.clear_slot(a.slot)
    print(doc.place_image(a.slot, png, a.height))
    out = Path(a.output) if a.output else doc.path.with_name(f"{doc.path.stem} - signed{doc.path.suffix}")
    print(f"Saved {doc.save(out)}")
    if a.pdf and doc.kind == "docx":
        from .convert import docx_to_pdf
        pdf = docx_to_pdf(out)
        print(f"Saved {pdf}" if pdf else "No .docx to .pdf converter found.")
    return 0


def _cmd_pad(a):
    from .pad import capture_signature

    out = capture_signature(Path(a.output), open_browser=not a.no_browser)
    print(f"Saved {out}" if out else "Declined.")
    return 0 if out else 1


def _cmd_convert(a):
    from .convert import docx_to_pdf

    pdf = docx_to_pdf(a.file, a.output)
    print(f"Saved {pdf}" if pdf else "No .docx to .pdf converter found (LibreOffice or Microsoft Word).")
    return 0 if pdf else 1


def _cmd_samples(a):
    from .samples import build_sample_docx, build_sample_pdf, build_sample_signature

    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    for p in (build_sample_docx(d / "sample_agreement.docx"), build_sample_pdf(d / "sample_consent.pdf")):
        print(f"Wrote {p}")
    build_sample_signature(d / "sample_signature.png")
    print(f"Wrote {d / 'sample_signature.png'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="signpad", description="Agent-assisted handwritten document signing.")
    p.add_argument("--version", action="version", version=f"signpad {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ag = sub.add_parser("agent", help="Let the agent read the document and walk you through signing it.")
    ag.add_argument("file", help=".docx or .pdf to sign")
    g = ag.add_mutually_exclusive_group()
    g.add_argument("--request", metavar="FILE", help="text file with the request you received (e.g. an email)")
    g.add_argument("--request-text", metavar="TEXT", help="the request, inline")
    ag.add_argument("--signer", help="your name as it appears in the document")
    ag.add_argument("-o", "--output", help="where to save the signed copy")
    ag.add_argument("--model", default="claude-opus-5-5")
    ag.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ag.add_argument("--no-browser", action="store_true", help="print the pad URL instead of opening it")
    ag.add_argument("-v", "--verbose", action="store_true")
    ag.set_defaults(func=_cmd_agent)

    mc = sub.add_parser("mcp", help="Serve SignPad's tools over MCP (stdio) so Claude Code can be the agent.")
    mc.set_defaults(func=_cmd_mcp)

    ins = sub.add_parser("inspect", help="List the places a signature could go.")
    ins.add_argument("file")
    ins.add_argument("--text", action="store_true", help="also print the document text")
    ins.set_defaults(func=_cmd_inspect)

    pl = sub.add_parser("place", help="Put a signature PNG into a slot, without the agent.")
    pl.add_argument("file")
    pl.add_argument("--slot", required=True, help="slot id from `signpad inspect`")
    pl.add_argument("--signature", required=True, help="PNG from `signpad pad`")
    pl.add_argument("--height", type=float, default=36, help="signature height in points")
    pl.add_argument("--clear", action="store_true", help="empty the slot first (e.g. a typed name)")
    pl.add_argument("--pdf", action="store_true", help="also export a PDF (Word files)")
    pl.add_argument("-o", "--output")
    pl.set_defaults(func=_cmd_place)

    pd = sub.add_parser("pad", help="Open the signing pad and save your drawn signature as a PNG.")
    pd.add_argument("-o", "--output", default="signature.png")
    pd.add_argument("--no-browser", action="store_true")
    pd.set_defaults(func=_cmd_pad)

    cv = sub.add_parser("convert", help="Convert .docx to .pdf (LibreOffice or Microsoft Word).")
    cv.add_argument("file")
    cv.add_argument("-o", "--output")
    cv.set_defaults(func=_cmd_convert)

    sm = sub.add_parser("samples", help="Write sample forms to try SignPad on.")
    sm.add_argument("dir", nargs="?", default="samples")
    sm.set_defaults(func=_cmd_samples)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DocumentError as e:
        print(f"signpad: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
