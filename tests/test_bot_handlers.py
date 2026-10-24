from bot.telegram_bot import agreement_text, format_reveal, format_start
from tests.conftest import post


def reveal_payload(client, caption, guess="true"):
    start = client.post("/check/start", json={"text": caption, "client": "telegram"}).json()
    return client.post("/check/reveal", json={"check_id": start["check_id"], "guess": guess}).json()


def test_format_reveal_false_claim(client):
    out = format_reveal(reveal_payload(client, post("false_5g")["caption"]))
    assert "❌ <b>False</b>" in out
    from app.outlets import all_outlets
    assert f"4 of {len(all_outlets())} outlets checked cover it; all 4 say it's false." in out
    assert "💡 <b>Tip:</b>" in out
    assert "didn't match the source and was thrown out" in out
    assert out.count("• <a href=") <= 3


def test_at_most_three_sources_no_outlet_repeated():
    payload = {
        "verdict": "false", "confidence": "high", "explanation": "x", "guess_feedback": None,
        "agreement": {"supports": 0, "contradicts": 4, "not_mentioned": 2, "outlets_checked": 6, "rejected_quotes": 0},
        "sources": [{"outlet": o, "url": f"https://{o}.com/a", "stance": "contradicts", "quote": "q"}
                    for o in ["Reuters", "Reuters", "AP", "AFP", "Snopes"]],
        "tip": "t", "disclaimer": "d",
    }
    out = format_reveal(payload)
    assert out.count("• <a href=") == 3
    assert out.count(">Reuters</a>") == 1


def test_html_is_escaped():
    out = format_start({"claim": "<script>alert(1)</script>", "question": "Who & why?"})
    assert "<script>" not in out and "&lt;script&gt;" in out and "Who &amp; why?" in out


def test_opinion_reveal_has_no_agreement_line(client):
    out = format_reveal(reveal_payload(client, post("opinion_pizza")["caption"]))
    assert "💬 <b>Opinion</b>" in out and "📊" not in out


def test_agreement_text_variants():
    base = {"outlets_checked": 6}
    assert agreement_text("developing", {**base, "supports": 0, "contradicts": 0}) == \
        "None of the 6 outlets we checked cover it yet."
    assert agreement_text("misleading", {**base, "supports": 1, "contradicts": 2}) == \
        "3 of 6 outlets checked cover it: 2 say it's false, 1 says it's true."
    assert agreement_text("true", {**base, "supports": 1, "contradicts": 0}) == \
        "1 of 6 outlets checked cover it; 1 says it's true."


def test_format_comments(client):
    from bot.telegram_bot import format_comments
    from tests.test_comments import COMMENTS
    out = format_comments(client.post("/comments/check", json={"text": COMMENTS}).json())
    assert "🚩 <b>1 spreads misinformation</b>" in out
    assert "✅ <b>1 is backed by the sources</b>" in out
    assert "Opinion: can't be fact-checked" in out and "💡 <b>Tip:</b>" in out


def test_format_comments_empty_note():
    from bot.telegram_bot import format_comments
    assert format_comments({"comments": [], "note": "Paste <them>"}) == "Paste &lt;them&gt;"


def test_format_reveal_shows_whats_actually_true(client):
    out = format_reveal(reveal_payload(client, post("false_5g")["caption"]))
    assert "✅ <b>What's actually true:</b>" in out and "<a href=" in out


def test_opinion_reply_coaches_instead_of_a_dead_end():
    from bot.telegram_bot import format_opinion
    out = format_opinion({"claim": "Pineapple on pizza is the worst", "read_text": "Pineapple on pizza is the worst!!!",
                          "red_flags": ["Built to shock: ALL CAPS"], "opinion_questions": ["What facts is this built on?"]})
    assert "📝 <b>I read:</b>" in out and "This is an opinion" in out and "🚩" in out and "Worth asking yourself" in out


def test_start_message_shows_what_was_read():
    out = format_start({"claim": "5G makes you sick", "question": "Who posted this?", "read_text": "BREAKING 5G makes you sick"})
    assert out.startswith("📝 <b>I read:</b>")
