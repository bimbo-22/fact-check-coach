import json
from pathlib import Path

import pytest

from app.outlets import all_outlets, load_sources, outlet_for_url

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("url,expected", [
    ("https://www.reuters.com/fact-check/x/", "reuters"),
    ("https://reuters.com/world/x", "reuters"),
    ("https://apnews.com/article/x", "ap"),
    ("https://factcheck.afp.com/x", "afp"),
    ("https://www.bbc.co.uk/news/x", "bbc"),
    ("https://www.bbc.com/news/x", "bbc"),
    ("https://news.bbc.co.uk/x", "bbc"),
    ("https://www.snopes.com/fact-check/x/", "snopes"),
    ("https://www.politifact.com/factchecks/x/", "politifact"),
])
def test_accepts_whitelisted(url, expected):
    assert outlet_for_url(url).id == expected


@pytest.mark.parametrize("url", [
    "https://reuters.com.evil.io/fact-check/x",
    "https://notsnopes.com/x",
    "https://snopes.com-fake.net/x",
    "https://afp.com/x",  # only the English fact-check site is listed
    "https://dailytruth-news.example/5g",
    "ftp://reuters.com/x",
    "reuters.com/x",
    "",
])
def test_rejects_lookalikes(url):
    assert outlet_for_url(url) is None


def test_sources_yaml_has_exactly_six_complete_outlets():
    bias_checked, outlets = load_sources()
    assert len(outlets) == 6
    assert bias_checked
    for o in outlets:
        assert o.id and o.name and o.domains and o.type and o.bias_label and o.bias_source
        assert o.bias_status in ("confirmed", "unconfirmed") and o.bias_note


def test_every_fixture_source_but_the_decoy_is_whitelisted():
    for f in (FIXTURES / "sources").glob("*.json"):
        src = json.loads(f.read_text())
        if f.stem.startswith("nonwhitelisted"):
            assert outlet_for_url(src["url"]) is None
        else:
            assert outlet_for_url(src["url"]) is not None, f.name


def test_outlet_ids_unique():
    ids = [o.id for o in all_outlets()]
    assert len(ids) == len(set(ids))
