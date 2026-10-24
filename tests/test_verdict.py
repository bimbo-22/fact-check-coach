import pytest

from app.verdict import Evidence, decide, outlet_votes

SUP, CON, NM = "supports", "contradicts", "not_mentioned"


def art(outlet, stance):
    return Evidence(outlet, stance)


def cr(outlet, stance, rating=None):
    """A published fact-check, already labelled (and quote-verified) against OUR claim."""
    return Evidence(outlet, stance, is_claimreview=True, rating=rating)


def test_three_articles_from_one_outlet_count_once():
    r = decide([art("reuters", CON)] * 3)
    assert (r.c, r.C) == (1, 1)
    assert r.verdict == "unverified"


def test_outlet_tie_is_not_mentioned():
    votes = outlet_votes([art("bbc", SUP), art("bbc", CON)])
    assert votes[0].stance == NM


def test_single_claimreview_alone_is_enough():
    assert decide([cr("snopes", CON)]).verdict == "false"
    assert decide([cr("snopes", SUP)]).verdict == "true"


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


def test_claimreview_not_about_our_claim_falls_back_to_articles():
    r = decide([cr("snopes", NM, rating="False"), art("ap", CON)])
    assert r.verdict == "unverified"


def test_rating_never_decides_direction():
    # Reuters rated "5G makes you sick" False; our claim is the debunk, so the verified stance is supports.
    r = decide([cr("reuters", SUP, rating="False"), art("ap", SUP)])
    assert r.verdict == "true"


def test_claimreview_overrides_the_same_outlets_articles():
    votes = outlet_votes([cr("reuters", CON), art("reuters", SUP), art("reuters", SUP)])
    assert (votes[0].stance, votes[0].weight) == (CON, 2)


def test_strong_win_with_some_opposition_is_false_medium():
    # c = 2 (CR) + 1 + 1 = 4, s = 2 (CR) → c ≥ 3 and c ≥ 2s
    r = decide([cr("reuters", CON), art("ap", CON), art("bbc", CON), cr("snopes", SUP)])
    assert (r.verdict, r.confidence) == ("false", "medium")


def test_true_rule_mirrors_false():
    assert decide([art("ap", SUP), art("bbc", SUP)]).verdict == "true"
    assert decide([art("ap", SUP), art("bbc", SUP), art("afp", SUP), art("reuters", CON)]).verdict == "true"


@pytest.mark.parametrize("evidence,confidence", [
    # high: ≥4 weighted, no opposition, ≥2 outlets
    ([cr("reuters", CON), art("ap", CON), art("afp", CON)], "high"),
    # 4 weighted but only from 2 ClaimReviews of... still 2 outlets → high
    ([cr("reuters", CON), cr("snopes", CON)], "high"),
    # medium: ≥3 weighted
    ([cr("reuters", CON), art("ap", CON)], "medium"),
    # medium: exactly 2 with no opposition (single ClaimReview)
    ([cr("reuters", CON)], "medium"),
])
def test_confidence_levels(evidence, confidence):
    r = decide(evidence)
    assert r.verdict == "false"
    assert r.confidence == confidence


def test_misleading_medium_with_lots_of_split_evidence():
    r = decide([cr("reuters", CON), art("ap", CON), cr("snopes", SUP)])  # c=3, s=2
    assert (r.verdict, r.confidence) == ("misleading", "medium")


def test_no_evidence_is_unverified_low():
    r = decide([])
    assert (r.verdict, r.confidence) == ("unverified", "low")
