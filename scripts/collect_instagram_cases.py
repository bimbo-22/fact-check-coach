"""Build a labelled set of REAL Instagram posts from fact-check articles by our whitelisted outlets.

We never touch Instagram's API or scrape it. Fact-checkers already document viral Instagram posts: their
articles quote what the post claimed, often link it, and give a verdict. For each article we keep:
  - the claim as the Instagram post made it (extracted by the LLM, must appear in the article text),
  - the fact-checker's verdict (ground truth), backed by a verified quote from the article,
  - links to the original Instagram posts, if the article has them.

Usage: python -m scripts.collect_instagram_cases --target 50   (needs TAVILY_API_KEY + an LLM provider)
Output: datasets/instagram_factchecks.json
"""
import argparse
import asyncio
import json
import logging
import re
from datetime import date
from pathlib import Path

import httpx

from app.config import get_settings
from app.instagram import IG_URL_RE
from app.llm import make_llm
from app.llm.base import LLMClient, LLMError
from app.outlets import all_outlets, outlet_for_url
from app.quote_verifier import quote_in_text
from rapidfuzz import fuzz

OUT = Path("datasets/instagram_factchecks.json")
TOPICS = ["vaccine", "health cure", "cancer", "5G", "climate", "election", "immigration", "war Ukraine",
          "Israel Gaza", "celebrity", "AI-generated image", "food", "money scam", "weather", "space NASA",
          "covid", "politician quote", "crime", "science", "history photo", "animals", "sports", "technology",
          "viral video", "doctored photo", "fake quote", "chemtrails", "flat earth", "medicine", "diet",
          "earthquake", "hurricane", "protest", "royal family", "UK", "Africa", "India", "Nigeria", "Kenya",
          "Europe", "football", "school", "banking", "fuel prices", "water", "electric cars", "COVID vaccine"]

SYSTEM = """You read one fact-check article and extract what it says about a social media post.
Reply with ONLY a JSON object, no prose, no code fences:
{"about_instagram": boolean, "post_claim": string | null, "self_contained": boolean,
 "verdict": "false" | "misleading" | "true" | "other", "verdict_quote": string | null}

- "about_instagram": true only if the article checks a claim that was spread in an Instagram post or Reel
  (not an article about Instagram the company).
- "post_claim": the factual claim the post made, in one sentence a reader could check on its own, as the
  post's author would state it (e.g. "Covid vaccines alter your DNA", "A video shows a shark on a flooded
  highway"). Never include the verdict or words like "false" or "claims".
- "self_contained": true if post_claim alone is a specific factual claim (not a vague caption, joke,
  opinion or question).
- "verdict": the article's conclusion. false = false/fake/fabricated/pants on fire/no evidence;
  misleading = misleading/missing context/partly false/half true/altered; true = true/correct; else other.
- "verdict_quote": one sentence copied character for character from the article that states the verdict."""

VERDICT_RE = re.compile(r"\{.*\}", re.S)


async def tavily(client: httpx.AsyncClient, key: str, query: str) -> list[dict]:
    domains = [d for o in all_outlets() for d in o.domains]
    r = await client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"},
                          json={"query": query, "include_domains": domains, "max_results": 10,
                                "search_depth": "basic", "include_raw_content": True})
    r.raise_for_status()
    return r.json().get("results", [])


async def extract(llm: LLMClient, text: str) -> dict | None:
    try:
        raw = await llm.complete("collect", SYSTEM, f"ARTICLE:\n{text[:9000]}")
        m = VERDICT_RE.search(raw)
        return json.loads(m.group(0)) if m else None
    except (LLMError, json.JSONDecodeError):
        return None


async def collect(target: int) -> list[dict]:
    s = get_settings()
    if not s.tavily_api_key:
        raise SystemExit("TAVILY_API_KEY is not set in .env")
    llm = make_llm(s)
    cases: list[dict] = json.loads(OUT.read_text()) if OUT.exists() else []
    seen_urls = {c["review_url"] for c in cases}
    rejected = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for topic in TOPICS:
            if len(cases) >= target:
                break
            try:
                results = await tavily(client, s.tavily_api_key, f"fact check Instagram post {topic}")
            except httpx.HTTPError as e:
                print(f"search failed for {topic!r}: {type(e).__name__}")
                continue
            for r in results:
                url, text = r.get("url", ""), r.get("raw_content") or ""
                outlet = outlet_for_url(url)
                if not outlet or url in seen_urls or "instagram" not in text.lower() or len(cases) >= target:
                    continue
                seen_urls.add(url)
                info = await extract(llm, text)
                if not info or not info.get("about_instagram") or not info.get("post_claim"):
                    continue
                if not info.get("self_contained"):
                    continue
                if any(fuzz.token_set_ratio(info["post_claim"], c["post_claim"]) >= 85 for c in cases):
                    continue  # same claim already collected (e.g. a translation or a follow-up article)
                if info.get("verdict") not in ("false", "misleading", "true"):
                    continue
                if not quote_in_text(info.get("verdict_quote"), text):  # ground truth must be traceable
                    rejected += 1
                    continue
                cases.append({
                    "id": f"ig{len(cases) + 1:03d}",
                    "post_claim": info["post_claim"].strip(),
                    "label": info["verdict"],
                    "verdict_quote": info["verdict_quote"].strip(),
                    "outlet": outlet.name,
                    "review_url": url,
                    "review_title": r.get("title", ""),
                    "instagram_urls": sorted({m.group(0) for m in IG_URL_RE.finditer(text)})[:3],
                    "collected": date.today().isoformat(),
                })
                print(f"{len(cases):3d}. [{info['verdict']:>10}] {outlet.name:18} {info['post_claim'][:80]}")
            OUT.parent.mkdir(exist_ok=True)
            OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    print(f"\n{len(cases)} cases saved to {OUT} ({rejected} dropped: verdict quote not found in article)")
    return cases


def main() -> None:
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=50)
    asyncio.run(collect(ap.parse_args().target))


if __name__ == "__main__":
    main()
