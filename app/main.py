"""FastAPI app. Front ends use /check/start → /check/reveal; /check is the one-shot for scripts."""
import logging
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.coach import guess_feedback
from app.config import Settings, get_settings
from app.fetcher import FixtureFetcher, HttpFetcher
from app.instagram import make_fixture_fetch
from app.cache import CheckStore
from app.llm import make_llm
from app.instagram_graph import InstagramGraph
from app.models import (CheckRequest, CommentsFromPostRequest, CommentsRequest, CommentsResponse, RevealRequest,
                        RevealResponse, StartResponse)
from app.outlets import all_outlets, load_sources
from app.pipeline import CheckOutcome, Pipeline
from app.search import make_search
from app.vision import ImageError, decode_image, make_vision

# Log only IDs, verdicts, counts and timings: never post text, usernames or chat IDs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full URLs, incl. API keys
log = logging.getLogger("fcc.api")


def build_pipeline(settings: Settings) -> Pipeline:
    if settings.search_provider == "mock":  # fully offline: saved source pages and Instagram previews
        return Pipeline(make_llm(settings), make_search(settings), FixtureFetcher(settings.fixtures_dir), settings,
                        instagram_fetch=make_fixture_fetch(settings.fixtures_dir), vision=make_vision(settings))
    graph = (InstagramGraph(settings.instagram_access_token, settings.instagram_user_id)
             if settings.instagram_access_token and settings.instagram_user_id else None)
    return Pipeline(make_llm(settings), make_search(settings), HttpFetcher(), settings, vision=make_vision(settings),
                    instagram_graph=graph)


def image_bytes(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        return decode_image(b64)
    except ImageError as e:
        raise HTTPException(422, str(e)) from e


def to_reveal(outcome: CheckOutcome, guess: str | None) -> RevealResponse:
    ev = outcome.evidence
    return RevealResponse(
        verdict=ev.verdict, confidence=ev.confidence, claim=ev.claim, explanation=ev.explanation,
        agreement=ev.agreement, sources=ev.sources,
        guess_feedback=guess_feedback(guess, ev.verdict, ev.agreement) if guess else None,
        tip=outcome.tip,
    )


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Fact-Check Coach", version="0.1.0",
                  description="A fact-checker that trains you to need it less.")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^(chrome-extension://.*|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.state.pipeline = pipeline or build_pipeline(settings)
    app.state.checks = CheckStore(settings.check_ttl_seconds)

    @app.get("/health")
    async def health() -> dict:
        p: Pipeline = app.state.pipeline
        return {"status": "ok", "llm_provider": p.llm.name, "search_provider": p.search.name,
                "vision_provider": p.vision.name if p.vision else None, "stats": p.stats}

    @app.get("/sources")
    async def sources() -> dict:
        bias_checked, _ = load_sources()
        return {"bias_checked": bias_checked, "outlets": [o.public() for o in all_outlets()],
                "note": "Only these outlets count as evidence. Each outlet gets one vote."}

    @app.post("/check/start", response_model=StartResponse)
    async def check_start(req: CheckRequest) -> StartResponse:
        outcome = await app.state.pipeline.run(req.text, req.url, image_bytes(req.image_base64), req.image_url)
        if outcome.needs_text:
            return StartResponse(check_id=None, claim=None, checkable=False, question=None,
                                 note=outcome.note, needs_text=True)
        check_id = str(uuid.uuid4())
        app.state.checks.put(check_id, outcome)
        log.info("start check_id=%s client=%s cache_hit=%s", check_id, req.client, outcome.cache_hit)
        ev = outcome.evidence
        return StartResponse(check_id=check_id, claim=ev.claim, checkable=ev.checkable,
                             question=outcome.question, note=outcome.note)

    @app.post("/check/reveal", response_model=RevealResponse)
    async def check_reveal(req: RevealRequest) -> RevealResponse:
        status, outcome = app.state.checks.get(req.check_id)
        if status == "missing":
            raise HTTPException(404, "Unknown check_id.")
        if status == "expired":
            raise HTTPException(410, "This check has expired. Send the post again.")
        log.info("reveal check_id=%s verdict=%s guess=%s", req.check_id, outcome.evidence.verdict, req.guess)
        return to_reveal(outcome, req.guess)

    @app.post("/check", response_model=RevealResponse)
    async def check_one_shot(req: CheckRequest) -> RevealResponse:
        outcome = await app.state.pipeline.run(req.text, req.url, image_bytes(req.image_base64), req.image_url)
        if outcome.needs_text:
            raise HTTPException(422, outcome.note)
        return to_reveal(outcome, None)

    @app.post("/comments/check", response_model=CommentsResponse)
    async def comments_check(req: CommentsRequest) -> CommentsResponse:
        """Label pasted or screenshotted comments: opinion / question / claim, and check the claims."""
        result = await app.state.pipeline.check_comments(req.text, image_bytes(req.image_base64))
        log.info("comments client=%s opinions=%d claims=%d misinformation=%d backed=%d", req.client,
                 result.summary.opinions, result.summary.claims, result.summary.misinformation, result.summary.backed)
        return result

    @app.post("/comments/from-post", response_model=CommentsResponse)
    async def comments_from_post(req: CommentsFromPostRequest) -> CommentsResponse:
        """Read and check the real comments of one of OUR demo account's posts (official Graph API)."""
        result = await app.state.pipeline.comments_from_post(req.url)
        log.info("comments-from-post client=%s claims=%d misinformation=%d", req.client,
                 result.summary.claims, result.summary.misinformation)
        return result

    return app


app = create_app()
