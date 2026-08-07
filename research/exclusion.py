"""Deterministic own-channel and denylist exclusion (runs before CURATOR)."""
from dataclasses import dataclass
from research import urls_util
from research.categories import DENYLIST_DOMAINS


@dataclass
class ExclusionSet:
    resolved_domain: str | None
    owned_profile_urls: list[str]
    owned_handles: list[str]
    allow_borderline_domains: set[str]


def is_excluded(url, exclusion):
    """Return (is_excluded, reason_code) for a candidate URL."""
    if exclusion.resolved_domain and urls_util.registrable_domain_matches(
        url, exclusion.resolved_domain
    ):
        return True, "own_domain"
    for owned in (exclusion.owned_profile_urls + exclusion.owned_handles):
        if urls_util.owned_profile_match(url, owned):  # platform+path aware
            return True, "own_profile"
    dom = urls_util.registrable_domain(url)
    if dom and dom in DENYLIST_DOMAINS:
        if dom not in exclusion.allow_borderline_domains:
            return True, "denylist"
    return False, ""
