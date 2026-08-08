from research import urls_util as u


def test_detect_input_kind():
    assert u.detect_input_kind("Acme Corp") == "name"
    assert u.detect_input_kind("https://acme.com") == "url"
    assert u.detect_input_kind("acme.com") == "url"
    assert u.detect_input_kind("acme.com/about") == "url"
    assert u.detect_input_kind("acme.com:8080") == "url"
    assert u.detect_input_kind("just a phrase") == "name"
    assert u.detect_input_kind("google.com/about") == "url"
    # No dot -> name (even without spaces).
    assert u.detect_input_kind("Acme") == "name"
    # A leading-dot bare suffix is a product name, not a URL.
    assert u.detect_input_kind(".NET") == "name"
    assert u.detect_input_kind(".com") == "name"
    # A malformed interior label still classifies as URL (rejected downstream).
    assert u.detect_input_kind("example..com") == "url"


def test_registrable_domain():
    assert u.registrable_domain("https://blog.acme.co.uk/x") == "acme.co.uk"
    assert u.registrable_domain("acme.com") == "acme.com"
    assert u.registrable_domain("not a domain") is None


def test_canonicalize_strips_tracking_and_fragment():
    a = u.canonicalize_url_for_dedupe("https://A.com/p/?utm_source=x#frag")
    b = u.canonicalize_url_for_dedupe("http://www.a.com/p")
    assert a == b


def test_canonicalize_keeps_meaningful_query():
    out = u.canonicalize_url_for_dedupe("https://a.com/p?id=7&utm_medium=x")
    assert "id=7" in out
    assert "utm_medium" not in out


def test_canonicalize_idn_and_percent_encoding():
    # IDN host is lowercased consistently; a percent-encoded path is preserved.
    one = u.canonicalize_url_for_dedupe("https://Bücher.example/Path%20A")
    two = u.canonicalize_url_for_dedupe("http://bücher.example/Path%20A/")
    assert one == two


def test_registrable_domain_matches_subdomain_not_suffix_trick():
    assert u.registrable_domain_matches("https://news.acme.com/x", "acme.com")
    assert not u.registrable_domain_matches(
        "https://acme.com.evil.test/x", "acme.com")


def test_owned_profile_match_is_platform_and_path_aware():
    assert u.owned_profile_match("https://x.com/acmehq/status/1", "@acmehq")
    # third-party article merely mentioning the handle in the path is NOT a match
    assert not u.owned_profile_match(
        "https://techcrunch.com/2025/acmehq-raises", "@acmehq")
    # linkedin uses a two-segment account key (company/<slug>)
    assert u.owned_profile_match(
        "https://linkedin.com/company/acme/about",
        "https://linkedin.com/company/acme")
    # path-prefix false positive guarded
    assert not u.owned_profile_match(
        "https://linkedin.com/company/acme-competitor",
        "https://linkedin.com/company/acme")
    # youtube @handle form
    assert u.owned_profile_match(
        "https://youtube.com/@acme/videos", "https://youtube.com/@acme")


def test_is_safe_http_url():
    assert u.is_safe_http_url("https://acme.com/a")
    assert u.is_safe_http_url("http://acme.com")
    assert not u.is_safe_http_url("javascript:alert(1)")
    assert not u.is_safe_http_url("data:text/html,<script>")
    assert not u.is_safe_http_url("file:///etc/passwd")
    assert not u.is_safe_http_url("//evil.com/x")  # protocol-relative
    assert not u.is_safe_http_url("mailto:x@y.com")
    assert not u.is_safe_http_url("https://")  # no hostname
    assert not u.is_safe_http_url(None)


def test_extract_uses_no_disk_cache():
    # Regression (Codex code-review 1, finding 1): URL handling must be fully
    # offline and never write to the user's (possibly read-only) home cache.
    # A disabled DiskCache performs no filesystem reads or writes.
    assert u._extract._cache.enabled is False


def test_parse_homepage_input_edges():
    assert u.parse_homepage_input("acme.com") == "https://acme.com"
    assert u.parse_homepage_input("https://blog.acme.com/x") == \
        "https://blog.acme.com"
    for bad in ("https://", "http://", "https://?x=1", "example..com",
                ".com", "example.com.", "exa mple.com"):
        assert u.parse_homepage_input(bad) is None
