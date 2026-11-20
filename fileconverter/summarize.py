"""File -> Markdown -> NVIDIA API -> summary. No Qt imports."""
from __future__ import annotations

import json
import http.client
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

SUMMARY_EXTS = {".pdf", ".docx", ".pptx"}
Style = Literal["Short", "Detailed", "Bullets"]

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
KEY_URL = "https://build.nvidia.com"
MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b"]
DEFAULT_MODEL = MODELS[0]
KEYRING_SERVICE, KEYRING_USER = "FileConverter", "nvidia"

_COMMON = " Use only information from the document. Reply in the document's language."
PROMPTS: dict[str, str] = {
    "Short": "Summarize the document in one paragraph of at most 5 sentences." + _COMMON,
    "Detailed": "Summarize the document in several paragraphs covering every main section." + _COMMON,
    "Bullets": "Summarize the document as 5-10 concise bullet points." + _COMMON,
}
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class SummarizeError(Exception):
    """Base class; str(error) is a user-facing message."""


class NoTextFound(SummarizeError):
    pass


class BadApiKey(SummarizeError):
    pass


class RateLimited(SummarizeError):
    pass


class Offline(SummarizeError):
    pass


class ApiError(SummarizeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"NVIDIA API error {status}: {body[:200]}")
        self.status, self.body = status, body


def extract_markdown(src: Path) -> str:
    from markitdown import MarkItDown  # heavy import (onnxruntime); load on first use

    text = MarkItDown().convert(str(src)).text_content or ""
    if not text.strip():
        raise NoTextFound("No text found - scanned PDF? OCR is not supported.")
    return text


def chunk(text: str, max_chars: int = 100_000) -> list[str]:
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > max_chars:  # hard-split an oversized paragraph
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


def _chat(system: str, user: str, api_key: str, model: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": 2048,
            "temperature": 0.2,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:  # must come before URLError (subclass)
        detail = e.read().decode("utf-8", "replace")
        if e.code in (401, 403):
            raise BadApiKey("API key rejected - check it on build.nvidia.com.") from e
        if e.code == 429:
            raise RateLimited("Rate limited - wait a minute and try again.") from e
        raise ApiError(e.code, detail) from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected) as e:
        raise Offline("Cannot reach NVIDIA API - check your internet connection.") from e
    except json.JSONDecodeError as e:
        raise ApiError(200, "response was not JSON") from e
    try:
        reply = data["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise ApiError(200, "unexpected response shape") from e
    content = _THINK.sub("", reply or "").strip()
    if not content:
        raise SummarizeError("The model returned an empty reply - try again or pick another model.")
    return content


def summarize(text: str, style: Style, api_key: str, model: str = DEFAULT_MODEL) -> str:
    parts = chunk(text)
    if not parts:
        raise NoTextFound("No text found - scanned PDF? OCR is not supported.")
    if len(parts) == 1:
        return _chat(PROMPTS[style], parts[0], api_key, model)
    partials = [_chat(PROMPTS["Detailed"], part, api_key, model) for part in parts]
    return _chat(PROMPTS[style], "\n\n".join(partials), api_key, model)


def get_api_key() -> str | None:
    env = os.environ.get("NVIDIA_API_KEY", "").strip()
    if env:
        return env
    import keyring
    from keyring.errors import KeyringError

    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except KeyringError:
        return None


def set_api_key(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.strip())
