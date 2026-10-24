"""Run real claims through the LIVE pipeline once and save everything as offline demo fixtures.

The saved set has the same layout as tests/fixtures (instagram/ + sources/), so the offline demo can
replay real outlets and real quotes with no network:

    python -m scripts.record_fixtures --out demo_fixtures "caption one" "caption two" ...
    python -m scripts.demo --fixtures demo_fixtures

Needs real providers in .env (LLM_PROVIDER=watsonx|anthropic, SEARCH_PROVIDER=tavily|brave|google_factcheck).
Only the claim, the public source pages and the model's labels are saved: no usernames, no chat data.
"""
import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from app.config import get_settings
from app.fetcher import HttpFetcher
from app.llm import make_llm
from app.llm.base import LLMClient
from app.pipeline import Pipeline
from app.search import SearchProvider, make_search
from app.stance import parse_stance


class RecordingLLM(LLMClient):
    def __init__(self, inner: LLMClient) -> None:
        super().__init__()
        self.inner = inner
        self.name = f"recording:{inner.name}"
        self.extractions: dict[str, str] = {}  # post → raw JSON
        self.stances: dict[str, str] = {}      # source URL → raw JSON

    async def _complete(self, task: str, system: str, user: str) -> str:
        out = await self.inner.complete(task, system, user)
        if task == "extract_claim":
            self.extractions[user.removeprefix("POST:\n")] = out
        elif task == "stance" and (m := re.search(r"^SOURCE URL: (.*)$", user, re.M)):
            self.stances[m.group(1).strip()] = out
        return out


class RecordingSearch(SearchProvider):
    def __init__(self, inner: SearchProvider) -> None:
        self.inner = inner
        self.name = f"recording:{inner.name}"
        self.results = []

    async def search(self, claim: str):
        res = await self.inner.search(claim)
        self.results.extend(res)
        return res


class RecordingFetcher(HttpFetcher):
    def __init__(self) -> None:
        self.pages: dict[str, str] = {}

    async def fetch_all(self, urls):
        pages = await super().fetch_all(urls)
        self.pages.update(pages)
        return pages


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "post"


async def record(captions: list[str], out: Path) -> None:
    settings = get_settings()
    if settings.llm_provider == "mock" or settings.search_provider == "mock":
        raise SystemExit("Set real providers in .env first (LLM_PROVIDER and SEARCH_PROVIDER must not be mock).")
    (out / "instagram").mkdir(parents=True, exist_ok=True)
    (out / "sources").mkdir(parents=True, exist_ok=True)

    for caption in captions:
        llm, search, fetcher = RecordingLLM(make_llm(settings)), RecordingSearch(make_search(settings)), RecordingFetcher()
        outcome = await Pipeline(llm, search, fetcher, settings).run(caption)
        ev = outcome.evidence
        if ev is None:
            print(f"skipped (needs text): {caption[:60]}")
            continue
        name = slug(ev.claim or caption)
        extraction = json.loads(next(iter(llm.extractions.values())))
        (out / "instagram" / f"{name}.json").write_text(json.dumps({
            "id": name, "caption": caption, "is_reel": False, "expected_verdict": ev.verdict,
            "mock_extraction": extraction}, ensure_ascii=False, indent=2) + "\n")

        saved = 0
        for i, r in enumerate(search.results):
            text = fetcher.pages.get(r.url) or r.text
            if not text or r.url not in llm.stances:
                continue
            stance, quote, _ = parse_stance(llm.stances[r.url])
            (out / "sources" / f"{name}_{i:02d}.json").write_text(json.dumps({
                "url": r.url, "title": r.title, "claim_keys": [ev.claim.lower()],
                "claimreview_rating": r.rating, "text": text,
                "mock_stance": {"stance": stance, "quote": quote}}, ensure_ascii=False, indent=2) + "\n")
            saved += 1
        print(f"{ev.verdict:>10} ({ev.confidence}) · {saved} sources saved · {ev.claim}")


def main() -> None:
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captions", nargs="+", help="post captions to check live")
    ap.add_argument("--out", type=Path, default=Path("demo_fixtures"))
    args = ap.parse_args()
    asyncio.run(record(args.captions, args.out))


if __name__ == "__main__":
    main()
