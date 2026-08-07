"""Deterministic URL/domain handling. tldextract runs offline (no fetch)."""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import tldextract

# suffix_list_urls=() disables network refresh so tests are deterministic.
_extract = tldextract.TLDExtract(suffix_list_urls=())

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_eid", "ref")


def _with_scheme(text):
    if "://" in text:
        return text
    return "https://" + text


def detect_input_kind(text):
    """Classify a single input as a company name or a URL."""
    t = text.strip()
    if t.startswith("http://") or t.startswith("https://"):
        return "url"
    if any(ch.isspace() for ch in t) or "." not in t:
        return "name"
    head = t.split("/")[0].split(":")[0].split("?")[0]
    # A leading-dot token (".NET", ".com") is a bare suffix, not a host — treat
    # it as a name so a product search is not rejected as a bad URL.
    if head.startswith("."):
        return "name"
    ext = _extract(head)
    # A dotted, space-free token ending in a known public suffix is treated as
    # a URL even if an interior label is malformed (e.g. `example..com`, empty
    # domain); parse_homepage_input then rejects it at the API boundary.
    return "url" if ext.suffix else "name"


def registrable_domain(host_or_url):
    """Return the public-suffix registrable domain, or None."""
    ext = _extract(_with_scheme(host_or_url))
    if not (ext.domain and ext.suffix):
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def canonicalize_url_for_dedupe(url):
    """Lowercase host, drop www/fragment/tracking params, trim slash."""
    parts = urlsplit(_with_scheme(url))
    host = parts.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    return urlunsplit(("https", host.lower(), path, urlencode(query), ""))


def registrable_domain_matches(candidate_url, target_domain):
    """True if candidate's registrable domain equals target_domain.

    Subdomain-aware (news.acme.com matches acme.com). Use ONLY for own-domain /
    denylist checks, never for owned-profile matching on shared platforms.
    """
    cand = registrable_domain(candidate_url)
    return cand is not None and cand == target_domain.lower()


# Platforms whose account key is the FIRST path segment.
_SINGLE_SEG_PLATFORMS = {"x.com", "twitter.com", "github.com", "medium.com",
                         "substack.com", "facebook.com", "instagram.com",
                         "tiktok.com"}
# Platforms where the account key is the first TWO segments (prefix/slug).
_TWO_SEG_PREFIXES = {"linkedin.com": {"company", "in", "school"},
                     "youtube.com": {"channel", "c", "user"}}


def _account_key(url):
    """Platform-specific account key, or '' if none. Never a substring."""
    dom = registrable_domain(url)
    segs = [s for s in urlsplit(_with_scheme(url)).path.split("/") if s]
    if not segs:
        return ""
    if dom in _SINGLE_SEG_PLATFORMS:
        return f"{dom}:{segs[0].lower()}"
    if dom == "youtube.com" and segs[0].startswith("@"):
        return f"{dom}:{segs[0].lower()}"          # youtube.com/@handle
    prefixes = _TWO_SEG_PREFIXES.get(dom)
    if prefixes and len(segs) >= 2 and segs[0].lower() in prefixes:
        return f"{dom}:{segs[0].lower()}/{segs[1].lower()}"
    return ""


def owned_profile_match(candidate_url, profile_url_or_handle):
    """True only when candidate and reference resolve to the SAME platform
    account key (exact match; never substring/prefix; Codex impl points 9/10)."""
    cand = _account_key(candidate_url)
    if not cand:
        return False
    ref = profile_url_or_handle.strip()
    if "/" not in ref and "." not in ref:          # a bare handle
        handle = ref.lstrip("@").lower()
        return cand.endswith(f":{handle}") or cand.endswith(f"@{handle}")
    return _account_key(ref) == cand               # a full profile URL


def _is_valid_host(host):
    """Reject empty/edge labels; require a resolvable registrable domain."""
    if not host or host.startswith(".") or host.endswith("."):
        return False
    labels = host.split(".")
    if any(not lab or len(lab) > 63 for lab in labels):  # empty label = '..'
        return False
    if any(not all(c.isalnum() or c == "-" for c in lab) for lab in labels):
        return False
    return registrable_domain(host) is not None


def parse_homepage_input(text):
    """Normalize a URL-kind input to 'https://host', or None if invalid host."""
    host = (urlsplit(_with_scheme(text.strip())).hostname or "").lower()
    return f"https://{host}" if _is_valid_host(host) else None
