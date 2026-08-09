"""Pure per-category research (no DB): planner -> search -> curator loop."""
import logging
import os
from celery.exceptions import SoftTimeLimitExceeded
from research.llm import call_llm, call_and_parse
from research.tavily import tavily_search
from research.exclusion import is_excluded
from research.urls_util import canonicalize_url_for_dedupe
from research import schemas
from research.schemas import MalformedLLMOutput

_log = logging.getLogger("drumbeat")

# What each category means as THIRD-PARTY coverage about the company. The
# planner must target independent sources, not the company's own channels —
# otherwise queries like "Google blog posts" return google's own blogs, which
# the curator then rejects wholesale (leaving the category empty).
CATEGORY_INTENT = {
    "news": "news articles from independent news outlets",
    "trade_publications": "coverage in trade and industry publications",
    "blog_posts": ("blog posts written by INDEPENDENT third parties "
                   "(bloggers, analysts, enthusiasts) — NOT the company's own "
                   "blog"),
    "press_releases": ("press releases about the company distributed on "
                       "newswire services (PR Newswire, Business Wire, etc.)"),
    "social_posts": "notable social-media posts about the company by others",
    "newsletters": "third-party newsletters that cover or mention the company",
    "podcasts": "podcast episodes that discuss the company",
    "reddit": "Reddit discussions about the company",
    "forums": "online-forum discussions about the company",
}


def _plan_queries(company, category_key, domain=None, run_id=None):
    intent = CATEGORY_INTENT.get(category_key, f"third-party {category_key}")
    max_q = int(os.environ.get("QUERY_PLANNER_MAX_QUERIES", "3"))
    exclude = (f'Do NOT target the company\'s own domain "{domain}" or its '
               "owned channels; those are excluded downstream. "
               if domain else "")
    prompt = (
        f'You are finding THIRD-PARTY content ABOUT the company "{company}", '
        "written by INDEPENDENT sources — not the company's own website, blog, "
        f"or social accounts. {exclude}Goal for this batch: {intent}. Generate "
        f"up to {max_q} focused web-search queries that surface independent, "
        f'third-party sources discussing "{company}" (pair the company name '
        "with review/analysis/commentary/coverage terms; avoid queries that "
        'would mainly return the company\'s own pages). Return JSON '
        '{"queries": [...]} — queries only, no commentary.')
    try:
        queries = call_and_parse(
            call_llm, "QUERY_PLANNER", [{"role": "user", "content": prompt}],
            schemas.parse_query_planner, run_id=run_id,
            category_key=category_key)
    except MalformedLLMOutput as exc:  # non-fatal: fall back to a basic query
        _log.warning("query planner failed for %s/%s: %s; using fallback",
                     company, category_key, exc)
        queries = [f"{company} {category_key.replace('_', ' ')}"]
    return queries[:max_q]


def _ingest(queries, lookback_months, exclusion, pool, seen):
    """Search each query; add unique (by canonical URL), non-excluded items to
    `pool`, capped at MAX_CANDIDATES_PER_CATEGORY. Used for BOTH the initial and
    the curator's follow-up searches, so both honor window/caps/exclusion
    (Codex impl point 3)."""
    per = int(os.environ.get("TAVILY_RESULTS_PER_SEARCH", "10"))
    cap = int(os.environ.get("MAX_CANDIDATES_PER_CATEGORY", "40"))
    for q in queries:
        for item in tavily_search(q, lookback_months, per):
            if len(pool) >= cap:  # guard first so the pool never exceeds cap
                return pool
            key = canonicalize_url_for_dedupe(item["url"])
            excluded, _ = is_excluded(item["url"], exclusion)
            if excluded or key in seen:
                continue
            seen.add(key)
            pool.append(item)
    return pool


def _curator_prompt(company, category_key, pool):
    """Bounded curator prompt: caps the candidate list handed to the LLM."""
    cap = int(os.environ.get("MAX_CANDIDATES_PER_CATEGORY", "40"))
    snip = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    lines = [f"- {i['url']} :: {i['title']} :: {i['snippet'][:snip]}"
             for i in pool[:cap]]
    body = "\n".join(lines)
    return (
        f'Company: "{company}". Category: {category_key}.\n'
        "Keep ONLY items genuinely ABOUT this company — where the company (its "
        "business, products, people, actions, or reputation) is the PRIMARY "
        "SUBJECT of the piece.\n"
        "KEEP: news, analysis, reviews, or commentary whose main subject is the "
        "company.\n"
        "DROP, even when the company's name appears in the title or text:\n"
        "- items where the company is only mentioned in passing, or is one of "
        "many named (listicles, market round-ups, \"best X of 2026\");\n"
        "- items the company merely AUTHORED, published, sponsored, funded, or "
        "is quoted in, whose actual subject is a different topic (e.g. a "
        "company-authored report about an industry trend is ABOUT that trend, "
        "NOT about the company);\n"
        "- the company's own channels, aggregators, review/ecommerce pages, and "
        "otherwise off-topic results.\n"
        "Dedupe. You MAY request one more search via a "
        'tool_call {"query": "..."}. Return ONLY compact JSON of accepted '
        'URLs, e.g. {"accepted": [{"url": "https://..."}], "tool_call": null, '
        '"done": true}. Do NOT echo rejected or duplicate URLs.\n'
        f"{body}")


def _curate(company, category_key, pool, seen, lookback_months, exclusion,
            run_id=None):
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
        try:
            data = call_and_parse(
                call_llm, "CURATOR", [{"role": "user", "content": prompt}],
                schemas.parse_curator, run_id=run_id, category_key=category_key)
        except MalformedLLMOutput as exc:
            # Non-fatal: keep the exclusion-filtered candidate pool rather than
            # failing the whole category (better to show unfiltered findings).
            _log.warning("curator failed for %s/%s: %s; keeping candidate pool",
                         company, category_key, exc)
            return list(pool)
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


def _summarize(company, category_key, items, run_id=None):
    prompt = _summary_prompt(company, category_key, items)
    try:
        return call_and_parse(
            call_llm, "CATEGORY_SUMMARY", [{"role": "user", "content": prompt}],
            schemas.parse_category_summary, run_id=run_id,
            category_key=category_key)
    except MalformedLLMOutput as exc:  # non-fatal: no summary, keep the items
        _log.warning("category summary failed for %s: %s", category_key, exc)
        return None


def _sentiment_prompt(company, item):
    cap = int(os.environ.get("SENTIMENT_MAX_CONTENT_CHARS", "1500"))
    text = (item.get("content") or item.get("snippet") or "")[:cap]
    return (
        f'Assess the sentiment toward "{company}" expressed by this item, from '
        "its FULL content below (headline AND body/comments) — NOT just the "
        "headline, which can read positive while the actual coverage or "
        "commenters are negative. Return JSON with: \"score\" (number from -1 "
        'very negative to 1 very positive), "label" '
        '("positive"|"neutral"|"negative"), and "summary" (one sentence that '
        "reflects the ACTUAL sentiment and why — e.g. note when commenters are "
        "negative despite a positive-sounding headline).\n"
        f'Title: {item["title"]}\nContent: {text}')


def score_sentiments(company, items, run_id=None, category_key=None):
    """Attach sentiment_score/label to each item (best-effort, non-fatal).

    One LLM call per item, bounded by SENTIMENT_MAX_ITEMS. A per-item failure or
    a disabled feature leaves that item's sentiment None; it never raises and
    never affects category status (§5.4).
    """
    enabled = os.environ.get("SENTIMENT_ENABLED", "1") != "0"
    cap = int(os.environ.get("SENTIMENT_MAX_ITEMS", "10"))
    for idx, item in enumerate(items):
        item["sentiment_score"] = None
        item["sentiment_label"] = None
        item["sentiment_summary"] = None
        if not enabled or idx >= cap:
            continue
        try:
            data = call_and_parse(
                call_llm, "SENTIMENT",
                [{"role": "user", "content": _sentiment_prompt(company, item)}],
                schemas.parse_sentiment, run_id=run_id,
                category_key=category_key)
            item["sentiment_score"] = data["score"]
            item["sentiment_label"] = data["label"]
            item["sentiment_summary"] = data["summary"]
        except SoftTimeLimitExceeded:
            # SoftTimeLimitExceeded IS an Exception; do NOT swallow it, or the
            # 180s soft limit is lost and the task grinds to the 210s hard
            # SIGKILL (stuck-blue). Let it propagate to the subtask boundary,
            # which marks the category red cleanly (§5.4/§5.5).
            raise
        except Exception as exc:  # non-fatal: unknown sentiment, keep the item
            _log.warning("sentiment scoring failed for %s: %s",
                         item.get("url"), exc)
    return items


def research_category(company, category_key, lookback_months, exclusion,
                      run_id=None):
    """Return {'items': [...], 'summary': str|None} for one category."""
    queries = _plan_queries(company, category_key,
                            domain=exclusion.resolved_domain, run_id=run_id)
    pool, seen = [], set()
    _ingest(queries, lookback_months, exclusion, pool, seen)
    accepted = _curate(company, category_key, pool, seen,
                       lookback_months, exclusion, run_id=run_id)
    max_items = int(os.environ.get("MAX_ITEMS_PER_CATEGORY", "20"))
    items = accepted[:max_items]
    score_sentiments(company, items, run_id=run_id, category_key=category_key)
    summary = _summarize(company, category_key, items,
                         run_id=run_id) if items else None
    return {"items": items, "summary": summary}
