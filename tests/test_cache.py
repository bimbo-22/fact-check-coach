import dataclasses
import json
import logging

from app.cache import CheckStore, TTLCache
from tests.conftest import post


async def test_second_identical_check_is_a_cache_hit_without_llm_calls(pipeline):
    caption = post("false_5g")["caption"]
    first = await pipeline.run(caption)
    calls_after_first = pipeline.llm.total_calls
    second = await pipeline.run(caption)
    assert not first.cache_hit and second.cache_hit
    assert pipeline.llm.total_calls == calls_after_first
    assert pipeline.stats["cache_hits"] == 1
    assert second.evidence.verdict == first.evidence.verdict


async def test_different_post_same_claim_skips_search_and_stance(pipeline):
    await pipeline.run(post("false_5g")["caption"])
    stance_calls = pipeline.llm.calls["stance"]
    # Same caption with different emojis/hashtags normalises to the same post.
    await pipeline.run(post("false_5g")["caption"] + " 🔥🔥 #viral")
    assert pipeline.llm.calls["stance"] == stance_calls


def test_ttl_cache_expires():
    t = [0.0]
    c = TTLCache(10, clock=lambda: t[0])
    c.set("k", 1)
    assert c.get("k") == 1
    t[0] = 11
    assert c.get("k") is None


def test_check_store_states():
    t = [0.0]
    s = CheckStore(10, clock=lambda: t[0])
    s.put("a", "x")
    assert s.get("a") == ("ok", "x")
    t[0] = 10
    assert s.get("a") == ("expired", None)
    assert s.get("zzz") == ("missing", None)


async def test_privacy_nothing_stored_or_logged_contains_the_post(pipeline, client, caplog):
    caption = post("false_5g")["caption"]
    username = "wellness.truth.daily"
    with caplog.at_level(logging.DEBUG):
        start = client.post("/check/start", json={"text": caption, "client": "telegram"}).json()
        client.post("/check/reveal", json={"check_id": start["check_id"], "guess": "true"})
        client.post("/check/start", json={"url": post("false_5g")["url"]})

    stored = json.dumps(
        [dataclasses.asdict(v) for v in pipeline.claim_cache.values()]
        + pipeline.claim_cache.keys() + pipeline.input_cache.keys() + pipeline.input_cache.values(),
        default=str, ensure_ascii=False)
    logs = caplog.text
    for blob in (stored, logs):
        assert caption not in blob
        assert "Share before they delete this" not in blob
        assert username not in blob
    # The cache keys are hashes, not text.
    assert all(len(k) == 64 for k in pipeline.input_cache.keys())
