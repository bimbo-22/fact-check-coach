"""Measure the live pipeline against the labelled Instagram set (datasets/instagram_factchecks.json).

Two modes:
  open     : normal operation. The fact-check article that labelled the case may be found as evidence.
  holdout  : that article (and anything else from its URL) is hidden, so the pipeline must rely on OTHER
             coverage. Harder and more honest about generalisation.

Scores: exact verdict match; "wrong" = said true when the label is false (or vice versa), the dangerous
error; "abstained" = unverified/developing (safe but unhelpful).

Usage: python -m scripts.evaluate --mode holdout --limit 50   (uses providers from .env)
"""
import argparse
import asyncio
import json
import logging
import time
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.main import build_pipeline
from app.search import SearchProvider

DATA = Path("datasets/instagram_factchecks.json")
OPPOSITE = {"true": "false", "false": "true"}


class HideArticle(SearchProvider):
    """Wraps the real search and drops the article that produced the label."""

    def __init__(self, inner: SearchProvider) -> None:
        self.inner, self.name, self.hidden = inner, f"holdout:{inner.name}", ""

    async def search(self, claim: str):
        return [r for r in await self.inner.search(claim) if r.url.split("#")[0].rstrip("/") != self.hidden]


async def run(mode: str, limit: int, out: Path) -> None:
    cases = json.loads(DATA.read_text())[:limit]
    settings = get_settings()
    rows = []
    started = time.time()
    for i, case in enumerate(cases, 1):
        pipeline = build_pipeline(settings)  # fresh cache per case: no leakage between cases
        if mode == "holdout":
            pipeline.search = HideArticle(pipeline.search)
            pipeline.search.hidden = case["review_url"].split("#")[0].rstrip("/")
        t = time.time()
        outcome = await pipeline.run(case["post_claim"])
        ev = outcome.evidence
        verdict = ev.verdict if ev else "needs_text"
        rows.append({"id": case["id"], "label": case["label"], "verdict": verdict,
                     "confidence": ev.confidence if ev else None, "seconds": round(time.time() - t, 1),
                     "outlets": [s.outlet for s in ev.sources] if ev else [],
                     "rejected_quotes": ev.agreement.rejected_quotes if ev else 0,
                     "claim": case["post_claim"]})
        mark = "✓" if verdict == case["label"] else ("✗" if OPPOSITE.get(case["label"]) == verdict else "·")
        print(f"{i:3d}/{len(cases)} {mark} label={case['label']:<10} got={verdict:<10} {case['post_claim'][:60]}",
              flush=True)

    n = len(rows)
    exact = sum(r["verdict"] == r["label"] for r in rows)
    wrong = sum(OPPOSITE.get(r["label"]) == r["verdict"] for r in rows)
    abstained = sum(r["verdict"] in ("unverified", "developing") for r in rows)
    flagged = sum(r["label"] in ("false", "misleading") and r["verdict"] in ("false", "misleading") for r in rows)
    bad = sum(r["label"] in ("false", "misleading") for r in rows)
    summary = {
        "mode": mode, "cases": n, "llm": settings.llm_provider, "model": getattr(pipeline.llm, "model", ""),
        "search": settings.search_provider,
        "exact_match": round(exact / n, 3),
        "misinformation_flagged": f"{flagged}/{bad}",
        "dangerous_errors": wrong,
        "abstained": abstained,
        "rejected_quotes_total": sum(r["rejected_quotes"] for r in rows),
        "median_seconds": sorted(r["seconds"] for r in rows)[n // 2],
        "confusion": Counter(f"{r['label']}→{r['verdict']}" for r in rows).most_common(),
        "minutes": round((time.time() - started) / 60, 1),
    }
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n")
    print("\n" + json.dumps(summary, indent=2))


def main() -> None:
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["open", "holdout"], default="holdout")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    out = Path(f"datasets/eval_{args.mode}.json")
    asyncio.run(run(args.mode, args.limit, out))


if __name__ == "__main__":
    main()
