"""Comment-section checking: label each comment opinion / question / claim, and check the claims.

The original problem is that the debunk is buried in the comments. So we flag misinformation AND point
out the comments the evidence backs up. The LLM only sorts and restates; verdicts come from the pipeline.
Usernames are dropped before anything is labelled; nothing is stored.
"""
import json
import logging
import re
from dataclasses import dataclass

from app.llm.base import LLMClient, LLMError
from app.models import SourceOut

log = logging.getLogger(__name__)

MAX_COMMENTS = 20
MAX_CLAIMS_CHECKED = 5  # resource use: each claim is a full evidence check

SYSTEM = """You sort social media comments for a fact-checking tool.
Reply with ONLY a JSON object, no prose, no code fences:
{"comments": [{"text": string, "kind": "opinion" | "claim" | "question" | "other",
               "claim": string | null, "position": "asserts" | "denies" | null}]}

Rules:
- One entry per comment, in the order given. Leave out usernames, handles, like counts and timestamps.
- "text": the comment as written, without the username.
- "claim": a comment that states something factual that could be checked. Put the underlying claim in
  "claim", stated POSITIVELY in one neutral sentence (no "not", no "no evidence"), and say in "position"
  whether the comment asserts it or denies it. Add nothing that isn't in the comment.
  Example: "Fake, there's no proof vaccines cause autism" → claim "Vaccines cause autism", position "denies".
- "opinion": feelings, judgements, jokes, insults. "question": asks something. "other": anything else.
- Do not say whether anything is true."""

LABELS = {
    "false": "Misinformation: the outlets we checked say this is false",
    "misleading": "Misleading: the outlets we checked disagree with parts of it",
    "true": "Backed by the outlets we checked",
    "unverified": "Unverified: we couldn't confirm or debunk it",
    "developing": "Unverified: still developing",
}
KIND_LABELS = {
    "opinion": "Opinion: can't be fact-checked",
    "question": "Question",
    "other": "Not a factual claim",
}


@dataclass
class SortedComment:
    text: str
    kind: str
    claim: str | None
    denies: bool = False  # the comment rejects `claim` (claims are always stated positively)


INVERT = {"true": "false", "false": "true"}


def comment_verdict(claim_verdict: str, denies: bool) -> str:
    """Verdict on the comment itself: denying a false claim is right, denying a true one is wrong."""
    return INVERT.get(claim_verdict, claim_verdict) if denies else claim_verdict


def parse_sorted(raw: str) -> list[SortedComment] | None:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        items = json.loads(m.group(0))["comments"] if m else None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    out = []
    for it in items[:MAX_COMMENTS]:
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        kind = it.get("kind") if it.get("kind") in ("opinion", "claim", "question", "other") else "other"
        claim = str(it["claim"]).strip() if kind == "claim" and it.get("claim") else None
        out.append(SortedComment(str(it["text"]).strip()[:500], "claim" if claim else
                                 ("other" if kind == "claim" else kind), claim,
                                 denies=bool(claim) and it.get("position") == "denies"))
    return out


async def sort_comments(llm: LLMClient, comments_text: str) -> list[SortedComment] | None:
    for attempt in (1, 2):
        try:
            raw = await llm.complete("split_comments", SYSTEM, f"COMMENTS:\n{comments_text}")
        except LLMError as e:
            log.warning("comment sorting attempt %d failed: %s", attempt, e)
            continue
        if (parsed := parse_sorted(raw)) is not None:
            return parsed
    return None


def comments_tip(misinfo: int, backed: int, opinions: int) -> str:
    if misinfo and backed:
        return "The loudest comment isn't always right. Look for the ones that name a source."
    if misinfo:
        return "Comments can spread a false claim as fast as the post itself. Don't take them as proof."
    if backed:
        return "Sometimes the correction is right there in the comments. Check which ones cite a source."
    if opinions:
        return "Most comments are reactions, not evidence. Feelings tell you how people react, not what happened."
    return "Read comments as leads to check, not as facts."


def best_source(sources: list[SourceOut]) -> SourceOut | None:
    return next((s for s in sources if s.quote), sources[0] if sources else None)
