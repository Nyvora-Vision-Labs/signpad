"""Convert .docx to .pdf with whatever is installed: LibreOffice, then
Microsoft Word on macOS. Returns None when no converter works."""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


class ConversionError(Exception):
    pass


def _libreoffice(src: Path, out: Path, timeout: int) -> bool:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe and platform.system() == "Darwin":
        mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        exe = str(mac) if mac.exists() else None
    if not exe:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                       capture_output=True, timeout=timeout, check=False)
        produced = Path(tmp) / (src.stem + ".pdf")
        if produced.exists():
            shutil.move(str(produced), out)
            return True
    return False


def _word_mac(src: Path, out: Path, timeout: int) -> bool:
    if platform.system() != "Darwin" or not Path("/Applications/Microsoft Word.app").exists():
        return False
    script = f'''
    with timeout of {timeout} seconds
        tell application "Microsoft Word"
            set d to open file name (POSIX file "{src}" as string)
            save as d file name (POSIX file "{out}" as string) file format format PDF
            close d saving no
        end tell
    end timeout'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout + 10)
    except subprocess.TimeoutExpired as e:
        raise ConversionError(
            "Microsoft Word did not respond. It is probably showing a dialog (file access, "
            "sign-in or a save prompt). Answer it in Word and try again."
        ) from e
    if not out.exists() and r.stderr:
        raise ConversionError(f"Word could not export the PDF: {r.stderr.strip()}")
    return out.exists()


def docx_to_pdf(src: str | Path, out: str | Path | None = None, timeout: int = 90) -> Path | None:
    src = Path(src).resolve()
    out = Path(out).resolve() if out else src.with_suffix(".pdf")
    if out.exists():
        out.unlink()
    for convert in (_libreoffice, _word_mac):
        if convert(src, out, timeout):
            return out
    return None
