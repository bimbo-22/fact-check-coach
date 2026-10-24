"""LLM step 2: does this source support, contradict or not mention the claim? Plus the exact quote."""
import json
import logging
import re

from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

SYSTEM = """You label one news article against one claim for a fact-checking tool.
Judge only from the source text provided. Do not use outside knowledge.
If the text does not address the claim, answer not_mentioned.

Reply with ONLY a JSON object, no prose, no code fences:
{"stance": "supports" | "contradicts" | "not_mentioned", "quote": string | null}

"quote" must be copied character for character from the source text: the one sentence that
justifies your label. Use null when the stance is not_mentioned."""

EXPLAIN_SYSTEM = """You explain a fact-check result to a 15-year-old in 1–2 short sentences.
Use ONLY the verified quotes provided. Do not add any fact, number or name that is not in them.
Do not use markdown. Reply with the sentences only."""

VALID = {"supports", "contradicts", "not_mentioned"}


def parse_stance(raw: str) -> tuple[str, str | None]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    stance = data.get("stance")
    if stance not in VALID:
        return "not_mentioned", None
    quote = data.get("quote")
    return stance, quote if isinstance(quote, str) else None


async def label_source(llm: LLMClient, claim: str, url: str, text: str) -> tuple[str, str | None]:
    user = f"CLAIM: {claim}\nSOURCE URL: {url}\nSOURCE TEXT:\n{text}"
    try:
        return parse_stance(await llm.complete("stance", SYSTEM, user))
    except LLMError as e:
        log.warning("stance labelling failed: %s", e)
        return "not_mentioned", None


async def explain(llm: LLMClient, claim: str, verdict: str, quotes: list[str]) -> str | None:
    """Optional LLM explanation built only from verified quotes. None → caller uses a template."""
    if not quotes:
        return None
    user = f"CLAIM: {claim}\nVERDICT: {verdict}\nVERIFIED QUOTES:\n" + "\n".join(f"- {q}" for q in quotes[:4])
    try:
        out = (await llm.complete("explain", EXPLAIN_SYSTEM, user)).strip()
    except LLMError:
        return None
    return out if 0 < len(out) <= 400 else None
