from research.exclusion import ExclusionSet, is_excluded


def _es(**kw):
    base = dict(resolved_domain="acme.com", owned_profile_urls=[],
                owned_handles=[], allow_borderline_domains=set())
    base.update(kw)
    return ExclusionSet(**base)


def test_own_domain_excluded():
    ok, reason = is_excluded("https://news.acme.com/x", _es())
    assert ok and reason == "own_domain"


def test_denylist_excluded():
    ok, reason = is_excluded("https://www.g2.com/products/acme", _es())
    assert ok and reason == "denylist"


def test_reddit_excluded_by_default():
    ok, reason = is_excluded("https://reddit.com/r/acme", _es())
    assert ok and reason == "denylist"


def test_reddit_allowed_when_opted_in():
    es = _es(allow_borderline_domains={"reddit.com"})
    ok, _ = is_excluded("https://reddit.com/r/acme", es)
    assert not ok


def test_owned_handle_excluded():
    es = _es(owned_handles=["@acmehq"])
    ok, reason = is_excluded("https://x.com/acmehq/status/1", es)
    assert ok and reason == "own_profile"


def test_owned_profile_url_excluded():
    es = _es(owned_profile_urls=["https://linkedin.com/company/acme"])
    ok, reason = is_excluded("https://linkedin.com/company/acme/about", es)
    assert ok and reason == "own_profile"


def test_third_party_article_not_excluded():
    ok, reason = is_excluded("https://techcrunch.com/acme", _es())
    assert not ok and reason == ""


def test_no_resolved_domain_still_applies_denylist():
    es = _es(resolved_domain=None)
    ok, reason = is_excluded("https://g2.com/x", es)
    assert ok and reason == "denylist"
