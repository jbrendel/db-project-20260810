"""Pure per-category research (no DB): planner -> search -> curator loop."""
import os
from research.llm import call_llm
from research.tavily import tavily_search
from research.exclusion import is_excluded
from research.urls_util import canonicalize_url_for_dedupe
from research import schemas


def _plan_queries(company, category_key):
    prompt = (f"Company: {company}. Category: {category_key}. Return JSON "
              '{"queries": [...]} of focused web search queries.')
    out = call_llm("QUERY_PLANNER",
                   [{"role": "user", "content": prompt}])
    max_q = int(os.environ.get("QUERY_PLANNER_MAX_QUERIES", "3"))
    return schemas.parse_query_planner(out["content"])[:max_q]


def _ingest(queries, lookback_months, exclusion, pool, seen):
    """Search each query; add unique (by canonical URL), non-excluded items to
    `pool`, capped at MAX_CANDIDATES_PER_CATEGORY. Used for BOTH the initial and
    the curator's follow-up searches, so both honor window/caps/exclusion
    (Codex impl point 3)."""
    per = int(os.environ.get("TAVILY_RESULTS_PER_SEARCH", "10"))
    cap = int(os.environ.get("MAX_CANDIDATES_PER_CATEGORY", "40"))
    for q in queries:
        for item in tavily_search(q, lookback_months, per):
            key = canonicalize_url_for_dedupe(item["url"])
            excluded, _ = is_excluded(item["url"], exclusion)
            if excluded or key in seen:
                continue
            seen.add(key)
            pool.append(item)
            if len(pool) >= cap:
                return pool
    return pool


def _curator_prompt(company, category_key, pool):
    """Bounded curator prompt: caps the candidate list handed to the LLM."""
    cap = int(os.environ.get("MAX_CANDIDATES_PER_CATEGORY", "40"))
    snip = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    lines = [f"- {i['url']} :: {i['title']} :: {i['snippet'][:snip]}"
             for i in pool[:cap]]
    body = "\n".join(lines)
    return (
        f'Company: "{company}". Category: {category_key}. From the candidate '
        "URLs below, keep only genuine third-party content about the company; "
        "drop the company's own channels, aggregators, review/ecommerce pages, "
        "and off-topic results; dedupe. You MAY request one more search by "
        'returning a tool_call {"query": "..."}. Return JSON '
        '{"accepted": [{"url": ...}], "rejected": [{"url", "reason_code"}], '
        '"duplicates": [{"url", "duplicate_of"}], "tool_call": {...}|null, '
        f'"done": bool}}.\n{body}')


def _curate(company, category_key, pool, seen, lookback_months, exclusion):
    """Bounded curator: judge, optionally search more, return accepted items.

    Follow-up searches go through _ingest, so they honor the run's window, the
    result cap, and deterministic exclusion — never a hard-coded 36/10 (Codex
    impl point 3). `accepted` carries urls only; item metadata stays from Tavily.
    """
    max_iter = int(os.environ.get("CURATOR_MAX_ITERATIONS", "3"))
    max_search = int(os.environ.get("CURATOR_MAX_SEARCHES", "5"))
    accepted_urls, searches = [], 0
    for _ in range(max_iter):
        prompt = _curator_prompt(company, category_key, pool)
        out = call_llm("CURATOR", [{"role": "user", "content": prompt}])
        data = schemas.parse_curator(out["content"])
        accepted_urls = [a["url"] for a in data["accepted"]]
        if data["done"] or not data["tool_call"] or searches >= max_search:
            break
        searches += 1
        _ingest([data["tool_call"]["query"]], lookback_months, exclusion,
                pool, seen)
    by_url = {i["url"]: i for i in pool}
    return [by_url[u] for u in accepted_urls if u in by_url]


def _summary_prompt(company, category_key, items):
    snip = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    lines = [f"- {i['title']} :: {i['snippet'][:snip]}" for i in items]
    body = "\n".join(lines)
    return (f'Summarise, in one paragraph, third-party {category_key} coverage '
            f'of "{company}" from these items. Return JSON '
            f'{{"summary": "..."}}.\n{body}')


def _summarize(company, category_key, items):
    prompt = _summary_prompt(company, category_key, items)
    out = call_llm("CATEGORY_SUMMARY",
                   [{"role": "user", "content": prompt}])
    return schemas.parse_category_summary(out["content"])


def research_category(company, category_key, lookback_months, exclusion):
    """Return {'items': [...], 'summary': str|None} for one category."""
    queries = _plan_queries(company, category_key)
    pool, seen = [], set()
    _ingest(queries, lookback_months, exclusion, pool, seen)
    accepted = _curate(company, category_key, pool, seen,
                       lookback_months, exclusion)
    max_items = int(os.environ.get("MAX_ITEMS_PER_CATEGORY", "20"))
    items = accepted[:max_items]
    summary = _summarize(company, category_key, items) if items else None
    return {"items": items, "summary": summary}
