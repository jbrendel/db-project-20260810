from unittest.mock import patch
from research import pipeline
from research.exclusion import ExclusionSet


def _es():
    return ExclusionSet("acme.com", [], [], set())


def test_pipeline_filters_own_domain_and_summarizes(monkeypatch):
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
