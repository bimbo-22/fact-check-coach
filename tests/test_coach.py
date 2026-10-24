from datetime import date

import pytest

from app.coach import DEFAULT_QUESTION, guess_feedback, pick_question, pick_tip
from app.models import Agreement
from app.text import Signals, detect_signals

FALSE_4 = Agreement(contradicts=4, not_mentioned=2, outlets_checked=6)


def test_right_guess():
    assert guess_feedback("false", "false", FALSE_4).startswith("Nice, you got it")


def test_wrong_guess():
    assert guess_feedback("true", "false", FALSE_4) == \
        "You guessed true, but 4 of the 4 outlets that cover it say it's false."


def test_not_sure_on_clear_verdict():
    assert "Fair to be unsure" in guess_feedback("not_sure", "false", FALSE_4)


def test_not_sure_is_praised_when_unverified():
    a = Agreement(supports=1, not_mentioned=5, outlets_checked=6)
    assert guess_feedback("not_sure", "unverified", a).startswith("\"Not sure\" was the smart call")


def test_opinion_has_no_right_guess():
    assert "no right guess" in guess_feedback("true", "opinion", Agreement())


def test_misleading_feedback():
    a = Agreement(supports=1, contradicts=2, outlets_checked=6)
    assert "not that simple" in guess_feedback("true", "misleading", a)


@pytest.mark.parametrize("signals,start", [
    (Signals(old_date=True, old_year=2019), "Check the date: this is from 2019"),
    (Signals(image_mentioned=True), "Find the original"),
    (Signals(is_reel=True), "Reels cut out context"),
    (Signals(link_in_bio=True), "\"Link in bio\""),
    (Signals(emotional=True), "Notice how it makes you feel"),
    (Signals(many_hashtags=True, has_source_link=True), "Hashtags spread a post"),
    (Signals(), "Does it cite a source?"),
])
def test_tip_selection_by_signal(signals, start):
    assert pick_tip(signals, "false").startswith(start)


def test_verdict_specific_tips_win():
    assert pick_tip(Signals(link_in_bio=True), "developing").startswith("Breaking news")
    assert pick_tip(Signals(), "opinion").startswith("Opinions")


def test_question_selection():
    assert "Reel" in pick_question(Signals(is_reel=True))
    assert "link in bio" in pick_question(Signals(link_in_bio=True))
    assert pick_question(Signals()) == DEFAULT_QUESTION


def test_detect_signals_from_instagram_caption():
    s = detect_signals("😱 SHOCKING!!! 5G is DANGEROUS. Link in bio #a #b #c #d", today=date(2026, 10, 24))
    assert s.link_in_bio and s.emotional and s.many_hashtags and not s.has_source_link


def test_detect_old_post_date():
    s = detect_signals("text", post_date=date(2019, 3, 3), today=date(2026, 10, 24))
    assert s.old_date and s.old_year == 2019
