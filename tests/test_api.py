from tests.conftest import post


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "mock" and body["search_provider"] == "mock"


def test_sources_lists_all_outlets_with_bias_labels(client):
    from app.outlets import all_outlets
    body = client.get("/sources").json()
    assert len(body["outlets"]) == len(all_outlets()) >= 6
    assert all(o["bias_label"] and o["bias_source"] for o in body["outlets"])
    assert "bias_checked" in body


def test_start_never_contains_a_verdict(client):
    r = client.post("/check/start", json={"text": post("false_5g")["caption"], "client": "telegram"})
    body = r.json()
    assert r.status_code == 200
    assert body["check_id"] and body["question"] and body["checkable"] is True
    for leak in ("verdict", "confidence", "sources", "agreement", "explanation"):
        assert leak not in body
    assert "false" not in body["question"].lower()


def test_start_then_reveal(client):
    start = client.post("/check/start", json={"text": post("false_5g")["caption"]}).json()
    r = client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "true"})
    body = r.json()
    assert r.status_code == 200
    assert body["verdict"] == "false"
    assert body["guess_feedback"] == "You guessed true, but 4 of the 4 outlets that cover it say it's false."
    assert body["disclaimer"]
    assert body["agreement"]["rejected_quotes"] == 1


def test_reveal_unknown_check_is_404(client):
    r = client.post("/check/reveal", json={"check_id": "nope", "guess": "true"})
    assert r.status_code == 404


def test_reveal_expired_check_is_410(client):
    start = client.post("/check/start", json={"text": post("false_5g")["caption"]}).json()
    store = client.app.state.checks
    now = store.clock()
    store.clock = lambda: now + store.ttl + 1
    r = client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "true"})
    assert r.status_code == 410


def test_one_shot_check(client):
    body = client.post("/check", json={"text": post("true_eiffel")["caption"]}).json()
    assert body["verdict"] == "true"
    assert body["guess_feedback"] is None


def test_long_input_is_truncated_not_rejected(client):
    r = client.post("/check", json={"text": "Pineapple on pizza is the worst. " * 200})
    assert r.status_code == 200


def test_empty_text_is_422(client):
    assert client.post("/check/start", json={"text": ""}).status_code == 422
    assert client.post("/check/start", json={"text": "   "}).status_code == 422


def test_opinion_start_has_no_question(client):
    body = client.post("/check/start", json={"text": post("opinion_pizza")["caption"]}).json()
    assert body["checkable"] is False and body["question"] is None and body["note"]


def test_instagram_link_that_cannot_be_read_needs_text(client):
    body = client.post("/check/start", json={"url": "https://www.instagram.com/p/BLOCKED999/"}).json()
    assert body["needs_text"] is True and body["check_id"] is None


def test_instagram_link_plus_pasted_caption_works(client):
    body = client.post("/check/start", json={"url": "https://www.instagram.com/p/BLOCKED999/",
                                             "text": post("false_5g")["caption"]}).json()
    assert body["checkable"] is True and body["check_id"]


def test_cors_allows_the_extension(client):
    r = client.options("/check/start", headers={"Origin": "chrome-extension://abcdef",
                                                "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "chrome-extension://abcdef"
