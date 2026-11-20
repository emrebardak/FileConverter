import shutil
import subprocess
from pathlib import Path

import pypdf
import pytest

from fileconverter import office

needs_lo = pytest.mark.skipif(office.find_soffice() is None, reason="LibreOffice not installed")


def test_find_soffice_does_not_raise():
    result = office.find_soffice()
    assert result is None or result.exists()


def test_missing_libreoffice_raises(monkeypatch, sample_docx, workdir):
    monkeypatch.setattr(office, "find_soffice", lambda: None)
    with pytest.raises(office.LibreOfficeMissing):
        office.to_pdf(sample_docx, workdir)


@needs_lo
def test_docx_to_pdf(sample_docx, workdir):
    out = office.to_pdf(sample_docx, workdir)
    assert len(pypdf.PdfReader(out).pages) >= 1


@needs_lo
def test_pptx_to_pdf(sample_pptx, workdir):
    out = office.to_pdf(sample_pptx, workdir)
    assert len(pypdf.PdfReader(out).pages) >= 1


@needs_lo
def test_same_stem_does_not_collide(sample_docx, sample_pptx, workdir):
    # sample.docx and sample.pptx both become sample.pdf
    a = office.to_pdf(sample_docx, workdir)
    b = office.to_pdf(sample_pptx, workdir)
    assert a != b and a.exists() and b.exists()


@needs_lo
def test_non_ascii_path_converts(sample_docx, workdir, tmp_path):
    src = tmp_path / "ÇĞÜ rapor şubat.docx"
    shutil.copy(sample_docx, src)
    out = office.to_pdf(src, workdir)
    assert len(pypdf.PdfReader(out).pages) >= 1


def test_failure_with_no_output_has_clean_message(monkeypatch, sample_docx, workdir):
    monkeypatch.setattr(office, "find_soffice", lambda: Path("soffice.exe"))
    monkeypatch.setattr(
        office.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=None, stderr=None),
    )
    with pytest.raises(office.ConversionError) as err:
        office.to_pdf(sample_docx, workdir)
    assert "NoneType" not in str(err.value)
