import pytest
from research.schemas import (parse_query_planner, parse_report,
                              parse_category_summary, parse_curator,
                              parse_identity, MalformedLLMOutput)


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


def test_parse_report_array_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_report('{"executive_overview": ["a"]}')


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


def test_parse_curator_missing_done_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_curator('{"accepted": [], "rejected": [], "duplicates": []}')


def test_parse_curator_tolerates_missing_rejected_duplicates():
    # rejected/duplicates are unused, so a compact response omitting them is OK.
    data = parse_curator('{"accepted": [{"url": "u"}], "done": true}')
    assert data["accepted"][0]["url"] == "u"
    assert data["rejected"] == [] and data["duplicates"] == []


def test_parse_curator_accepted_without_url_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_curator('{"accepted": [{"title": "x"}], "rejected": [],'
                      '"duplicates": [], "done": true}')


def test_parse_curator_done_must_be_bool():
    with pytest.raises(MalformedLLMOutput):
        parse_curator('{"accepted": [], "rejected": [], "duplicates": [],'
                      '"done": "yes"}')


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


def test_parse_identity_missing_matched_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_identity('{"official_domain": "acme.com",'
                       '"confidence": "high", "owned_profile_urls": [],'
                       '"owned_social_handles": []}')


def test_parse_identity_bad_confidence_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_identity('{"official_domain": "acme.com", "matched": true,'
                       '"confidence": "certain", "owned_profile_urls": [],'
                       '"owned_social_handles": []}')


def test_parse_identity_matched_true_requires_domain():
    with pytest.raises(MalformedLLMOutput):
        parse_identity('{"official_domain": null, "matched": true,'
                       '"confidence": "high", "owned_profile_urls": [],'
                       '"owned_social_handles": []}')
