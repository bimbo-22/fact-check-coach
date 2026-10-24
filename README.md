# Fact-Check Coach

> **A fact-checker that trains you to need it less.**

Young people get their news from Instagram, and the correction is usually buried in the comments. Fact-Check Coach checks a post against 13 named fact-checkers, **asks you to guess first**, and always ends with **what's actually true**, using quotes checked word for word against the source.

Built for the IBM Responsible AI Hackathon: *"AI that makes us smarter, not more dependent."*

![How it works](docs/architecture.png)

## What it does

- **Chrome extension:** a red-flag score on every Instagram post (no source named, built to shock, "share before they delete this"…), worked out in your browser. Click **Fact-check this post** to check it in place.
- **Telegram bot:** send a screenshot, get the answer, then check the comments too.
- **Website:** drop a screenshot or paste a caption and try it.
- **Comments:** labels each comment as opinion, question, misinformation or backed by the sources.

## Run it

```bash
make install                 # Python 3.11 + dependencies
cp .env.example .env         # add your keys (see below)
make run                     # API + website on http://localhost:8000
make bot                     # Telegram bot (second terminal)
```

**Chrome extension:** open `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → select the `extension/` folder.

**No keys?** `make demo` runs everything offline with saved examples, and `make test` runs the 180 tests.

**Keys** (in `.env`, never committed):

| Key | Used for |
|---|---|
| `ICA_API_KEY` | AI models via IBM Consulting Advantage (Granite, Llama) |
| `TAVILY_API_KEY` | Live search of the 13 sources |
| `TELEGRAM_BOT_TOKEN` | The Telegram bot |

Docker: `make docker-up` (API + website) or `make docker-bot` (adds the bot).

## Sources

Reuters · AP · AFP (English and French) · BBC Verify · Snopes · PolitiFact · Full Fact · FactCheck.org · Lead Stories · USA Today · France 24 · Africa Check · Science Feedback

Each source gets **one vote**, and anything not on this list is ignored. The list is in [app/sources.yaml](app/sources.yaml).

## Results

Tested on **50 real Instagram posts** that fact-checkers had already checked, using the real models and live search:

| | Exactly right | Misinformation flagged | Called a false post true |
|---|---|---|---|
| Normal | 58% | 67% | **0** |
| Original fact-check hidden | 44% | 51% | **0** |

When it isn't sure, it says "unverified" and still shows what the sources do report. To re-run: `python -m scripts.evaluate`.

## Responsible AI

- **The AI never decides.** It only reads; fixed rules decide the verdict.
- **Every quote is checked** against the article. Made-up quotes, links or numbers are thrown out.
- **You stay in control:** guess first, red flags teach the warning signs, opinions are labelled, not judged.
- **Nothing is stored:** no accounts, posts, screenshots or usernames. Feed red flags never leave your browser.

## Limits

- If none of the 13 sources has covered a claim, the answer is "unverified".
- Instagram doesn't let apps read posts from a link, so the bot needs a screenshot.
- Pictures without text (e.g. AI-made images) aren't judged; the app shows how to check them yourself.

## Project layout

```
app/        API and the fact-checking pipeline
bot/        Telegram bot
extension/  Chrome extension
web/        Website
scripts/    Demo, evaluation and setup checks
tests/      180 tests
```
