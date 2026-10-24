"""LLM step 1: pull the single checkable claim out of a post. The LLM adds no facts."""
import json
import logging
import re
from dataclasses import dataclass

from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

SYSTEM = """You extract claims from social media posts for a fact-checking tool.
Reply with ONLY a JSON object, no prose, no code fences:
{"claim": string, "checkable": boolean, "breaking_news": boolean, "language": string}

Rules:
- "claim": the single claim the post most wants people to believe, restated neutrally in one sentence.
  Prefer the specific claim about who did what, what a person said, or what an image shows over general
  background context. Example: a post saying "Liberal woman cries after migrant looters take her store"
  next to "businesses are being looted" → the claim is "Migrants looted the store of a woman who supported
  immigration", not "businesses are being looted". Do not add facts, names, numbers or context that are
  not in the post. Do not say whether it is true.
- "checkable": false ONLY if the post is an opinion, a feeling, a joke, a question, or makes no factual
  claim at all. A claim that sounds absurd, conspiratorial or obviously false is still checkable
  ("5G spreads viruses", "NASA fakes space flights"), and so is a description of what a photo or video
  shows ("A video shows a shark on a flooded highway").
- "breaking_news": true if the post presents the claim as something happening right now.
- "language": ISO 639-1 code of the post."""


@dataclass
class Extraction:
    claim: str
    checkable: bool
    breaking_news: bool
    language: str
    ok: bool = True


FALLBACK = Extraction(claim="We couldn't pull a clear claim out of this post.", checkable=True,
                      breaking_news=False, language="und", ok=False)


def parse_extraction(raw: str) -> Extraction | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        claim = str(data["claim"]).strip()
        if not claim or not isinstance(data["checkable"], bool):
            return None
        return Extraction(claim=claim[:300], checkable=data["checkable"],
                          breaking_news=bool(data.get("breaking_news", False)),
                          language=str(data.get("language", "en"))[:8])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


async def extract_claim(llm: LLMClient, post: str) -> Extraction:
    """Try twice, then fall back to an 'unverified' placeholder."""
    for attempt in (1, 2):
        try:
            raw = await llm.complete("extract_claim", SYSTEM, f"POST:\n{post}")
        except LLMError as e:
            log.warning("claim extraction attempt %d failed: %s", attempt, e)
            continue
        if parsed := parse_extraction(raw):
            return parsed
        log.warning("claim extraction attempt %d returned invalid JSON", attempt)
    return FALLBACK
