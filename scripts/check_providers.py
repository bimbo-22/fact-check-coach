"""Smoke-test every provider that has a key in .env. Never prints keys or tokens.

Usage: python -m scripts.check_providers   (or: make check-providers)
"""
import asyncio
import logging

import httpx

from app.claim_extractor import extract_claim
from app.config import get_settings
from app.fetcher import HttpFetcher
from app.search import BraveSearch, GoogleFactCheckSearch, TavilySearch, filter_and_rank

SAMPLE_POST = "Scientists confirm 5G towers make people sick!!! link in bio #5G"
SAMPLE_CLAIM = "5G towers make people sick"


def line(ok: bool | None, name: str, detail: str) -> None:
    mark = {True: "OK  ", False: "FAIL", None: "skip"}[ok]
    print(f"[{mark}] {name:18} {detail}")


async def check_llm(name: str, make) -> None:
    try:
        llm = make()
        ext = await extract_claim(llm, SAMPLE_POST)
        line(ext.ok, name, f"claim={ext.claim!r} checkable={ext.checkable}" if ext.ok
             else "no valid JSON after 2 tries (check model id / key)")
    except Exception as e:  # report and keep going
        line(False, name, f"{type(e).__name__}: {e}"[:160])


async def check_search(name: str, provider) -> None:
    try:
        raw = await provider.search(SAMPLE_CLAIM)
        kept = filter_and_rank(raw)
        with_text = sum(1 for r in kept if r.text)
        line(True, name, f"{len(raw)} results, {len(kept)} from our outlets, {with_text} with page text")
    except httpx.HTTPStatusError as e:
        line(False, name, f"HTTP {e.response.status_code}")
    except Exception as e:
        line(False, name, type(e).__name__)


async def main() -> None:
    logging.disable(logging.WARNING)
    s = get_settings()
    print(f"LLM_PROVIDER={s.llm_provider}  SEARCH_PROVIDER={s.search_provider}\n")

    try:
        async with httpx.AsyncClient(timeout=3) as c:
            tags = [m["name"] for m in (await c.get(f"{s.ollama_url}/api/tags")).json().get("models", [])]
        if s.ollama_model in tags:
            from app.llm.ollama import OllamaLLM
            await check_llm("ollama", lambda: OllamaLLM(s.ollama_url, s.ollama_model))
        else:
            line(False, "ollama", f"running, but {s.ollama_model} not pulled (ollama pull {s.ollama_model})")
    except httpx.HTTPError:
        line(None, "ollama", f"not running at {s.ollama_url}")

    if s.ica_api_key:
        from app.llm.ica import IcaLLM
        await check_llm(f"ica ({s.ica_model})", lambda: IcaLLM(s.ica_api_key, s.ica_base_url, s.ica_model))
    else:
        line(None, "ica", "ICA_API_KEY not set")

    if s.watsonx_api_key and s.watsonx_project_id:
        from app.llm.watsonx import WatsonxLLM
        await check_llm("watsonx", lambda: WatsonxLLM(s.watsonx_api_key, s.watsonx_project_id,
                                                      s.watsonx_url, s.watsonx_model_id))
    else:
        line(None, "watsonx", "WATSONX_API_KEY / WATSONX_PROJECT_ID not set")

    if s.anthropic_api_key:
        from app.llm.anthropic_client import AnthropicLLM
        await check_llm("anthropic", lambda: AnthropicLLM(s.anthropic_api_key, s.anthropic_model))
    else:
        line(None, "anthropic", "ANTHROPIC_API_KEY not set")

    for name, key, cls in (("google_factcheck", s.google_factcheck_api_key, GoogleFactCheckSearch),
                           ("tavily", s.tavily_api_key, TavilySearch),
                           ("brave", s.brave_api_key, BraveSearch)):
        if key:
            await check_search(name, cls(key))
        else:
            line(None, name, "key not set")

    pages = await HttpFetcher().fetch_all(["https://www.snopes.com/fact-check/", "https://www.reuters.com/fact-check/"])
    line(bool(pages), "direct fetch", f"{len(pages)}/2 test pages readable "
         "(Reuters/AP/AFP usually block: Tavily page text covers them)")

    if s.telegram_bot_token:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"https://api.telegram.org/bot{s.telegram_bot_token}/getMe")
            body = r.json()
            line(body.get("ok", False), "telegram", f"@{body['result']['username']}" if body.get("ok")
                 else f"rejected ({body.get('description', r.status_code)})")
        except httpx.HTTPError as e:
            line(False, "telegram", type(e).__name__)
    else:
        line(None, "telegram", "TELEGRAM_BOT_TOKEN not set")


if __name__ == "__main__":
    asyncio.run(main())
