import http.client
import io
import json
import urllib.error
import urllib.request

import pytest

from fileconverter import summarize as s


# ---------- extract + chunk ----------

def test_extract_markdown_pdf(text_pdf):
    assert "Hello summarizer world" in s.extract_markdown(text_pdf)


def test_extract_markdown_docx(sample_docx):
    assert "Revenue grew" in s.extract_markdown(sample_docx)


def test_extract_markdown_pptx(sample_pptx):
    assert "Roadmap" in s.extract_markdown(sample_pptx)


def test_extract_markdown_empty_raises(tmp_path, monkeypatch):
    class Empty:
        text_content = "   \n"

    class FakeMarkItDown:
        def convert(self, _):
            return Empty()

    import markitdown

    monkeypatch.setattr(markitdown, "MarkItDown", FakeMarkItDown)
    with pytest.raises(s.NoTextFound):
        s.extract_markdown(tmp_path / "x.pdf")


def test_chunk_small_text_is_one_chunk():
    assert s.chunk("a\n\nb", max_chars=100) == ["a\n\nb"]


def test_chunk_respects_limit_and_paragraphs():
    text = "\n\n".join(["x" * 40] * 5)
    parts = s.chunk(text, max_chars=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n\n".join(parts) == text


def test_chunk_hard_splits_huge_paragraph():
    parts = s.chunk("y" * 250, max_chars=100)
    assert [len(p) for p in parts] == [100, 100, 50]


# ---------- API ----------

def ok_response(content: str):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def http_error(code: int):
    return urllib.error.HTTPError(s.API_URL, code, "err", {}, io.BytesIO(b"details"))


@pytest.fixture
def calls(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return ok_response(f"summary {len(sent)}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


def test_single_chunk_one_call(calls):
    assert s.summarize("short text", "Short", "key", "m") == "summary 1"
    assert len(calls) == 1
    assert calls[0]["model"] == "m"
    assert calls[0]["messages"][0]["content"] == s.PROMPTS["Short"]


def test_many_chunks_map_reduce(calls, monkeypatch):
    monkeypatch.setattr(s, "chunk", lambda text: ["c1", "c2", "c3"])
    assert s.summarize("long", "Bullets", "key", "m") == "summary 4"
    assert len(calls) == 4  # 3 chunks + 1 combine
    assert calls[-1]["messages"][0]["content"] == s.PROMPTS["Bullets"]


def test_think_block_is_stripped(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: ok_response("<think>hmm</think>\nFinal"))
    assert s.summarize("text", "Short", "key", "m") == "Final"


def test_empty_reply_raises(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: ok_response(None))
    with pytest.raises(s.SummarizeError, match="empty reply"):
        s.summarize("text", "Short", "key", "m")


@pytest.mark.parametrize(
    "error, expected",
    [
        (http_error(401), s.BadApiKey),
        (http_error(403), s.BadApiKey),
        (http_error(429), s.RateLimited),
        (http_error(500), s.ApiError),
        (urllib.error.URLError("no route"), s.Offline),
        (TimeoutError(), s.Offline),
        (ConnectionResetError(), s.Offline),
        (http.client.RemoteDisconnected("closed"), s.Offline),
    ],
)
def test_errors_map_to_types(monkeypatch, error, expected):
    def boom(request, timeout):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(expected):
        s.summarize("text", "Short", "key", "m")


@pytest.mark.parametrize("payload", [b"<html>oops</html>", b"{}", b'{"choices": []}', b'{"choices": [{}]}', b"[]"])
def test_malformed_200_maps_to_api_error(monkeypatch, payload):
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: io.BytesIO(payload))
    with pytest.raises(s.ApiError):
        s.summarize("text", "Short", "key", "m")


# ---------- API key ----------

def test_env_key_wins(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env")
    assert s.get_api_key() == "nvapi-env"


def test_keyring_key(monkeypatch):
    import keyring

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = {}
    monkeypatch.setattr(keyring, "set_password", lambda svc, user, pw: store.__setitem__((svc, user), pw))
    monkeypatch.setattr(keyring, "get_password", lambda svc, user: store.get((svc, user)))
    s.set_api_key("  nvapi-stored  ")
    assert s.get_api_key() == "nvapi-stored"
