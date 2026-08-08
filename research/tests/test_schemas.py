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
