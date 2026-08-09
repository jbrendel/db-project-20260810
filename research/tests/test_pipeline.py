import pytest
from unittest.mock import patch
from research import pipeline
from research.exclusion import ExclusionSet


def _es():
    return ExclusionSet("acme.com", [], [], set())


def test_pipeline_filters_own_domain_and_summarizes(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "0")
    monkeypatch.setenv("MAX_ITEMS_PER_CATEGORY", "10")
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "1")
    search_items = [
        {"title": "A", "url": "https://acme.com/x", "source": "acme.com",
         "published_at": None, "snippet": "s"},
        {"title": "B", "url": "https://news.com/y", "source": "news.com",
         "published_at": None, "snippet": "s"},
    ]
    curator_out = {"content": '{"accepted": [{"url": "https://news.com/y"}],'
                   '"rejected": [], "duplicates": [], "tool_call": null,'
                   '"done": true}', "tool_calls": [], "usage": None}
    planner_out = {"content": '{"queries": ["acme news"]}',
                   "tool_calls": [], "usage": None}
    summary_out = {"content": '{"summary": "About Acme."}',
                   "tool_calls": [], "usage": None}
    with patch.object(pipeline, "tavily_search", return_value=search_items), \
         patch.object(pipeline, "call_llm",
                      side_effect=[planner_out, curator_out, summary_out]):
        result = pipeline.research_category("Acme", "news", 36, _es())
    urls = [i["url"] for i in result["items"]]
    assert "https://acme.com/x" not in urls   # own domain removed pre-curator
    assert "https://news.com/y" in urls
    assert result["summary"] == "About Acme."


def test_pipeline_empty_yields_no_summary(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "0")
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "1")
    planner_out = {"content": '{"queries": ["acme news"]}',
                   "tool_calls": [], "usage": None}
    curator_out = {"content": '{"accepted": [], "rejected": [],'
                   '"duplicates": [], "tool_call": null, "done": true}',
                   "tool_calls": [], "usage": None}
    with patch.object(pipeline, "tavily_search", return_value=[]), \
         patch.object(pipeline, "call_llm",
                      side_effect=[planner_out, curator_out]):
        result = pipeline.research_category("Acme", "news", 36, _es())
    assert result["items"] == []
    assert result["summary"] is None  # no CATEGORY_SUMMARY call when empty


def test_query_planner_cap(monkeypatch):
    monkeypatch.setenv("QUERY_PLANNER_MAX_QUERIES", "2")
    out = {"content": '{"queries": ["a", "b", "c", "d"]}',
           "tool_calls": [], "usage": None}
    with patch.object(pipeline, "call_llm", return_value=out):
        queries = pipeline._plan_queries("Acme", "news")
    assert queries == ["a", "b"]


def test_planner_prompt_targets_third_party_and_excludes_own_domain():
    captured = {}

    def fake(name, messages, **kw):
        captured["prompt"] = messages[0]["content"]
        captured["kw"] = kw
        return {"content": '{"queries": ["x"]}', "tool_calls": [],
                "usage": None}

    with patch.object(pipeline, "call_llm", side_effect=fake):
        pipeline._plan_queries("Google", "blog_posts", domain="google.com",
                               run_id=7)
    prompt = captured["prompt"]
    assert "THIRD-PARTY" in prompt
    assert "INDEPENDENT" in prompt
    assert "google.com" in prompt  # own-domain exclusion hint
    assert "not the company's own blog" in prompt.lower()
    # LLM log correlation now flows through (was missing before).
    assert captured["kw"]["run_id"] == 7
    assert captured["kw"]["category_key"] == "blog_posts"


def test_score_sentiments_attaches(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "https://n.com/a", "source": "n.com",
              "published_at": None, "snippet": "s"}]
    out = {"content": '{"score": 0.6, "label": "positive"}',
           "tool_calls": [], "usage": None}
    with patch.object(pipeline, "call_llm", return_value=out):
        pipeline.score_sentiments("Acme", items, run_id=1, category_key="news")
    assert items[0]["sentiment_score"] == 0.6
    assert items[0]["sentiment_label"] == "positive"


def test_score_sentiments_failure_is_nonfatal(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm", side_effect=RuntimeError("boom")):
        pipeline.score_sentiments("Acme", items)  # must NOT raise
    assert items[0]["sentiment_score"] is None
    assert items[0]["sentiment_label"] is None


def test_score_sentiments_reraises_soft_time_limit(monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm", side_effect=SoftTimeLimitExceeded()):
        with pytest.raises(SoftTimeLimitExceeded):  # must NOT be swallowed
            pipeline.score_sentiments("Acme", items)


def test_score_sentiments_disabled_makes_no_calls(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "0")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm") as llm:
        pipeline.score_sentiments("Acme", items)
    llm.assert_not_called()
    assert items[0]["sentiment_score"] is None


def test_score_sentiments_respects_cap(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    monkeypatch.setenv("SENTIMENT_MAX_ITEMS", "1")
    items = [{"title": f"t{i}", "url": f"u{i}", "source": "s",
              "published_at": None, "snippet": "s"} for i in range(3)]
    out = {"content": '{"score": 0.2, "label": "neutral"}',
           "tool_calls": [], "usage": None}
    with patch.object(pipeline, "call_llm", return_value=out) as llm:
        pipeline.score_sentiments("Acme", items)
    assert llm.call_count == 1                 # only the first item scored
    assert items[1]["sentiment_score"] is None  # beyond the cap -> unknown
