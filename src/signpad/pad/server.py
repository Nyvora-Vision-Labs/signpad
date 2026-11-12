"""The signing pad: a small local web app where the human draws their signature
and reviews the signed result. The agent talks to it through ``PadServer``.

The server binds to 127.0.0.1 only. Every API call must carry a random
session token (kept in the page URL), and the Host header must be local,
so other websites open in the same browser cannot read or post to it.
"""
from __future__ import annotations

import base64
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
MAX_BODY = 8 * 1024 * 1024


class PadServer:
    def __init__(self, open_browser: bool = True, title: str = "SignPad"):
        self.token = secrets.token_urlsafe(18)
        self.open_browser = open_browser
        self._cond = threading.Condition()
        self._state: dict = {"phase": "waiting", "title": title,
                             "message": "The agent is reading your document."}
        self._result: dict | None = None
        self._preview: bytes | None = None
        self._seq = 0
        self._httpd: ThreadingHTTPServer | None = None
        self.url = ""

    # ------------------------------------------------------------ lifecycle
    def start(self) -> str:
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}/?t={self.token}"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        if self.open_browser:
            webbrowser.open(self.url)
        return self.url

    def close(self, message: str = "All done. You can close this tab."):
        self._set({"phase": "closed", "message": message})
        if self._httpd:
            threading.Timer(1.5, self._httpd.shutdown).start()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ agent side
    def _set(self, state: dict):
        with self._cond:
            self._seq += 1
            self._state = {**{"title": self._state.get("title")}, **state, "seq": self._seq}
            self._result = None
            self._cond.notify_all()

    def _wait(self, timeout: float | None):
        with self._cond:
            seq = self._seq
            ok = self._cond.wait_for(lambda: self._result is not None and self._result.get("seq") == seq,
                                     timeout=timeout)
            return self._result if ok else None

    def status(self, message: str):
        """Show a progress message on the page."""
        self._set({"phase": "waiting", "message": message})

    def request_signature(self, signer: str, purpose: str, timeout: float | None = None) -> bytes | None:
        """Ask the human to draw a signature. Returns PNG bytes, or None if they declined."""
        self._set({"phase": "sign", "signer": signer, "purpose": purpose})
        res = self._wait(timeout)
        self.status("Thanks. The agent is placing your signature.")
        if not res or res.get("action") != "signed":
            return None
        return res["png"]

    def request_review(self, summary: str, preview_pdf: bytes | None,
                       files: list[str], timeout: float | None = None) -> tuple[bool, str]:
        """Show the result and ask the human to approve it. Returns (approved, comment)."""
        self._preview = preview_pdf
        self._set({"phase": "review", "summary": summary, "files": files,
                   "has_preview": preview_pdf is not None})
        res = self._wait(timeout) or {}
        self.status("Thanks. Passing your answer to the agent.")
        return bool(res.get("approved")), str(res.get("comment", ""))

    # ------------------------------------------------------------ page side
    def _submit(self, data: dict) -> tuple[int, dict]:
        with self._cond:
            if data.get("seq") != self._seq:
                return 409, {"error": "This request is no longer current. Reload the page."}
            phase = self._state.get("phase")
            if phase == "sign" and data.get("action") == "signed":
                try:
                    png = base64.b64decode(data["png"].split(",", 1)[1], validate=True)
                except (KeyError, IndexError, ValueError):
                    return 400, {"error": "Bad image"}
                if png[:8] != b"\x89PNG\r\n\x1a\n":
                    return 400, {"error": "Bad image"}
                self._result = {"seq": self._seq, "action": "signed", "png": png}
            elif phase == "sign" and data.get("action") == "declined":
                self._result = {"seq": self._seq, "action": "declined"}
            elif phase == "review":
                self._result = {"seq": self._seq, "approved": bool(data.get("approved")),
                                "comment": str(data.get("comment", ""))[:2000]}
            else:
                return 409, {"error": f"Nothing to submit in phase {phase!r}"}
            self._cond.notify_all()
            return 200, {"ok": True}


def _make_handler(pad: PadServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _authorized(self, url) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            token = parse_qs(url.query).get("t", [""])[0] or self.headers.get("X-SignPad-Token", "")
            return host in ("127.0.0.1", "localhost") and secrets.compare_digest(token, pad.token)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in STATIC:
                name, ctype = STATIC[url.path]
                body = resources.files("signpad.pad").joinpath("static", name).read_bytes()
                return self._send(200, body, ctype)
            if not self._authorized(url):
                return self._json(403, {"error": "forbidden"})
            if url.path == "/api/state":
                with pad._cond:
                    state = dict(pad._state)
                return self._json(200, state)
            if url.path == "/preview.pdf" and pad._preview:
                return self._send(200, pad._preview, "application/pdf")
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorized(url):
                return self._json(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad json"})
            if url.path == "/api/submit":
                code, obj = pad._submit(data)
                return self._json(code, obj)
            return self._json(404, {"error": "not found"})

    return Handler


def capture_signature(out: Path, signer: str = "you", open_browser: bool = True) -> Path | None:
    """Standalone use: open the pad, save the drawn signature as a PNG."""
    with PadServer(open_browser=open_browser) as pad:
        print(f"Draw your signature at {pad.url}", flush=True)
        png = pad.request_signature(signer, "Draw the signature you want to save as an image.")
        if png is None:
            return None
        out.write_bytes(png)
        pad.status(f"Saved to {out}")
        return out
