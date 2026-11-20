"""Office file -> PDF through headless LibreOffice. No Qt imports."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

OFFICE_EXTS = {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".odp", ".ods", ".rtf"}
LIBREOFFICE_URL = "https://www.libreoffice.org/download/"

_CANDIDATES = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]


class LibreOfficeMissing(Exception):
    """soffice.exe could not be found."""


class ConversionError(Exception):
    """LibreOffice failed or timed out."""


def _from_registry() -> Path | None:
    try:
        import winreg
    except ImportError:  # not Windows
        return None
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\LibreOffice\UNO\InstallPath",
                0,
                winreg.KEY_READ | view,
            ) as key:
                exe = Path(winreg.QueryValueEx(key, "")[0]) / "soffice.exe"
                if exe.exists():
                    return exe
        except OSError:
            continue
    return None


def find_soffice() -> Path | None:
    on_path = shutil.which("soffice")
    if on_path:
        return Path(on_path)
    for candidate in _CANDIDATES:
        if candidate.exists():
            return candidate
    return _from_registry()


def to_pdf(src: Path, workdir: Path, timeout: int = 120) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise LibreOfficeMissing("LibreOffice is required for Office files")
    run_dir = Path(tempfile.mkdtemp(prefix="lo-", dir=workdir)).resolve()
    profile, outdir = run_dir / "profile", run_dir / "out"
    cmd = [
        str(soffice),
        "--headless",
        "--norestore",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(src),
    ]
    try:
        # ponytail: kills soffice.exe on timeout; a stray soffice.bin child may linger.
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",  # soffice writes UTF-8, not the ANSI codepage
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError(f"{src.name}: timed out after {timeout}s") from e
    out = outdir / f"{src.stem}.pdf"
    if result.returncode != 0 or not out.exists():
        detail = ((result.stderr or "") + (result.stdout or "")).strip() or "LibreOffice produced no PDF"
        raise ConversionError(f"{src.name}: {detail}")
    return out
