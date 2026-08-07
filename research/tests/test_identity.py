import pytest
from unittest.mock import patch
from research.models import Run
from research import identity

pytestmark = pytest.mark.django_db


def test_url_input_derives_domain_without_llm():
    run = Run.objects.create(input_text="https://acme.com/x",
                             input_kind="url")
    with patch.object(identity, "call_llm") as llm:
        domain, profiles, handles = identity.resolve_identity(run)
    assert domain == "acme.com"
    llm.assert_not_called()


def test_name_input_uses_llm_and_no_match_returns_none():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    out = {"content": '{"matched": false, "official_domain": null,'
           '"confidence": "low", "owned_profile_urls": [],'
           '"owned_social_handles": []}',
           "tool_calls": [], "usage": None}
    with patch.object(identity, "tavily_search", return_value=[]), \
         patch.object(identity, "call_llm", return_value=out):
        domain, profiles, handles = identity.resolve_identity(run)
    assert domain is None


def test_name_input_match_returns_registrable_domain_and_channels():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    out = {"content": '{"matched": true,'
           '"official_domain": "https://www.acme.com/",'
           '"confidence": "high",'
           '"owned_profile_urls": ["https://linkedin.com/company/acme"],'
           '"owned_social_handles": ["@acmehq"]}',
           "tool_calls": [], "usage": None}
    with patch.object(identity, "tavily_search", return_value=[]), \
         patch.object(identity, "call_llm", return_value=out):
        domain, profiles, handles = identity.resolve_identity(run)
    assert domain == "acme.com"
    assert profiles == ["https://linkedin.com/company/acme"]
    assert handles == ["@acmehq"]
