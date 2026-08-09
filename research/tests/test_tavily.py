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


def test_url_date_extraction():
    assert tavily._url_date("https://nypost.com/2026/02/18/business/x") == \
        datetime(2026, 2, 18, tzinfo=timezone.utc)
    assert tavily._url_date("https://forbes.com/sites/x/2026/06/09/apple") == \
        datetime(2026, 6, 9, tzinfo=timezone.utc)
    assert tavily._url_date("https://site.com/2026/03/story") == \
        datetime(2026, 3, 1, tzinfo=timezone.utc)  # month only -> day 1
    # An id-like number is not a date (month out of range) -> None.
    assert tavily._url_date("https://theverge.com/tech/944110/wwdc") is None
    assert tavily._url_date("https://x.com/2026/13/bad") is None  # bad month
    assert tavily._url_date("https://x.com/about") is None


def test_url_date_used_when_tavily_date_missing(monkeypatch):
    raw = {"results": [{"title": "T",
           "url": "https://n.com/2026/02/18/apple-story", "content": "c"}]}
    with patch.object(tavily, "_raw_search", return_value=raw), \
         patch.object(tavily, "_within_window", return_value=True):
        items = tavily.tavily_search("q", 36, 10)
    assert items[0]["published_at"] == \
        datetime(2026, 2, 18, tzinfo=timezone.utc)


def test_time_buckets():
    # <=12 months -> a single recent bucket.
    assert tavily._time_buckets(6) == [(180, 0)]
    assert tavily._time_buckets(12) == [(360, 0)]
    # >12 months -> recent-12 bucket + one older bucket (≈2x cost).
    assert tavily._time_buckets(36) == [(365, 0), (1080, 365)]
    assert tavily._time_buckets(24) == [(365, 0), (720, 365)]


def test_long_lookback_makes_two_searches_and_dedupes(monkeypatch):
    # Two disjoint buckets return two DIFFERENT items; a URL appearing in both
    # is deduped. Assert _raw_search is called once per bucket.
    calls = []

    def fake_raw(query, start_days, end_days, max_results):
        calls.append((start_days, end_days))
        if end_days == 0:  # recent bucket
            return {"results": [{"title": "recent", "url": "https://x.com/r",
                    "content": "c", "published_date": "2026-06-01"},
                    {"title": "dup", "url": "https://x.com/d", "content": "c",
                     "published_date": "2026-05-01"}]}
        return {"results": [{"title": "old", "url": "https://x.com/o",
                "content": "c", "published_date": "2024-06-01"},
                {"title": "dup", "url": "https://x.com/d", "content": "c",
                 "published_date": "2024-05-01"}]}  # same url as recent bucket

    with patch.object(tavily, "_raw_search", side_effect=fake_raw), \
         patch.object(tavily, "_within_window", return_value=True):
        items = tavily.tavily_search("q", 36, 10)
    assert len(calls) == 2                      # one search per bucket
    urls = sorted(i["url"] for i in items)
    assert urls == ["https://x.com/d", "https://x.com/o", "https://x.com/r"]
