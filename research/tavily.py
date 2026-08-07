"""Tavily search wrapper: the single mock seam for search (Section 9)."""
import os
from datetime import datetime, timedelta, timezone
from research import urls_util


def _raw_search(query, days, max_results):
    from tavily import TavilyClient  # lazy, per-process
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    # topic="news" is required for Tavily's day-window to apply; see the note
    # below on the known limitation for non-news categories.
    return client.search(query=query, max_results=max_results,
                         days=days, topic="news")


def _parse_date(value):
    if not value:
        return None
    try:  # tz-aware UTC so it stores cleanly under Django USE_TZ=True
        return datetime.fromisoformat(value[:10]).replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _within_window(published_at, lookback_months):
    if published_at is None:
        return True  # undated is kept: best-effort window (Section 9)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_months * 30)
    return published_at >= cutoff


def tavily_search(query, lookback_months, max_results):
    """Search, map, and post-filter by window (§9 layer 2). Undated kept."""
    days = lookback_months * 30
    max_snippet = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    raw = _raw_search(query, days, max_results)
    items = []
    for r in raw["results"]:
        url = r["url"]
        published = _parse_date(r.get("published_date"))
        if not _within_window(published, lookback_months):
            continue  # drop dated-but-out-of-window results
        items.append({
            "title": r["title"],
            "url": url,
            "source": urls_util.registrable_domain(url) or "",
            "published_at": published,
            "snippet": (r.get("content") or "")[:max_snippet],
        })
    return items
