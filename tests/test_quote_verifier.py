from app.quote_verifier import quote_in_text, verify_label

TEXT = """Health agencies say 5G radio waves are far below levels that could harm people,
and   claims that 5G makes people sick are false. The WHO agrees."""


def test_exact_match_passes():
    assert quote_in_text("claims that 5G makes people sick are false", TEXT)


def test_whitespace_and_case_differences_pass():
    assert quote_in_text("HEALTH AGENCIES say 5G radio waves are far below levels that could harm people, and claims",
                         TEXT)


def test_curly_quotes_and_dashes_normalised():
    assert quote_in_text("It’s a claim — and it’s false", "it's a claim - and it's false, says the report")


def test_fabricated_quote_rejected_and_stance_downgraded():
    stance, quote, rejected = verify_label("supports", "Experts confirmed 5G towers cause illness in residents.", TEXT)
    assert (stance, quote, rejected) == ("not_mentioned", None, True)


def test_near_miss_below_threshold_rejected():
    # Same shape, but the meaning has been flipped by changed words.
    assert not quote_in_text("claims that 5G makes people healthy are definitely true", TEXT)


def test_tiny_quote_rejected():
    assert not quote_in_text("5G", TEXT)


def test_missing_quote_with_a_stance_is_rejected():
    assert verify_label("contradicts", None, TEXT)[2] is True


def test_not_mentioned_passes_through_without_counting():
    assert verify_label("not_mentioned", None, TEXT) == ("not_mentioned", None, False)


def test_real_label_kept():
    stance, quote, rejected = verify_label("contradicts", "claims that 5G makes people sick are false", TEXT)
    assert (stance, rejected) == ("contradicts", False)
