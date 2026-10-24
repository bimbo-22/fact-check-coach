"""The coaching layer: one reflective question before the reveal, one tip after, friendly guess feedback."""
from app.models import Agreement
from app.text import Signals

DEFAULT_QUESTION = "Before I show you: who posted this, and do they link a source?"


def pick_question(s: Signals) -> str:
    if s.is_reel:
        return "Who's speaking in this Reel, and do they say where their info comes from?"
    if s.image_mentioned:
        return "It's a screenshot of a headline. Did the outlet really publish it? How could you tell?"
    if s.link_in_bio:
        return "It says \"link in bio\". Would you click through before sharing? What do you expect is behind it?"
    if s.emotional:
        return "How does this post make you feel, and could that be the point?"
    return DEFAULT_QUESTION


def pick_tip(s: Signals, verdict: str) -> str:
    if verdict == "opinion":
        return "Opinions can't be fact-checked, but you can ask which facts they're built on."
    if verdict == "developing":
        return "Breaking news changes fast. Wait until at least two trusted outlets report it before sharing."
    if s.old_date:
        return f"Check the date: this is from {s.old_year}. Old stories get reshared as if they're new."
    if s.image_mentioned:
        return "Search the headline: if a real outlet published it, you'll find it on their own site."
    if s.is_reel:
        return "Reels cut out context. Look for where the clip or claim originally came from."
    if s.link_in_bio:
        return "\"Link in bio\" hides the source. Check what's behind it before you share."
    if s.emotional:
        return "Notice how it makes you feel. Posts built to shock spread faster than careful ones."
    if s.many_hashtags:
        return "Hashtags spread a post; they don't prove it."
    if not s.has_source_link:
        return "Does it cite a source? A claim with no source is a claim you can't check."
    return "Open the source yourself and read past the headline."


def agreement_line(verdict: str, a: Agreement) -> str:
    covering = a.supports + a.contradicts
    if verdict == "false":
        return f"{a.contradicts} of the {covering} outlets that cover it say it's false"
    if verdict == "true":
        return f"{a.supports} of the {covering} outlets that cover it say it's true"
    if verdict == "misleading":
        return f"the outlets disagree: {a.supports} back it, {a.contradicts} contradict it"
    if covering == 0:
        return f"none of the {a.outlets_checked} outlets we checked cover it"
    return f"only {covering} of {a.outlets_checked} outlets we checked cover it"


def guess_feedback(guess: str, verdict: str, a: Agreement) -> str:
    line = agreement_line(verdict, a)
    if verdict == "opinion":
        return "This is an opinion, so there's no right guess. Good on you for stopping to think about it."
    if verdict in ("unverified", "developing"):
        if guess == "not_sure":
            return f"\"Not sure\" was the smart call: {line}, so nobody can confirm it yet."
        return f"You guessed {guess}, but nobody can confirm it either way yet: {line}. Holding back is the safe move."
    if verdict == "misleading":
        if guess == "not_sure":
            return f"Fair to be unsure: {line}. Parts of it may be true, but the full picture isn't."
        return f"It's not that simple: {line}. Parts of it may be true, but the full picture isn't."
    if guess == "not_sure":
        return f"Fair to be unsure. Here's what the evidence says: {line}."
    if guess == verdict:
        return f"Nice, you got it: {line}."
    return f"You guessed {guess}, but {line}."


def template_explanation(verdict: str, a: Agreement) -> str:
    covering = a.supports + a.contradicts
    return {
        "true": f"{a.supports} of the {covering} trusted outlets that cover this say it's accurate.",
        "false": f"{a.contradicts} of the {covering} trusted outlets that cover this say it's not true.",
        "misleading": "The outlets that cover this don't agree: some parts hold up and some don't.",
        "unverified": "We couldn't find enough coverage from trusted outlets to confirm or debunk this.",
        "developing": "This looks like breaking news, and trusted outlets haven't confirmed it yet.",
        "opinion": "This is an opinion, not a factual claim, so it can't be fact-checked.",
    }[verdict]
