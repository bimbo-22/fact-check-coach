"""LLM step 2: does this source support, contradict or not mention the claim? Plus the exact quote."""
import json
import logging
import re

URL_OR_MARKDOWN_RE = re.compile(r"https?://|www\.|!\[|\]\(|[*_#`]{2,}|^\s*[-*#]", re.M)
NUMBER_RE = re.compile(r"\d[\d,.]*")

from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

SYSTEM = """You label one news article against one claim for a fact-checking tool.
Judge only from the source text provided. Do not use outside knowledge.
If the text does not address the claim, answer not_mentioned.

Reply with ONLY a JSON object, no prose, no code fences:
{"stance": "supports" | "contradicts" | "not_mentioned", "quote": string | null, "related": string | null}

- "supports": the source says the claim, exactly as worded, is true.
- "contradicts": the source says the claim, exactly as worded, is false or unsupported.
Read negations carefully. Example: claim "There is no evidence that X causes Y" and source
"No study has linked X to Y" → supports, because the source agrees with the claim as worded.

"quote" must be copied character for character from the source text: the one sentence that
justifies your label. Use null when the stance is not_mentioned.

"related": if the source does NOT confirm or deny the claim but reports on the same event, place, people
or topic, copy the one most relevant sentence character for character. Otherwise null."""

KNOWN_SYSTEM = """You help a fact-checking tool tell a 15-year-old what trusted sources actually say.
Write ONE or TWO short sentences using ONLY the quotes provided. Do not add any fact, number or name that
is not in the quotes. No markdown, no links. Do not repeat the false claim as if it were true.
Reply with the sentences only."""

EXPLAIN_SYSTEM = """You explain a fact-check result to a 15-year-old in 1–2 short sentences.
Use ONLY the verified quotes provided. Do not add any fact, number or name that is not in them.
Do not use markdown. Reply with the sentences only."""

VALID = {"supports", "contradicts", "not_mentioned"}


def parse_stance(raw: str) -> tuple[str, str | None, str | None]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    related = data.get("related") if isinstance(data.get("related"), str) else None
    stance = data.get("stance")
    if stance not in VALID:
        return "not_mentioned", None, related
    quote = data.get("quote")
    return stance, quote if isinstance(quote, str) else None, related


async def label_source(llm: LLMClient, claim: str, url: str, text: str) -> tuple[str, str | None, str | None]:
    user = f"CLAIM: {claim}\nSOURCE URL: {url}\nSOURCE TEXT:\n{text}"
    try:
        return parse_stance(await llm.complete("stance", SYSTEM, user))
    except LLMError as e:
        log.warning("stance labelling failed: %s", e)
        return "not_mentioned", None, None


async def explain(llm: LLMClient, claim: str, verdict: str, quotes: list[str]) -> str | None:
    """Optional LLM explanation built only from verified quotes. None → caller uses a template."""
    if not quotes:
        return None
    user = f"CLAIM: {claim}\nVERDICT: {verdict}\nVERIFIED QUOTES:\n" + "\n".join(f"- {q}" for q in quotes[:4])
    try:
        out = (await llm.complete("explain", EXPLAIN_SYSTEM, user)).strip()
    except LLMError:
        return None
    return out if explanation_is_safe(out, quotes) else None


async def summarise_known(llm: LLMClient, claim: str, kind: str, quotes: list[str]) -> str | None:
    """'What's actually true' / 'what the outlets do report', rephrased from verified quotes only."""
    if not quotes:
        return None
    task = {"correction": "Say what the sources say is actually true instead of the claim.",
            "context": "The sources don't confirm or deny the claim. Say what they DO report on the topic.",
            "confirmed": "Say what the sources have confirmed so far."}[kind]
    user = (f"CLAIM: {claim}\nTASK: {task}\nVERIFIED QUOTES:\n" + "\n".join(f"- {q}" for q in quotes[:4]))
    try:
        out = (await llm.complete("known", KNOWN_SYSTEM, user)).strip()
    except LLMError:
        return None
    return out if explanation_is_safe(out, quotes) else None


def explanation_is_safe(text: str, quotes: list[str]) -> bool:
    """The explanation may only rephrase verified quotes: no links, no markdown, no new numbers."""
    if not 0 < len(text) <= 400 or URL_OR_MARKDOWN_RE.search(text):
        log.warning("explanation rejected: link/markdown or length")
        return False
    allowed = set(NUMBER_RE.findall(" ".join(quotes)))
    if any(n not in allowed for n in NUMBER_RE.findall(text)):
        log.warning("explanation rejected: number not in the verified quotes")
        return False
    return True
