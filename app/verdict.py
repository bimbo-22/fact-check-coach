"""Deterministic verdict rules: one vote per outlet. No LLM involved."""
import re
from collections import Counter
from dataclasses import dataclass, field

# --- Thresholds (see prompt.md §7 step 9) ---
CLAIMREVIEW_WEIGHT = 2      # a published fact-check is stronger than an article that only touches the claim
MIN_EVIDENCE = 2            # weighted votes needed for any verdict: one plain article is never enough
BREAKING_MIN_OUTLETS = 2    # breaking news covered by fewer outlets is "developing", not "unverified"
CLEAR_WIN = 2               # winning side with zero opposition
STRONG_WIN = 3              # winning side when there is some opposition...
DOMINANCE_RATIO = 2         # ...and it outweighs the other side at least 2:1
MISLEADING_MIN = 3          # total weighted votes before split evidence counts as "misleading"
HIGH_CONF_MIN = 4           # high confidence: ≥4 weighted, no opposition...
HIGH_CONF_OUTLETS = 2       # ...from at least 2 distinct outlets
MISLEADING_MEDIUM_MIN = 4   # misleading with this much evidence is medium confidence

# ClaimReview textualRating → stance. Ratings not listed here are ignored (e.g. "Mixture", "Half True").
RATING_MAP = {
    "false": "contradicts", "pants on fire": "contradicts", "fake": "contradicts",
    "incorrect": "contradicts", "not true": "contradicts", "fabricated": "contradicts",
    "wrong": "contradicts", "hoax": "contradicts", "mostly false": "contradicts", "altered": "contradicts",
    "true": "supports", "correct": "supports", "accurate": "supports", "mostly true": "supports",
}


def rating_to_stance(rating: str | None) -> str | None:
    if not rating:
        return None
    key = re.sub(r"[^a-z ]", "", rating.lower()).strip()
    return RATING_MAP.get(key)


@dataclass
class Evidence:
    """One verified article (or ClaimReview) from one outlet."""
    outlet_id: str
    stance: str  # supports | contradicts | not_mentioned (already quote-verified)
    is_claimreview: bool = False
    rating: str | None = None


@dataclass
class OutletVote:
    outlet_id: str
    stance: str
    weight: int


@dataclass
class VerdictResult:
    verdict: str
    confidence: str
    s: int = 0  # weighted support
    c: int = 0  # weighted contradiction
    S: int = 0  # supporting outlets
    C: int = 0  # contradicting outlets
    votes: list[OutletVote] = field(default_factory=list)


def outlet_votes(evidence: list[Evidence]) -> list[OutletVote]:
    by_outlet: dict[str, list[Evidence]] = {}
    for e in evidence:
        by_outlet.setdefault(e.outlet_id, []).append(e)

    votes = []
    for outlet_id, items in by_outlet.items():
        # 1. A ClaimReview with a known rating decides the outlet's stance.
        rated = Counter(s for e in items if e.is_claimreview and (s := rating_to_stance(e.rating)))
        if rated:
            top = rated.most_common()
            if len(top) == 1 or top[0][1] > top[1][1]:
                votes.append(OutletVote(outlet_id, top[0][0], CLAIMREVIEW_WEIGHT))
                continue
        # 2. Otherwise the majority of verified article stances; a tie means not_mentioned.
        counts = Counter(e.stance for e in items if e.stance != "not_mentioned")
        sup, con = counts["supports"], counts["contradicts"]
        stance = "supports" if sup > con else "contradicts" if con > sup else "not_mentioned"
        votes.append(OutletVote(outlet_id, stance, 1))
    return votes


def _confidence(win: int, lose: int, win_outlets: int) -> str:
    if win >= HIGH_CONF_MIN and lose == 0 and win_outlets >= HIGH_CONF_OUTLETS:
        return "high"
    if win >= STRONG_WIN or (win >= CLEAR_WIN and lose == 0):
        return "medium"
    return "low"


def decide(evidence: list[Evidence], breaking_news: bool = False) -> VerdictResult:
    votes = outlet_votes(evidence)
    s = sum(v.weight for v in votes if v.stance == "supports")
    c = sum(v.weight for v in votes if v.stance == "contradicts")
    S = sum(1 for v in votes if v.stance == "supports")
    C = sum(1 for v in votes if v.stance == "contradicts")

    def result(verdict: str, confidence: str) -> VerdictResult:
        return VerdictResult(verdict, confidence, s, c, S, C, votes)

    if breaking_news and S + C < BREAKING_MIN_OUTLETS:
        return result("developing", "low")
    if s + c < MIN_EVIDENCE:
        return result("unverified", "low")
    if (c >= CLEAR_WIN and s == 0) or (c >= STRONG_WIN and c >= DOMINANCE_RATIO * s):
        return result("false", _confidence(c, s, C))
    if (s >= CLEAR_WIN and c == 0) or (s >= STRONG_WIN and s >= DOMINANCE_RATIO * c):
        return result("true", _confidence(s, c, S))
    if S >= 1 and C >= 1 and s + c >= MISLEADING_MIN:
        return result("misleading", "medium" if s + c >= MISLEADING_MEDIUM_MIN else "low")
    return result("unverified", "low")
