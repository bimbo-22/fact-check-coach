"""Screenshot reading: a vision model ONLY transcribes the text in an image; the normal pipeline checks it.

The model is told not to explain, judge or add anything, and to skip interface text (usernames, like
counts). `scrub_ui` removes any that slip through. Images are never stored or logged.
"""
import base64
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
NO_TEXT = "NO_TEXT"
PROMPT = f"""Transcribe the text visible in this image exactly as written, one line per line of text.
Rules:
- Do not explain, summarise, correct, translate, judge or answer the text. Do not add anything.
- Skip interface text: usernames and @handles, profile names, like/view/comment counts, buttons,
  "View all comments", timestamps.
- If there is no readable text, reply exactly: {NO_TEXT}"""

# Instagram/Facebook image CDNs: the only hosts the API will download an image URL from.
ALLOWED_IMAGE_HOSTS = ("cdninstagram.com", "fbcdn.net")
UI_LINE_RE = re.compile(
    r"^\s*(♥|❤|♡)?\s*[\d.,]+\s*[kKmM]?\s*(likes?|views?|comments?|replies|shares?)\s*$"
    r"|^\s*view all [\d.,]+\s*comments?\s*$"
    r"|^\s*(reply|see translation|follow|following|liked by .*)\s*$",
    re.I,
)
# A line that is only a username: starts with @ or contains . _ or a digit (so a one-word comment like "fake" stays).
HANDLE_LINE_RE = re.compile(r"^\s*(@[a-z0-9._]{2,30}|(?=[a-z0-9._]*[._0-9])[a-z0-9._]{3,30})\s*$")


class ImageError(ValueError):
    pass


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ImageError("Send a PNG, JPEG or WebP image.")


def decode_image(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64.split(",", 1)[-1], validate=False)
    except ValueError as e:
        raise ImageError("That image couldn't be read.") from e
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("That image is too big (max 5 MB).")
    sniff_mime(data)
    return data


def image_host_allowed(url: str) -> bool:
    try:
        u = httpx.URL(url)
    except Exception:
        return False
    host = (u.host or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_IMAGE_HOSTS)


async def download_image(url: str) -> bytes | None:
    """Best-effort download of an Instagram CDN image (allowlisted hosts only, size-capped)."""
    if not image_host_allowed(url):
        return None
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            r = await client.get(url)
        if r.status_code != 200 or len(r.content) > MAX_IMAGE_BYTES:
            return None
        sniff_mime(r.content)
        return r.content
    except (httpx.HTTPError, ImageError):
        return None


def scrub_ui(text: str) -> str:
    lines = [l for l in text.splitlines() if not UI_LINE_RE.match(l) and not HANDLE_LINE_RE.match(l)]
    return "\n".join(l.rstrip() for l in lines if l.strip()).strip()


class Vision(ABC):
    name = "base"

    async def transcribe(self, image: bytes) -> str | None:
        """Text in the image (UI chrome removed), or None if there is none / the model failed."""
        try:
            raw = await self._transcribe(image, sniff_mime(image))
        except (httpx.HTTPError, KeyError, IndexError, ImageError) as e:
            log.warning("vision transcription failed: %s", type(e).__name__)
            return None
        text = scrub_ui((raw or "").replace("```", ""))
        return None if not text or text.strip() == NO_TEXT else text

    @abstractmethod
    async def _transcribe(self, image: bytes, mime: str) -> str: ...


class IcaVision(Vision):
    name = "ica"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key, self.model = api_key, model
        self.url = f"{base_url.rstrip('/')}/chat-models/chat/completions"

    async def _transcribe(self, image: bytes, mime: str) -> str:
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        body = {"model": self.model, "stream": False, "max_tokens": 800,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}}]}]}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


class OllamaVision(Vision):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url, self.model = base_url.rstrip("/"), model

    async def _transcribe(self, image: bytes, mime: str) -> str:
        body = {"model": self.model, "stream": False, "options": {"temperature": 0},
                "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(image).decode()]}]}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=body)
            r.raise_for_status()
        return r.json()["message"]["content"]


class MockVision(Vision):
    """Offline: images in tests/fixtures/images have a sidecar .txt with their transcription."""
    name = "mock"

    def __init__(self, fixtures_dir: Path) -> None:
        self.texts = {}
        for img in (fixtures_dir / "images").glob("*.png"):
            sidecar = img.with_suffix(".txt")
            if sidecar.exists():
                self.texts[hashlib.sha256(img.read_bytes()).hexdigest()] = sidecar.read_text()

    async def _transcribe(self, image: bytes, mime: str) -> str:
        return self.texts.get(hashlib.sha256(image).hexdigest(), NO_TEXT)


def make_vision(settings: Settings) -> Vision:
    provider = settings.vision_provider
    if provider == "auto":
        provider = settings.llm_provider if settings.llm_provider in ("ica", "ollama") else "mock"
    if provider == "ica" and settings.ica_api_key:
        return IcaVision(settings.ica_api_key, settings.ica_base_url, settings.ica_vision_model)
    if provider == "ollama":
        return OllamaVision(settings.ollama_url, settings.ollama_vision_model)
    return MockVision(settings.fixtures_dir)
