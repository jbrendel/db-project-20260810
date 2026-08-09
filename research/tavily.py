"""Tavily search wrapper: the single mock seam for search (Section 9)."""
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from research import urls_util


_RECENT_WINDOW_DAYS = 365  # "most recent 12 months" bucket boundary


def _raw_search(query, start_days, end_days, max_results):
    """One Tavily news search over [today-start_days, today-end_days].

    topic="news" is the only topic that returns publish dates, and an explicit
    start/end window (not `days`) is what actually reaches back years.
    """
    from tavily import TavilyClient  # lazy, per-process
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=start_days)
    end = today - timedelta(days=end_days)
    # include_raw_content pulls the full page text (incl. comment sections), so
    # sentiment reflects the body, not just a positive-sounding headline.
    return client.search(query=query, max_results=max_results, topic="news",
                         start_date=start.isoformat(),
                         end_date=end.isoformat(), include_raw_content=True)


def _time_buckets(lookback_months):
    """Split the lookback into search windows (start_days, end_days from today).

    Tavily ranks news by relevance, which crowds out older articles when one
    wide window is searched. To surface older coverage we search the recent 12
    months as one bucket and, if the lookback reaches further back, the whole
    remaining range (12 months .. lookback) as a second bucket. So <=12-month
    lookbacks make ONE search; longer ones make TWO (≈2x cost, not per-year).
    """
    total_days = lookback_months * 30
    if total_days <= _RECENT_WINDOW_DAYS:
        return [(total_days, 0)]
    return [(_RECENT_WINDOW_DAYS, 0), (total_days, _RECENT_WINDOW_DAYS)]


# A date embedded in a URL path, e.g. /2026/02/18/ or /2026-02-18 or /2026/02/.
_URL_DATE_RE = re.compile(r"/(20\d{2})[/-](\d{1,2})(?:[/-](\d{1,2}))?(?=[/?.]|$)")


def _url_date(url):
    """Extract a publish date from a URL path, or None. Conservative: requires
    a /YYYY/MM(/DD)? shape with a valid month/day (avoids matching id numbers).
    """
    m = _URL_DATE_RE.search(url or "")
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else 1
    if not (1 <= month <= 12):
        return None
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:  # e.g. day out of range for the month
        return None


def _parse_date(value):
    """Parse a Tavily publish date to a tz-aware UTC datetime, or None.

    Tavily returns RFC 2822 ("Thu, 12 Feb 2026 21:57:14 GMT"); some sources /
    older paths use ISO ("2026-02-12"). Try RFC 2822 first, then an ISO
    date-prefix. Result is normalised to tz-aware UTC (Django USE_TZ=True).
    """
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)  # RFC 2822 (Tavily's format)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value[:10])  # ISO date prefix
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _within_window(published_at, lookback_months):
    if published_at is None:
        return True  # undated is kept: best-effort window (Section 9)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_months * 30)
    return published_at >= cutoff


def tavily_search(query, lookback_months, max_results):
    """Search each time bucket, map, and post-filter by window (§9 layer 2).

    A long lookback searches a recent-12-months bucket AND an older bucket so
    Tavily's recency-ranking does not crowd out older articles. Results are
    deduped by canonical URL across buckets. Undated items are kept.
    """
    max_snippet = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    max_content = int(os.environ.get("SENTIMENT_MAX_CONTENT_CHARS", "1500"))
    items, seen = [], set()
    for start_days, end_days in _time_buckets(lookback_months):
        raw = _raw_search(query, start_days, end_days, max_results)
        for r in raw["results"]:
            url = r["url"]
            if not urls_util.is_safe_http_url(url):
                continue  # drop non-http(s) (javascript:/data:/file: etc.)
            key = urls_util.canonicalize_url_for_dedupe(url)
            if key in seen:
                continue  # same article surfaced in both buckets
            # Prefer Tavily's date; fall back to a date embedded in the URL so
            # the item can still land on the sentiment timeline where possible.
            published = _parse_date(r.get("published_date")) or _url_date(url)
            if not _within_window(published, lookback_months):
                continue  # drop dated-but-out-of-window results
            seen.add(key)
            full = r.get("raw_content") or r.get("content") or ""
            items.append({
                "title": r["title"],
                "url": url,
                "source": urls_util.registrable_domain(url) or "",
                "published_at": published,
                "snippet": (r.get("content") or "")[:max_snippet],
                # Fuller text for sentiment scoring only (not persisted).
                "content": full[:max_content],
            })
    return items
