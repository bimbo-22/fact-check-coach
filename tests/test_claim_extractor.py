import json

from app.claim_extractor import extract_claim, parse_extraction
from app.llm.mock import MockLLM
from tests.conftest import FIXTURES, ScriptedLLM

VALID = json.dumps({"claim": "5G towers make people sick.", "checkable": True,
                    "breaking_news": False, "language": "en"})


async def test_valid_json_parsed():
    ext = await extract_claim(ScriptedLLM([VALID]), "post")
    assert ext.ok and ext.claim == "5G towers make people sick." and ext.checkable


async def test_json_inside_code_fence_parsed():
    ext = await extract_claim(ScriptedLLM([f"```json\n{VALID}\n```"]), "post")
    assert ext.ok


async def test_malformed_json_retries_once_then_succeeds():
    llm = ScriptedLLM(["{oops", VALID])
    ext = await extract_claim(llm, "post")
    assert ext.ok and llm.calls["extract_claim"] == 2


async def test_malformed_twice_falls_back():
    llm = ScriptedLLM(["{oops", "nope"])
    ext = await extract_claim(llm, "post")
    assert not ext.ok and llm.calls["extract_claim"] == 2


def test_missing_fields_rejected():
    assert parse_extraction('{"claim": "x"}') is None
    assert parse_extraction('{"claim": "", "checkable": true}') is None
    assert parse_extraction('{"claim": "x", "checkable": "yes"}') is None


async def test_opinion_text_is_not_checkable_with_mock_rules():
    ext = await extract_claim(MockLLM(FIXTURES), "I think cats are the best pets ever")
    assert ext.checkable is False


async def test_breaking_detected_with_mock_rules():
    ext = await extract_claim(MockLLM(FIXTURES), "BREAKING: a bridge collapsed in Oslo just now")
    assert ext.breaking_news is True
