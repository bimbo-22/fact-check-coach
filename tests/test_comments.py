import base64

from app.comments import parse_sorted
from tests.conftest import FIXTURES, ScriptedLLM

COMMENTS = (FIXTURES / "images" / "comments_5g.txt").read_text()
SCREENSHOT = base64.b64encode((FIXTURES / "images" / "comments_5g.png").read_bytes()).decode()


def by_text(resp, start):
    return next(c for c in resp["comments"] if c["text"].startswith(start))


def check_labels(resp):
    assert by_text(resp, "This is so scary")["kind"] == "opinion"
    assert by_text(resp, "Honestly 5G")["kind"] == "opinion"
    assert by_text(resp, "Is this real")["kind"] == "question"
    wrong = by_text(resp, "5G towers make people sick")
    assert wrong["verdict"] == "false" and wrong["label"].startswith("Misinformation")
    assert wrong["source"]["outlet"]
    debunk = by_text(resp, "Fake. Reuters")
    assert debunk["verdict"] == "true" and debunk["label"] == "Backed by the outlets we checked"
    s = resp["summary"]
    assert (s["opinions"], s["questions"], s["claims"], s["misinformation"], s["backed"]) == (2, 1, 2, 1, 1)
    assert "loudest comment" in resp["tip"]


def test_pasted_comments(client):
    check_labels(client.post("/comments/check", json={"text": COMMENTS}).json())


def test_screenshot_of_comments(client):
    check_labels(client.post("/comments/check", json={"image_base64": SCREENSHOT}).json())


def test_comments_need_input(client):
    assert client.post("/comments/check", json={"text": ""}).status_code == 422


async def test_claims_are_capped(pipeline):
    many = "\n".join(f"5G towers cause problem number {i}" for i in range(8))
    resp = await pipeline.check_comments(many)
    assert resp.summary.claims == 8
    assert resp.summary.unchecked_claims == 3


async def test_repeated_claim_uses_cache(pipeline):
    await pipeline.check_comments("5G towers make people sick")
    calls = pipeline.llm.calls["stance"]
    await pipeline.check_comments("5G towers make people sick\nwow")
    assert pipeline.llm.calls["stance"] == calls


async def test_unparseable_sort_gives_friendly_note(pipeline):
    pipeline.llm = ScriptedLLM(["nope", "still nope"])
    resp = await pipeline.check_comments("a comment")
    assert resp.comments == [] and "one comment per line" in resp.note


def test_parse_sorted_downgrades_claim_without_claim_text():
    items = parse_sorted('{"comments": [{"text": "x", "kind": "claim", "claim": null}, {"text": "y", "kind": "weird"}]}')
    assert [(i.kind, i.claim) for i in items] == [("other", None), ("other", None)]


def test_comment_verdict_inversion():
    from app.comments import comment_verdict
    assert comment_verdict("false", denies=True) == "true"     # rejecting a false claim = right
    assert comment_verdict("true", denies=True) == "false"     # rejecting a true claim = misinformation
    assert comment_verdict("unverified", denies=True) == "unverified"
    assert comment_verdict("false", denies=False) == "false"


def test_debunk_comment_is_checked_as_positive_claim_and_reuses_cache(client):
    client.post("/check", json={"text": "5G makes people sick"})
    resp = client.post("/comments/check", json={"text": COMMENTS}).json()
    debunk = by_text(resp, "Fake. Reuters")
    assert debunk["denies"] is True and "no evidence" not in debunk["claim"].lower()
