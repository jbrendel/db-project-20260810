from unittest.mock import patch
from research import pipeline
from research.exclusion import ExclusionSet


def test_curator_stops_at_iteration_cap(monkeypatch):
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "2")
    monkeypatch.setenv("CURATOR_MAX_SEARCHES", "5")
    # Curator never says done, always requests one more search.
    tool_turn = {"content": '{"accepted": [], "rejected": [],'
                 '"duplicates": [], "tool_call": {"query": "more"},'
                 '"done": false}', "tool_calls": [], "usage": None}
    es = ExclusionSet(None, [], [], set())
    with patch.object(pipeline, "call_llm", return_value=tool_turn), \
         patch.object(pipeline, "tavily_search", return_value=[]) as srch:
        items = pipeline._curate("Acme", "news", [], set(), 36, es)
    assert items == []
    assert srch.call_count <= 2  # bounded by iterations


def test_curator_honors_done(monkeypatch):
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "5")
    pool = [{"title": "A", "url": "https://n.com/y", "source": "n.com",
             "published_at": None, "snippet": "s"}]
    done_turn = {"content": '{"accepted": [{"url": "https://n.com/y"}],'
                 '"rejected": [], "duplicates": [], "tool_call": null,'
                 '"done": true}', "tool_calls": [], "usage": None}
    es = ExclusionSet(None, [], [], set())
    with patch.object(pipeline, "call_llm", return_value=done_turn) as llm, \
         patch.object(pipeline, "tavily_search", return_value=[]):
        items = pipeline._curate("Acme", "news", pool, set(), 36, es)
    assert [i["url"] for i in items] == ["https://n.com/y"]
    assert llm.call_count == 1  # stopped immediately on done


def test_curator_search_cap(monkeypatch):
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "10")
    monkeypatch.setenv("CURATOR_MAX_SEARCHES", "2")
    tool_turn = {"content": '{"accepted": [], "rejected": [],'
                 '"duplicates": [], "tool_call": {"query": "more"},'
                 '"done": false}', "tool_calls": [], "usage": None}
    es = ExclusionSet(None, [], [], set())
    with patch.object(pipeline, "call_llm", return_value=tool_turn), \
         patch.object(pipeline, "tavily_search", return_value=[]) as srch:
        pipeline._curate("Acme", "news", [], set(), 36, es)
    assert srch.call_count <= 2  # bounded by CURATOR_MAX_SEARCHES


def test_curator_prompt_caps_candidates(monkeypatch):
    monkeypatch.setenv("MAX_CANDIDATES_PER_CATEGORY", "2")
    pool = [{"title": f"T{i}", "url": f"https://n.com/{i}", "source": "n.com",
             "published_at": None, "snippet": "s"} for i in range(5)]
    prompt = pipeline._curator_prompt("Acme", "news", pool)
    assert prompt.count("https://n.com/") == 2  # only 2 candidate lines


def test_curator_prompt_enforces_aboutness():
    prompt = pipeline._curator_prompt("Acme", "news", [])
    assert "PRIMARY SUBJECT" in prompt
    assert "one of many" in prompt          # listicle / round-up rejection
    assert "AUTHORED" in prompt             # company-authored-report rejection
    assert "different topic" in prompt


def test_summary_prompt_bounds_snippet(monkeypatch):
    monkeypatch.setenv("MAX_SNIPPET_CHARS", "3")
    items = [{"title": "T", "url": "u", "source": "s",
              "published_at": None, "snippet": "abcdefgh"}]
    prompt = pipeline._summary_prompt("Acme", "news", items)
    assert "abc" in prompt and "abcdefgh" not in prompt
