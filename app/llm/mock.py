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


HEADERS = ("POST", "COMMENTS", "CLAIM", "SOURCE URL", "SOURCE TEXT", "VERDICT", "VERIFIED QUOTES")
FEELING_RE = re.compile(r"\b(scary|scared|lol|omg|wow|crazy|insane|honestly|cute|sad|angry)\b", re.I)


def _section(user: str, label: str) -> str:
    """Text after `LABEL:` up to the next prompt header that follows it (headers are fixed by our prompts)."""
    start = user.find(f"{label}:")
    if start == -1:
        return ""
    start += len(label) + 1
    later = [i for h in HEADERS[HEADERS.index(label) + 1:] if (i := user.find(f"\n{h}:", start)) != -1]
    return user[start:min(later) if later else len(user)].strip()


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
        if task == "split_comments":
            return json.dumps({"comments": [self._sort_comment(l) for l in _section(user, "COMMENTS").splitlines()
                                            if l.strip()]})
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

    def _sort_comment(self, line: str) -> dict:
        line = line.strip()
        if line.endswith("?"):
            return {"text": line, "kind": "question", "claim": None}
        if OPINION_RE.search(line) or FEELING_RE.search(line):
            return {"text": line, "kind": "opinion", "claim": None}
        return {"text": line, "kind": "claim", "claim": line}

    def _stance(self, claim: str, url: str, text: str) -> dict:
        if url in self.stances:
            scripted = self.stances[url]
            # Scripted stances are written against the positive claim; a negated claim ("there is no
            # evidence that…") flips them, so a debunking comment is correctly backed.
            if NEGATION_RE.search(claim) and scripted["stance"] in ("supports", "contradicts"):
                flipped = "supports" if scripted["stance"] == "contradicts" else "contradicts"
                return {**scripted, "stance": flipped}
            return scripted
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
