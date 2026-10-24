"""Deterministic, rule-based LLM used for tests and the offline demo.

Fixtures can script exact answers (`mock_extraction` on a post, `mock_stance` on a source);
anything unscripted falls back to simple keyword rules.
"""
import json
import re
from pathlib import Path

from app.llm.base import LLMClient
from app.text import normalise_post

OPINION_RE = re.compile(
    r"\b(i think|i feel|i believe|imo|in my opinion|best|worst|overrated|underrated|"
    r"should|deserve|is a crime|love|hate|disgusting|beautiful|ugly)\b",
    re.I,
)
BREAKING_RE = re.compile(r"\b(breaking|just now|happening now|right now|developing|live)\b", re.I)
NEGATION_RE = re.compile(
    r"\b(false|no evidence|not true|misleading|debunk\w*|fabricated|baseless|myth|"
    r"does not|do not|did not|no link|hoax|incorrect)\b",
    re.I,
)
STOPWORDS = {
    "that", "this", "with", "from", "have", "they", "their", "there", "about", "were", "will",
    "into", "your", "what", "when", "which", "than", "then", "them", "been", "every", "make",
    "makes", "people", "confirm", "confirms", "scientists",
}


def _section(user: str, label: str) -> str:
    m = re.search(rf"^{label}:\s*(.*?)(?=^\w[\w ]*:|\Z)", user, re.S | re.M)
    return m.group(1).strip() if m else ""


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{2,}", text.lower())
    return [w for w in words if (len(w) >= 4 or w.isalnum() and any(c.isdigit() for c in w))
            and w not in STOPWORDS]


class MockLLM(LLMClient):
    name = "mock"

    def __init__(self, fixtures_dir: Path) -> None:
        super().__init__()
        self.extractions: dict[str, dict] = {}
        self.stances: dict[str, dict] = {}
        for f in sorted((fixtures_dir / "instagram").glob("*.json")):
            post = json.loads(f.read_text())
            if "mock_extraction" in post:
                self.extractions[normalise_post(post["caption"]).lower()] = post["mock_extraction"]
        for f in sorted((fixtures_dir / "sources").glob("*.json")):
            src = json.loads(f.read_text())
            if "mock_stance" in src:
                self.stances[src["url"]] = src["mock_stance"]

    async def _complete(self, task: str, system: str, user: str) -> str:
        if task == "extract_claim":
            return json.dumps(self._extract(_section(user, "POST")))
        if task == "stance":
            return json.dumps(self._stance(
                _section(user, "CLAIM"), _section(user, "SOURCE URL"), _section(user, "SOURCE TEXT")))
        if task == "explain":
            return self._explain(user)
        raise ValueError(f"unknown task {task}")

    def _extract(self, post: str) -> dict:
        scripted = self.extractions.get(post.lower())
        if scripted:
            return scripted
        first = re.split(r"(?<=[.!?])\s+", post.strip())[0][:200]
        return {
            "claim": first,
            "checkable": not OPINION_RE.search(post),
            "breaking_news": bool(BREAKING_RE.search(post)),
            "language": "en",
        }

    def _stance(self, claim: str, url: str, text: str) -> dict:
        if url in self.stances:
            return self.stances[url]
        keys = set(_keywords(claim))
        if not keys:
            return {"stance": "not_mentioned", "quote": None}
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            hits = keys & set(_keywords(sentence))
            if len(hits) >= max(1, len(keys) // 2):
                stance = "contradicts" if NEGATION_RE.search(sentence) else "supports"
                return {"stance": stance, "quote": sentence.strip()}
        return {"stance": "not_mentioned", "quote": None}

    def _explain(self, user: str) -> str:
        verdict = _section(user, "VERDICT")
        quotes = [q.strip("- ").strip() for q in _section(user, "VERIFIED QUOTES").splitlines() if q.strip()]
        if not quotes:
            return ""
        return f"The outlets we checked point to '{verdict}'. For example: \"{quotes[0][:180]}\""
