"""Offline demo: walks through the four Instagram cases against the API in MOCK mode.

Runs the real FastAPI app in-process (no server, no network, no API keys), so it works with Wi-Fi off.
Usage: python -m scripts.demo   (or: make demo)
"""
import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["SEARCH_PROVIDER"] = "mock"

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
COLOR = sys.stdout.isatty()
VERDICT_STYLE = {"false": ("❌", "31"), "true": ("✅", "32"), "misleading": ("⚠️", "33"),
                 "unverified": ("❓", "37"), "developing": ("⏳", "35"), "opinion": ("💬", "36")}

# (title, request, simulated guess)
CASES = [
    ("1 · Viral 5G post, shared as an Instagram link",
     {"url": "https://www.instagram.com/p/FCCFIX5G01/"}, "true"),
    ("2 · Screenshot of a headline (Eiffel Tower)",
     {"text": json.loads((FIXTURES / "instagram" / "true_eiffel.json").read_text())["caption"]}, "not_sure"),
    ("3 · An opinion",
     {"text": json.loads((FIXTURES / "instagram" / "opinion_pizza.json").read_text())["caption"]}, "false"),
    ("4 · Breaking-news Reel nobody has covered yet",
     {"text": json.loads((FIXTURES / "instagram" / "breaking_reel.json").read_text())["caption"],
      "url": "https://www.instagram.com/reel/FIXREEL01/"}, "true"),
]


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def wrap(text: str, indent: str = "   ") -> str:
    return textwrap.fill(text, width=88, initial_indent=indent, subsequent_indent=indent)


async def demo_screenshot_and_comments(client: httpx.AsyncClient) -> None:
    img = lambda name: base64.b64encode((FIXTURES / "images" / name).read_bytes()).decode()
    print(c("━" * 88, "90"))
    print(c("5 · A screenshot of a headline, no caption at all", "1;34"))
    start = (await client.post("/check/start", json={"image_base64": img("headline_5g.png"), "client": "script"})).json()
    print(wrap(f"Text read from the image → claim: {start['claim']}"))
    print(wrap(f"🤔 {start['question']}"))
    r = (await client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "not_sure"})).json()
    emoji, code = VERDICT_STYLE[r["verdict"]]
    print("   " + c(f"{emoji} {r['verdict'].upper()}", f"1;{code}") + f"  · confidence {r['confidence']}")
    print(wrap(f"💡 {r['tip']}"))
    print()
    print(c("━" * 88, "90"))
    print(c("6 · The comment section (screenshot of 5 comments)", "1;34"))
    cm = (await client.post("/comments/check", json={"image_base64": img("comments_5g.png"), "client": "script"})).json()
    icons = {"opinion": "💬", "question": "❔", "other": "▫️"}
    vicons = {"false": ("🚩", "31"), "true": ("✅", "32"), "misleading": ("⚠️", "33"), "unverified": ("❓", "37")}
    for x in cm["comments"]:
        icon, code = vicons.get(x.get("verdict"), (icons.get(x["kind"], "▫️"), "0"))
        print(wrap(f"{icon} “{x['text']}”"))
        print("      " + c(x["label"], code))
    print(wrap(f"💡 {cm['tip']}"))
    print()


def recorded_cases(folder: Path) -> list:
    """Cases from a folder made by scripts/record_fixtures.py (real outlets, real quotes)."""
    return [(f"{i} · {p['caption'][:70]}", {"text": p["caption"]}, "true")
            for i, p in enumerate((json.loads(f.read_text()) for f in sorted((folder / "instagram").glob("*.json"))), 1)]


async def run(fixtures: Path, cases: list, llm_provider: str) -> None:
    logging.disable(logging.WARNING)  # the summary line reports caught hallucinations instead
    app = create_app(Settings(llm_provider=llm_provider, search_provider="mock", fixtures_dir=fixtures))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
        model = "mock LLM" if llm_provider == "mock" else f"{llm_provider} LLM (real model)"
        print(c(f"\nFact-Check Coach · demo ({model} + saved sources)\n", "1"))
        for title, req, guess in cases:
            print(c("━" * 88, "90"))
            print(c(title, "1;34"))
            if "url" in req:
                print(wrap(f"Link: {req['url']}"))
            if "text" in req:
                print(wrap(f"Caption: {req['text']}"))

            start = (await client.post("/check/start", json={**req, "client": "script"})).json()
            print(c("\n▶ /check/start  (no verdict yet)", "90"))
            if not start["checkable"]:
                print(wrap(f"💬 {start['note']}"))
                if not start["check_id"]:
                    continue
            else:
                print(wrap(f"Claim: {start['claim']}"))
                print(wrap(f"🤔 {start['question']}"))
            print(wrap(f"User guesses: {guess.replace('_', ' ')}"))

            r = (await client.post("/check/reveal", json={"check_id": start["check_id"], "guess": guess})).json()
            emoji, code = VERDICT_STYLE[r["verdict"]]
            a = r["agreement"]
            print(c("\n▶ /check/reveal", "90"))
            print("   " + c(f"{emoji} {r['verdict'].upper()}", f"1;{code}") + f"  · confidence {r['confidence']}")
            print(wrap(f"🎯 {r['guess_feedback']}"))
            print(wrap(r["explanation"]))
            if r["verdict"] != "opinion":
                print(wrap(f"📊 supports {a['supports']} · contradicts {a['contradicts']} · "
                           f"not covering {a['not_mentioned']} (of {a['outlets_checked']} outlets) · "
                           f"rejected AI quotes {a['rejected_quotes']}"))
            for s in r["sources"][:3]:
                quote = f" “{s['quote']}”" if s.get("quote") else ""
                print(wrap(f"• {s['outlet']} [{s['stance']}{', fact-check' if s['is_claimreview'] else ''}]{quote}"))
            print(wrap(f"💡 {r['tip']}"))
            print()
        if fixtures == FIXTURES:
            await demo_screenshot_and_comments(client)
        health = (await client.get("/health")).json()
        print(c("━" * 88, "90"))
        print(f"Checks run: {health['stats']['checks']} · cache hits: {health['stats']['cache_hits']} · "
              f"hallucinated quotes caught: {health['stats']['rejected_quotes']}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Offline Fact-Check Coach demo")
    ap.add_argument("--fixtures", type=Path, help="folder recorded by scripts/record_fixtures.py")
    ap.add_argument("--llm", default="mock", choices=["mock", "ollama", "ica"],
                    help="ollama = local open-source Granite; ica = IBM-hosted model via the ICA API (needs ICA_API_KEY)")
    args = ap.parse_args()
    if args.fixtures:
        asyncio.run(run(args.fixtures, recorded_cases(args.fixtures), args.llm))
    else:
        asyncio.run(run(FIXTURES, CASES, args.llm))
