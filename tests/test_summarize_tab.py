from qt_helpers import qapp, settle  # noqa: F401  (qapp is a fixture)

import pytest

from fileconverter import summarize_tab as module
from fileconverter.convert_tab import ConvertTab
from fileconverter.summarize_tab import SummarizeTab


@pytest.fixture
def fake_api(monkeypatch):
    s = module.summarize
    monkeypatch.setattr(s, "get_api_key", lambda: "nvapi-test")
    monkeypatch.setattr(s, "extract_markdown", lambda src: f"text of {src.name}")
    monkeypatch.setattr(s, "summarize", lambda text, style, key, model: f"{style} | {model} | {text}")
    return s


def test_summarize_current_document(qapp, workdir, tall_png, fake_api):
    convert = ConvertTab(workdir)
    convert.add_files([tall_png])
    settle(qapp)
    tab = SummarizeTab(convert, workdir)
    tab.current_radio.setChecked(True)
    tab.run()
    settle(qapp)
    assert tab.result.toPlainText() == f"Short | {fake_api.DEFAULT_MODEL} | text of current.pdf"
    assert tab.run_btn.isEnabled()


def test_summarize_chosen_file_with_style(qapp, workdir, text_pdf, fake_api):
    tab = SummarizeTab(ConvertTab(workdir), workdir)
    tab.source = text_pdf
    next(b for b in tab.style_group.buttons() if b.property("style") == "Bullets").setChecked(True)
    tab.run()
    settle(qapp)
    assert tab.result.toPlainText() == f"Bullets | {fake_api.DEFAULT_MODEL} | text of text.pdf"


def test_failure_reenables_button(qapp, workdir, text_pdf, fake_api, monkeypatch):
    def boom(text, style, key, model):
        raise fake_api.Offline("Cannot reach NVIDIA API")

    monkeypatch.setattr(fake_api, "summarize", boom)
    shown = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda parent, title, text: shown.append(text))
    tab = SummarizeTab(ConvertTab(workdir), workdir)
    tab.source = text_pdf
    tab.run()
    settle(qapp)
    assert shown == ["Cannot reach NVIDIA API"]
    assert tab.run_btn.isEnabled()
    assert tab.result.toPlainText() == ""
