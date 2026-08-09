from datetime import datetime, timezone
from unittest.mock import patch
from research import tavily


def test_maps_and_truncates(monkeypatch):
    monkeypatch.setenv("MAX_SNIPPET_CHARS", "5")
    raw = {"results": [{"title": "T", "url": "https://x.com/a",
           "content": "abcdefgh", "published_date": "2025-01-02"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert items[0]["snippet"] == "abcde"
    assert items[0]["published_at"] == datetime(2025, 1, 2,
                                                tzinfo=timezone.utc)
    assert items[0]["source"] == "x.com"


def test_missing_date_is_none_and_kept(monkeypatch):
    raw = {"results": [{"title": "T", "url": "https://x.com/a",
           "content": "c"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert len(items) == 1 and items[0]["published_at"] is None


def test_out_of_window_dated_item_dropped():
    raw = {"results": [{"title": "old", "url": "https://x.com/a",
           "content": "c", "published_date": "2010-01-01"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert items == []  # dated, older than the window -> dropped (§9 layer 2)


def test_unsafe_scheme_dropped():
    raw = {"results": [
        {"title": "bad", "url": "javascript:alert(1)", "content": "c"},
        {"title": "ok", "url": "https://x.com/a", "content": "c"},
    ]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert [i["url"] for i in items] == ["https://x.com/a"]


def test_unparseable_date_treated_as_undated(monkeypatch):
    raw = {"results": [{"title": "T", "url": "https://x.com/a",
           "content": "c", "published_date": "not-a-date"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert len(items) == 1 and items[0]["published_at"] is None


def test_parse_date_handles_rfc2822_and_iso():
    # Tavily returns RFC 2822; ISO must still work. Time-independent.
    assert tavily._parse_date("Thu, 12 Feb 2026 21:57:14 GMT") == \
        datetime(2026, 2, 12, 21, 57, 14, tzinfo=timezone.utc)
    assert tavily._parse_date("2026-02-12") == \
        datetime(2026, 2, 12, tzinfo=timezone.utc)
    assert tavily._parse_date("") is None
    assert tavily._parse_date("garbage") is None


def test_rfc2822_date_from_tavily_is_dated(monkeypatch):
    # Regression: real Tavily dates (RFC 2822) were parsed to None, leaving
    # every item undated. A recent RFC 2822 date must survive within the window.
    raw = {"results": [{"title": "T", "url": "https://x.com/a", "content": "c",
           "published_date": "Thu, 12 Feb 2026 21:57:14 GMT"}]}
    with patch.object(tavily, "_raw_search", return_value=raw), \
         patch.object(tavily, "_within_window", return_value=True):
        items = tavily.tavily_search("q", 36, 10)
    assert items[0]["published_at"] == \
        datetime(2026, 2, 12, 21, 57, 14, tzinfo=timezone.utc)
