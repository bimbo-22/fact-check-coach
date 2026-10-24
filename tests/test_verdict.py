import pytest

from app.verdict import Evidence, decide, outlet_votes, rating_to_stance

SUP, CON, NM = "supports", "contradicts", "not_mentioned"


def art(outlet, stance):
    return Evidence(outlet, stance)


def cr(outlet, rating):
    return Evidence(outlet, NM, is_claimreview=True, rating=rating)


def test_three_articles_from_one_outlet_count_once():
    r = decide([art("reuters", CON)] * 3)
    assert (r.c, r.C) == (1, 1)
    assert r.verdict == "unverified"


def test_outlet_tie_is_not_mentioned():
    votes = outlet_votes([art("bbc", SUP), art("bbc", CON)])
    assert votes[0].stance == NM


def test_single_claimreview_alone_is_enough():
    assert decide([cr("snopes", "False")]).verdict == "false"
    assert decide([cr("snopes", "True")]).verdict == "true"


def test_single_plain_article_is_unverified():
    assert decide([art("ap", CON)]).verdict == "unverified"


def test_two_contradict_none_support_is_false():
    r = decide([art("ap", CON), art("bbc", CON)])
    assert (r.verdict, r.confidence) == ("false", "medium")


def test_two_contradict_one_supports_is_misleading():
    r = decide([art("ap", CON), art("bbc", CON), art("afp", SUP)])
    assert (r.verdict, r.confidence) == ("misleading", "low")


def test_one_each_is_unverified():
    assert decide([art("ap", CON), art("bbc", SUP)]).verdict == "unverified"


def test_breaking_news_with_one_outlet_is_developing():
    assert decide([art("ap", CON)], breaking_news=True).verdict == "developing"
    assert decide([], breaking_news=True).verdict == "developing"


def test_breaking_news_with_two_outlets_gets_a_real_verdict():
    assert decide([art("ap", CON), art("bbc", CON)], breaking_news=True).verdict == "false"


def test_unknown_claimreview_rating_is_ignored():
    # "Mixture" isn't in the map, so the outlet falls back to its articles (none mention it).
    r = decide([cr("snopes", "Mixture"), art("ap", CON)])
    assert r.verdict == "unverified"
    assert rating_to_stance("Half True") is None


def test_claimreview_overrides_the_same_outlets_articles():
    votes = outlet_votes([cr("reuters", "False"), art("reuters", SUP), art("reuters", SUP)])
    assert (votes[0].stance, votes[0].weight) == (CON, 2)


@pytest.mark.parametrize("rating,stance", [
    ("False", CON), ("Pants on Fire!", CON), ("FAKE", CON), ("Mostly False", CON),
    ("True", SUP), ("Correct.", SUP), ("Mostly True", SUP),
])
def test_rating_map(rating, stance):
    assert rating_to_stance(rating) == stance


def test_strong_win_with_some_opposition_is_false_medium():
    # c = 2 (CR) + 1 + 1 = 4, s = 2 (CR) → c ≥ 3 and c ≥ 2s
    r = decide([cr("reuters", "False"), art("ap", CON), art("bbc", CON), cr("snopes", "True")])
    assert (r.verdict, r.confidence) == ("false", "medium")


def test_true_rule_mirrors_false():
    assert decide([art("ap", SUP), art("bbc", SUP)]).verdict == "true"
    assert decide([art("ap", SUP), art("bbc", SUP), art("afp", SUP), art("reuters", CON)]).verdict == "true"


@pytest.mark.parametrize("evidence,confidence", [
    # high: ≥4 weighted, no opposition, ≥2 outlets
    ([cr("reuters", "False"), art("ap", CON), art("afp", CON)], "high"),
    # 4 weighted but only from 2 ClaimReviews of... still 2 outlets → high
    ([cr("reuters", "False"), cr("snopes", "False")], "high"),
    # medium: ≥3 weighted
    ([cr("reuters", "False"), art("ap", CON)], "medium"),
    # medium: exactly 2 with no opposition (single ClaimReview)
    ([cr("reuters", "False")], "medium"),
])
def test_confidence_levels(evidence, confidence):
    r = decide(evidence)
    assert r.verdict == "false"
    assert r.confidence == confidence


def test_misleading_medium_with_lots_of_split_evidence():
    r = decide([cr("reuters", "False"), art("ap", CON), cr("snopes", "True")])  # c=3, s=2
    assert (r.verdict, r.confidence) == ("misleading", "medium")


def test_no_evidence_is_unverified_low():
    r = decide([])
    assert (r.verdict, r.confidence) == ("unverified", "low")
