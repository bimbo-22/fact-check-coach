"""Orchestrates: Instagram → normalise → cache → extract → search → fetch → stance → verify → verdict → coach."""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from app import coach
from app.cache import TTLCache, text_hash
from app.claim_extractor import extract_claim
from app.config import Settings
from app.fetcher import MAX_SOURCE_CHARS, Fetcher
from app.instagram import HASHTAGS_ONLY_MSG, NEEDS_TEXT_MSG, find_instagram_url, get_caption, is_reel_url
from app.llm.base import LLMClient
from app.models import Agreement, SourceOut
from app.outlets import all_outlets, outlet_by_id
from app.quote_verifier import verify_label
from app.search import SearchProvider, filter_and_rank
from app.stance import explain, label_source
from app.text import Signals, detect_signals, normalise_post
from app.verdict import Evidence, decide, rating_to_stance

log = logging.getLogger("fcc.pipeline")

OPINION_NOTE = "This looks like an opinion. Opinions can't be fact-checked, but you can ask what facts they rest on."


@dataclass
class EvidenceResult:
    """Everything about the claim itself. Safe to cache: it holds the neutral claim, never the post."""
    claim: str | None
    checkable: bool
    breaking_news: bool = False
    verdict: str = "unverified"
    confidence: str = "low"
    explanation: str = ""
    agreement: Agreement = field(default_factory=Agreement)
    sources: list[SourceOut] = field(default_factory=list)


@dataclass
class CheckOutcome:
    evidence: EvidenceResult | None
    signals: Signals
    question: str | None
    tip: str
    needs_text: bool = False
    note: str | None = None
    cache_hit: bool = False


class Pipeline:
    def __init__(self, llm: LLMClient, search: SearchProvider, fetcher: Fetcher, settings: Settings,
                 instagram_fetch=get_caption) -> None:
        self.llm = llm
        self.search = search
        self.fetcher = fetcher
        self.settings = settings
        self.instagram_fetch = instagram_fetch
        self.claim_cache = TTLCache(settings.cache_ttl_seconds)  # claim hash → EvidenceResult
        self.input_cache = TTLCache(settings.cache_ttl_seconds)  # post hash → claim hash
        self.stats = {"checks": 0, "cache_hits": 0, "rejected_quotes": 0}

    async def run(self, text: str, url: str | None = None) -> CheckOutcome:
        self.stats["checks"] += 1
        text = (text or "").strip()
        ig_url = find_instagram_url(url, text)
        post_date, is_reel = None, bool(ig_url and is_reel_url(ig_url))

        if ig_url and not normalise_post(text.replace(ig_url, "")):
            caption = await self.instagram_fetch(ig_url)
            post_date, is_reel = caption.post_date, caption.is_reel
            text = caption.caption or ""
        if not text:
            return self._needs_text(NEEDS_TEXT_MSG, is_reel)

        signals = detect_signals(text, post_date=post_date, is_reel=is_reel)
        post = normalise_post(text, self.settings.max_input_chars)
        if not post:
            return self._needs_text(HASHTAGS_ONLY_MSG, is_reel)

        evidence, hit = await self._evidence(post)
        if hit:
            self.stats["cache_hits"] += 1
        if not evidence.checkable:
            return CheckOutcome(evidence, signals, None, coach.pick_tip(signals, "opinion"),
                                note=OPINION_NOTE, cache_hit=hit)
        return CheckOutcome(evidence, signals, coach.pick_question(signals),
                            coach.pick_tip(signals, evidence.verdict), cache_hit=hit)

    def _needs_text(self, msg: str, is_reel: bool) -> CheckOutcome:
        return CheckOutcome(None, Signals(is_reel=is_reel), None, "", needs_text=True, note=msg)

    async def _evidence(self, post: str) -> tuple[EvidenceResult, bool]:
        post_key = text_hash(post)
        if (claim_key := self.input_cache.get(post_key)) and (cached := self.claim_cache.get(claim_key)):
            return cached, True

        started = time.perf_counter()
        ext = await extract_claim(self.llm, post)
        if not ext.ok:
            return EvidenceResult(claim=ext.claim, checkable=True,
                                  explanation=coach.template_explanation("unverified", Agreement(
                                      outlets_checked=len(all_outlets()), not_mentioned=len(all_outlets())))), False

        claim_key = text_hash(ext.claim)
        if cached := self.claim_cache.get(claim_key):
            self.input_cache.set(post_key, claim_key)
            return cached, True

        if not ext.checkable:
            result = EvidenceResult(claim=ext.claim, checkable=False, verdict="opinion",
                                    explanation=coach.template_explanation("opinion", Agreement()))
        else:
            result = await self._check_claim(ext.claim, ext.breaking_news)
        self.claim_cache.set(claim_key, result)
        self.input_cache.set(post_key, claim_key)
        log.info("checked claim verdict=%s confidence=%s sources=%d rejected=%d in %.2fs",
                 result.verdict, result.confidence, len(result.sources),
                 result.agreement.rejected_quotes, time.perf_counter() - started)
        return result, False

    async def _check_claim(self, claim: str, breaking_news: bool) -> EvidenceResult:
        try:
            raw = await self.search.search(claim)
        except Exception as e:  # search outage → unverified, never an error
            log.warning("search failed: %s", type(e).__name__)
            raw = []
        results = filter_and_rank(raw)
        pages = await self.fetcher.fetch_all([r.url for r in results])
        for r in results:  # outlet blocked our fetch → fall back to the provider's copy of the page
            if r.url not in pages and r.text:
                pages[r.url] = r.text[:MAX_SOURCE_CHARS]

        fetched = [r for r in results if r.url in pages]
        labels = await asyncio.gather(*(label_source(self.llm, claim, r.url, pages[r.url]) for r in fetched))

        evidence: list[Evidence] = []
        rows: list[tuple[str, SourceOut]] = []
        rejected = 0
        for r, (stance, quote) in zip(fetched, labels):
            outlet = outlet_by_id(r.outlet_id)
            stance, quote, was_rejected = verify_label(stance, quote, pages[r.url], outlet.domains[0])
            rejected += was_rejected
            evidence.append(Evidence(r.outlet_id, stance, r.is_claimreview, r.rating))
            shown_stance = stance
            if r.is_claimreview and (rated := rating_to_stance(r.rating)):
                # The publisher's rating decides; drop a quote that points the other way.
                quote = quote if stance == rated else None
                shown_stance = rated
            rows.append((r.outlet_id, SourceOut(title=r.title, url=r.url, outlet=outlet.name,
                                                domain=outlet.domains[0], stance=shown_stance, quote=quote,
                                                is_claimreview=r.is_claimreview, rating=r.rating)))
        # A ClaimReview's rating is structured data from the publisher, so it counts even if the page didn't load.
        for r in results:
            if r.url not in pages and r.is_claimreview and (stance := rating_to_stance(r.rating)):
                outlet = outlet_by_id(r.outlet_id)
                evidence.append(Evidence(r.outlet_id, "not_mentioned", True, r.rating))
                rows.append((r.outlet_id, SourceOut(title=r.title, url=r.url, outlet=outlet.name,
                                                    domain=outlet.domains[0], stance=stance,
                                                    is_claimreview=True, rating=r.rating)))
        self.stats["rejected_quotes"] += rejected

        vr = decide(evidence, breaking_news)
        n_outlets = len(all_outlets())
        agreement = Agreement(supports=vr.S, contradicts=vr.C, not_mentioned=n_outlets - vr.S - vr.C,
                              outlets_checked=n_outlets, rejected_quotes=rejected)

        # Show only the articles that back their outlet's vote, the winning side first.
        vote_of = {v.outlet_id: v.stance for v in vr.votes}
        shown = [src for oid, src in rows if src.stance != "not_mentioned" and src.stance == vote_of.get(oid)]
        winning = "contradicts" if vr.c >= vr.s else "supports"
        shown.sort(key=lambda s: (s.stance != winning, not s.is_claimreview))

        quotes = [s.quote for s in shown if s.quote]
        text = None
        if vr.verdict in ("true", "false", "misleading"):
            text = await explain(self.llm, claim, vr.verdict, quotes)
        return EvidenceResult(claim=claim, checkable=True, breaking_news=breaking_news, verdict=vr.verdict,
                              confidence=vr.confidence,
                              explanation=text or coach.template_explanation(vr.verdict, agreement),
                              agreement=agreement, sources=shown)
