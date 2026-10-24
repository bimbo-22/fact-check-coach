"""Orchestrates: Instagram → normalise → cache → extract → search → fetch → stance → verify → verdict → coach."""
import asyncio
import re
import logging
import time
from dataclasses import dataclass, field

from app import coach
from app.cache import TTLCache, text_hash
from app.claim_extractor import extract_claim
from app.config import Settings
from app.fetcher import MAX_SOURCE_CHARS, Fetcher

MIN_SOURCE_CHARS = 80  # drop empty junk only: short snippets can still hold a verifiable sentence
from app import comments as cm
from app.instagram import HASHTAGS_ONLY_MSG, NEEDS_TEXT_MSG, find_instagram_url, get_caption, is_reel_url
from app.instagram_graph import InstagramGraph
from app.llm.base import LLMClient
from app.models import Agreement, CommentOut, CommentsResponse, CommentsSummary, SourceOut
from app.outlets import all_outlets, outlet_by_id
from app.quote_verifier import verify_label
from app.search import SearchProvider, filter_and_rank
from app.models import SourceRef, WhatIsTrue
from app.quote_verifier import quote_in_text
from app.stance import explain, label_source, summarise_known
from app.text import URL_RE, Signals, detect_signals, normalise_post
from app.verdict import Evidence, decide
from app.vision import Vision, download_image

log = logging.getLogger("fcc.pipeline")

OPINION_NOTE = "This looks like an opinion. Opinions can't be fact-checked, but you can ask what facts they rest on."
LINK_ONLY_MSG = ("I can't open links from apps like that. Send me a screenshot of the post (quickest), "
                 "or paste what it says, and I'll check it.")
NOT_OUR_POST_MSG = ("I can only read comments on our own demo account's posts (that's Instagram's rule, and it keeps "
                    "other people's data out). Paste the comments or send a screenshot instead.")
NO_TEXT_IN_IMAGE_MSG = ("There's no text in this image for me to check, and I don't judge pictures myself: "
                        "dramatic images like this are often AI-made or old. Check it yourself: 1) do a reverse "
                        "image search (Google Lens or TinEye), 2) look for a news outlet's photo credit, 3) zoom in "
                        "on details like hands, signs and lights. Or type what the post claims and I'll check that.")


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
    what_is_true: WhatIsTrue | None = None


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
                 instagram_fetch=get_caption, vision: Vision | None = None,
                 instagram_graph: InstagramGraph | None = None, stance_llm: LLMClient | None = None) -> None:
        self.llm = llm
        self.stance_llm = stance_llm or llm
        self.vision = vision
        self.instagram_graph = instagram_graph
        self.search = search
        self.fetcher = fetcher
        self.settings = settings
        self.instagram_fetch = instagram_fetch
        self.claim_cache = TTLCache(settings.cache_ttl_seconds)  # claim hash → EvidenceResult
        self.input_cache = TTLCache(settings.cache_ttl_seconds)  # post hash → claim hash
        self.stats = {"checks": 0, "cache_hits": 0, "rejected_quotes": 0, "images_read": 0, "comment_checks": 0}

    async def read_image(self, image: bytes | None) -> str | None:
        """Text in a screenshot, via the vision model (transcription only)."""
        if image is None or self.vision is None:
            return None
        text = await self.vision.transcribe(image)
        if text:
            self.stats["images_read"] += 1
        return text

    async def run(self, text: str, url: str | None = None, image: bytes | None = None,
                  image_url: str | None = None) -> CheckOutcome:
        self.stats["checks"] += 1
        text = (text or "").strip()
        log.info("input %s", self._shape(text, url, image))
        ig_url = find_instagram_url(url, text)
        post_date, is_reel = None, bool(ig_url and is_reel_url(ig_url))
        if image is None and image_url:
            image = await download_image(image_url)

        # Links (with any tracking like ?igsh=…) aren't the user's text: only words outside URLs count.
        if ig_url and not normalise_post(text):
            # Our own demo account → official Graph API; anyone else's post → public preview, best effort.
            own = await self.instagram_graph.find_post(ig_url) if self.instagram_graph else None
            caption = own or await self.instagram_fetch(ig_url)
            log.info("instagram link: source=%s caption=%s preview_image=%s", "graph-api" if own else "public-preview",
                     "read" if caption.caption else "blocked", "yes" if caption.image_url else "no")
            post_date, is_reel = caption.post_date, caption.is_reel
            text = caption.caption or ""
            if image is None and caption.image_url:  # the post's own image may be a headline screenshot
                image = await download_image(caption.image_url)

        image_text = await self.read_image(image)
        if image_text:
            text = f"{text}\n{image_text}".strip()
        if not text:
            log.info("outcome needs_text reason=%s", "image_without_text" if image is not None else "instagram_blocked")
            return self._needs_text(NO_TEXT_IN_IMAGE_MSG if image is not None else NEEDS_TEXT_MSG, is_reel)

        signals = detect_signals(text, post_date=post_date, is_reel=is_reel)
        if image_text:
            signals.image_mentioned = True
        post = normalise_post(text, self.settings.max_input_chars)
        if not post:
            only_links = not normalise_post(URL_RE.sub(" ", text)) and URL_RE.search(text)
            log.info("outcome needs_text reason=%s", "link_only" if only_links else "hashtags_only")
            return self._needs_text(LINK_ONLY_MSG if only_links else HASHTAGS_ONLY_MSG, is_reel)

        evidence, hit = await self._evidence(post)
        log.info("outcome verdict=%s checkable=%s cache_hit=%s image_text=%s", evidence.verdict, evidence.checkable,
                 hit, "yes" if image_text else "no")
        if hit:
            self.stats["cache_hits"] += 1
        if not evidence.checkable:
            return CheckOutcome(evidence, signals, None, coach.pick_tip(signals, "opinion"),
                                note=OPINION_NOTE, cache_hit=hit)
        return CheckOutcome(evidence, signals, coach.pick_question(signals),
                            coach.pick_tip(signals, evidence.verdict), cache_hit=hit)

    @staticmethod
    def _shape(text: str, url: str | None, image: bytes | None) -> str:
        """What arrived, without content: lengths, link hosts/kinds and flags only (privacy-safe logging)."""
        links = URL_RE.findall(text or "") + ([url] if url else [])
        kinds = []
        for link in links:
            m = re.match(r"https?://(?:www\.)?([^/?#]+)(/[^/?#]*)?", link)
            kinds.append(f"{m.group(1)}{(m.group(2) or '')[:7] if m and 'instagram' in m.group(1) else ''}" if m else "?")
        return (f"text_len={len(text or '')} words_outside_links={len(normalise_post(text or '').split())} "
                f"links={kinds or '-'} image={'yes' if image else 'no'}")

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

        if not ext.checkable:
            claim_key = text_hash(ext.claim)
            result = EvidenceResult(claim=ext.claim, checkable=False, verdict="opinion",
                                    explanation=coach.template_explanation("opinion", Agreement()))
            self.claim_cache.set(claim_key, result)
            hit = False
        else:
            result, hit = await self.evidence_for_claim(ext.claim, ext.breaking_news)
            claim_key = text_hash(ext.claim)
        self.input_cache.set(post_key, claim_key)
        log.info("checked claim verdict=%s confidence=%s sources=%d rejected=%d in %.2fs",
                 result.verdict, result.confidence, len(result.sources),
                 result.agreement.rejected_quotes, time.perf_counter() - started)
        return result, hit

    async def evidence_for_claim(self, claim: str, breaking_news: bool = False) -> tuple[EvidenceResult, bool]:
        """Evidence for an already-extracted claim, through the claim cache."""
        claim_key = text_hash(claim)
        if cached := self.claim_cache.get(claim_key):
            return cached, True
        result = await self._check_claim(claim, breaking_news)
        self.claim_cache.set(claim_key, result)
        return result, False

    async def comments_from_post(self, url: str) -> CommentsResponse:
        """Real comment section of one of OUR demo account's posts, via the official Graph API."""
        own = await self.instagram_graph.find_post(url) if self.instagram_graph else None
        if own is None:
            return CommentsResponse(note=NOT_OUR_POST_MSG)
        texts = await self.instagram_graph.comments(own.id)
        if not texts:
            return CommentsResponse(note="That post has no comments yet.")
        return await self.check_comments("\n".join(" ".join(t.split()) for t in texts))

    async def check_comments(self, text: str, image: bytes | None = None) -> CommentsResponse:
        """Label each comment; check up to MAX_CLAIMS_CHECKED distinct claims against the whitelisted outlets."""
        self.stats["comment_checks"] += 1
        image_text = await self.read_image(image)
        raw = "\n".join(t for t in ((text or "").strip(), image_text) if t)
        if not raw:
            return CommentsResponse(note=NO_TEXT_IN_IMAGE_MSG if image is not None else "Paste the comments to check.")

        sorted_comments = await cm.sort_comments(self.llm, raw[: self.settings.max_input_chars * 2])
        if sorted_comments is None:
            return CommentsResponse(note="I couldn't separate those comments. Try pasting one comment per line.")

        claims = list(dict.fromkeys(c.claim for c in sorted_comments if c.claim))
        checked = dict(zip(claims[:cm.MAX_CLAIMS_CHECKED], await asyncio.gather(
            *(self.evidence_for_claim(c) for c in claims[:cm.MAX_CLAIMS_CHECKED]))))

        out, summary = [], CommentsSummary()
        for c in sorted_comments:
            if c.kind != "claim":
                summary.opinions += c.kind == "opinion"
                summary.questions += c.kind == "question"
                out.append(CommentOut(text=c.text, kind=c.kind, label=cm.KIND_LABELS[c.kind]))
                continue
            summary.claims += 1
            if c.claim not in checked:
                summary.unchecked_claims += 1
                out.append(CommentOut(text=c.text, kind="claim", claim=c.claim,
                                      label="Not checked: too many claims in one go"))
                continue
            ev = checked[c.claim][0]
            verdict = cm.comment_verdict(ev.verdict, c.denies)
            summary.misinformation += verdict == "false"
            summary.backed += verdict == "true"
            out.append(CommentOut(text=c.text, kind="claim", claim=c.claim, denies=c.denies,
                                  label=cm.LABELS[verdict], verdict=verdict, confidence=ev.confidence,
                                  source=cm.best_source(ev.sources),
                                  what_is_true=ev.what_is_true.text if verdict == "false" and ev.what_is_true
                                  and ev.what_is_true.kind == "correction" else None))
        return CommentsResponse(comments=out, summary=summary,
                                tip=cm.comments_tip(summary.misinformation, summary.backed, summary.opinions))

    async def _check_claim(self, claim: str, breaking_news: bool) -> EvidenceResult:
        try:
            raw = await self.search.search(claim)
        except Exception as e:  # search outage → unverified, never an error
            log.warning("search failed: %s", type(e).__name__)
            raw = []
        results = filter_and_rank(raw)
        pages = await self.fetcher.fetch_all([r.url for r in results])
        for r in results:
            if r.url in pages:
                continue
            if r.text and len(r.text.strip()) >= MIN_SOURCE_CHARS:  # blocked fetch → search provider's copy
                pages[r.url] = r.text[:MAX_SOURCE_CHARS]
            elif r.is_claimreview and r.rating and r.reviewed_claim:
                # Page unreachable: the publisher's structured ClaimReview is the source text. The LLM still
                # has to say how it relates to OUR claim, and its quote is verified against this text.
                pages[r.url] = (f"{outlet_by_id(r.outlet_id).name} fact-check. "
                                f"Claim reviewed: \"{r.reviewed_claim}\". Rating: {r.rating}.")

        # The headline goes first: fact-check titles often state the verdict. Quotes are verified against
        # exactly this text, so a quoted title is still a real quote from the source.
        pages = {u: f"{next(r.title for r in results if r.url == u)}\n\n{t}" for u, t in pages.items()}
        fetched = [r for r in results if r.url in pages]
        labels = await asyncio.gather(*(label_source(self.stance_llm, claim, r.url, pages[r.url]) for r in fetched))

        evidence: list[Evidence] = []
        rows: list[tuple[str, SourceOut]] = []
        rejected = 0
        related: list[tuple[str, SourceRef]] = []  # verified on-topic sentences from non-deciding articles
        for r, (stance, quote, rel) in zip(fetched, labels):
            outlet = outlet_by_id(r.outlet_id)
            stance, quote, was_rejected = verify_label(stance, quote, pages[r.url], outlet.domains[0])
            rejected += was_rejected
            if rel and stance == "not_mentioned":
                if quote_in_text(rel, pages[r.url]):
                    related.append((rel.strip(), SourceRef(outlet=outlet.name, url=r.url)))
                else:
                    rejected += 1
            evidence.append(Evidence(r.outlet_id, stance, r.is_claimreview, r.rating))
            rows.append((r.outlet_id, SourceOut(title=r.title, url=r.url, outlet=outlet.name,
                                                domain=outlet.domains[0], stance=stance, quote=quote,
                                                is_claimreview=r.is_claimreview, rating=r.rating)))
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
        known = await self._what_is_true(claim, vr.verdict, shown, related)
        return EvidenceResult(claim=claim, checkable=True, breaking_news=breaking_news, verdict=vr.verdict,
                              confidence=vr.confidence,
                              explanation=text or coach.template_explanation(vr.verdict, agreement),
                              agreement=agreement, sources=shown, what_is_true=known)

    async def _what_is_true(self, claim: str, verdict: str, shown: list[SourceOut],
                            related: list[tuple[str, SourceRef]]) -> WhatIsTrue | None:
        """End every result with something concrete from the sources, never a bare 'unverified'."""
        if verdict in ("false", "misleading"):
            kind, picks = "correction", [(s.quote, SourceRef(outlet=s.outlet, url=s.url))
                                         for s in shown if s.stance == "contradicts" and s.quote]
        elif verdict in ("unverified", "developing"):
            kind = "confirmed" if verdict == "developing" else "context"
            picks = [(s.quote, SourceRef(outlet=s.outlet, url=s.url)) for s in shown if s.quote] + related
        else:
            return None
        if not picks:
            if verdict == "unverified":
                return WhatIsTrue(kind="none", heading="What we know",
                                  text="None of our outlets has reported on this yet. That's a reason to wait "
                                       "before sharing, not proof that it's true or false.")
            return None
        picks = list({q: (q, ref) for q, ref in picks}.values())[:4]  # one entry per distinct quote
        text = await summarise_known(self.llm, claim, kind, [q for q, _ in picks])
        if not text:  # fall back to the best verified quote, word for word
            text = f"“{picks[0][0]}” ({picks[0][1].outlet})"
        heading = {"correction": "What's actually true", "context": "What the outlets do report",
                   "confirmed": "What's confirmed so far"}[kind]
        refs = list({ref.outlet: ref for _, ref in reversed(picks)}.values())[::-1][:3]  # one link per outlet
        return WhatIsTrue(kind=kind, heading=heading, text=text, sources=refs)
