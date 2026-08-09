import pytest
from research.schemas import (parse_query_planner, parse_report,
                              parse_category_summary, parse_curator,
                              parse_identity, parse_sentiment,
                              MalformedLLMOutput)


def test_parse_query_planner_ok():
    assert parse_query_planner('{"queries": ["a", "b"]}') == ["a", "b"]


def test_parse_query_planner_strips_code_fence():
    raw = "```json\n{\"queries\": [\"a\"]}\n```"
    assert parse_query_planner(raw) == ["a"]


def test_parse_query_planner_malformed_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_query_planner("not json")


def test_parse_query_planner_non_string_items_raise():
    with pytest.raises(MalformedLLMOutput):
        parse_query_planner('{"queries": [1, 2]}')


def test_parse_report_ok():
    assert parse_report('{"executive_overview": "hi"}') == "hi"


def test_parse_report_null_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_report('{"executive_overview": null}')


def test_parse_report_missing_key_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_report('{"something_else": "x"}')


def test_parse_report_coerces_structured_overview():
    # A model may return the overview as a nested object (e.g. positive/negative
    # sections). Flatten it to prose instead of failing the whole report.
    raw = ('{"executive_overview": {"summary": "Overall solid.",'
           '"positive": "Praise from TechCrunch.",'
           '"negative": "Concerns in Reuters."}}')
    out = parse_report(raw)
    assert "Overall solid." in out
    assert "Positive: Praise from TechCrunch." in out
    assert "Negative: Concerns in Reuters." in out


def test_parse_report_coerces_list_overview():
    out = parse_report('{"executive_overview": ["Para one.", "Para two."]}')
    assert "Para one." in out and "Para two." in out


def test_parse_report_bounded(monkeypatch):
    monkeypatch.setenv("REPORT_MAX_CHARS", "3")
    assert parse_report('{"executive_overview": "abcdef"}') == "abc"


def test_parse_category_summary_ok():
    assert parse_category_summary('{"summary": "s"}') == "s"


def test_parse_curator_ok():
    data = parse_curator('{"accepted": [{"url": "u"}], "rejected": [],'
                         '"duplicates": [], "tool_call": null, "done": true}')
    assert data["done"] is True
    assert data["accepted"][0]["url"] == "u"


def test_parse_curator_missing_done_is_salvaged():
    # Real failure: model omitted `done`. Salvage accepted, infer done=True
    # (no follow-up search requested) instead of failing the whole category.
    data = parse_curator('{"accepted": [{"url": "u"}], "rejected": [],'
                         '"duplicates": []}')
    assert data["accepted"][0]["url"] == "u"
    assert data["done"] is True


def test_parse_curator_missing_done_with_tool_call_continues():
    data = parse_curator('{"accepted": [], "tool_call": {"query": "more"}}')
    assert data["done"] is False  # a real follow-up search keeps the loop going


def test_parse_curator_tolerates_missing_rejected_duplicates():
    # rejected/duplicates are unused, so a compact response omitting them is OK.
    data = parse_curator('{"accepted": [{"url": "u"}], "done": true}')
    assert data["accepted"][0]["url"] == "u"
    assert data["rejected"] == [] and data["duplicates"] == []


def test_parse_curator_drops_accepted_entries_without_url():
    # An entry lacking a string url is dropped, not fatal.
    data = parse_curator('{"accepted": [{"title": "x"}, {"url": "keep"}],'
                         '"done": true}')
    assert [a["url"] for a in data["accepted"]] == ["keep"]


def test_parse_curator_non_bool_done_inferred():
    data = parse_curator('{"accepted": [], "done": "yes"}')
    assert data["done"] is True  # invalid done, no tool_call -> stop


def test_parse_curator_non_json_still_fails():
    with pytest.raises(MalformedLLMOutput):
        parse_curator("not json")


def test_parse_curator_defaults_tool_call():
    data = parse_curator('{"accepted": [], "rejected": [], "duplicates": [],'
                         '"done": true}')
    assert data["tool_call"] is None


def test_parse_identity_ok():
    data = parse_identity('{"official_domain": "acme.com", "matched": true,'
                          '"confidence": "high", "owned_profile_urls": [],'
                          '"owned_social_handles": []}')
    assert data["official_domain"] == "acme.com"


def test_parse_identity_no_match_null_domain_ok():
    data = parse_identity('{"official_domain": null, "matched": false,'
                          '"confidence": "low", "owned_profile_urls": [],'
                          '"owned_social_handles": []}')
    assert data["matched"] is False and data["official_domain"] is None


def test_parse_identity_derives_matched_when_missing():
    # No `matched` key but a usable domain -> matched derived True.
    data = parse_identity('{"official_domain": "acme.com",'
                          '"owned_profile_urls": [], '
                          '"owned_social_handles": []}')
    assert data["matched"] is True and data["official_domain"] == "acme.com"


def test_parse_identity_numeric_confidence_salvaged():
    # Real OpenRouter output: confidence as a number. Salvage the domain.
    data = parse_identity('{"official_domain": "apple.com", "matched": true,'
                          '"confidence": 0.9, "owned_profile_urls": [],'
                          '"owned_social_handles": []}')
    assert data["official_domain"] == "apple.com"
    assert data["matched"] is True
    assert data["confidence"] == "high"


def test_parse_identity_array_matched_salvaged():
    # Real OpenRouter output: `matched` returned as an evidence array. The
    # domain is still salvaged and matched is derived from it.
    data = parse_identity('{"official_domain": "google.com",'
                          '"confidence": 0.85, "owned_profile_urls": [],'
                          '"owned_social_handles": [],'
                          '"matched": ["https://blog.google/x"]}')
    assert data["official_domain"] == "google.com"
    assert data["matched"] is True


def test_parse_identity_matched_true_but_null_domain_is_no_match():
    data = parse_identity('{"official_domain": null, "matched": true,'
                          '"confidence": "high", "owned_profile_urls": [],'
                          '"owned_social_handles": []}')
    assert data["matched"] is False  # cannot match without a domain


def test_parse_identity_non_json_still_fails():
    with pytest.raises(MalformedLLMOutput):
        parse_identity("not json at all")


def test_parse_sentiment_ok():
    d = parse_sentiment('{"score": 0.5, "label": "positive"}')
    assert d["score"] == 0.5 and d["label"] == "positive"


def test_parse_sentiment_clamps_score():
    assert parse_sentiment('{"score": 2.5, "label": "positive"}')["score"] == 1.0
    assert parse_sentiment('{"score": -9, "label": "negative"}')["score"] == -1.0


def test_parse_sentiment_derives_label_from_score():
    assert parse_sentiment('{"score": 0.4}')["label"] == "positive"
    assert parse_sentiment('{"score": -0.4}')["label"] == "negative"
    assert parse_sentiment('{"score": 0.0}')["label"] == "neutral"


def test_parse_sentiment_bad_label_is_derived():
    assert parse_sentiment('{"score": 0.4, "label": "great"}')["label"] \
        == "positive"


def test_parse_sentiment_unusable_score_is_unknown():
    d = parse_sentiment('{"score": "n/a", "label": "positive"}')
    assert d["score"] is None and d["label"] is None


def test_parse_sentiment_bool_score_is_unknown():
    d = parse_sentiment('{"score": true, "label": "positive"}')
    assert d["score"] is None and d["label"] is None


def test_parse_sentiment_non_json_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_sentiment("not json")


def test_parse_sentiment_non_object_json_is_unknown():
    # Valid JSON that is not an object (e.g. a bare number/array) -> unknown,
    # not an AttributeError.
    unknown = {"score": None, "label": None, "summary": None}
    assert parse_sentiment("5") == unknown
    assert parse_sentiment("[1, 2]") == unknown


def test_parse_sentiment_summary():
    d = parse_sentiment('{"score": -0.6, "label": "negative",'
                        '"summary": "Commenters are angry despite the title."}')
    assert d["summary"] == "Commenters are angry despite the title."


def test_parse_sentiment_summary_bounded(monkeypatch):
    monkeypatch.setenv("SENTIMENT_SUMMARY_MAX_CHARS", "4")
    d = parse_sentiment('{"score": 0.1, "summary": "abcdefgh"}')
    assert d["summary"] == "abcd"


def test_parse_sentiment_missing_summary_is_none():
    d = parse_sentiment('{"score": 0.5, "label": "positive"}')
    assert d["summary"] is None
