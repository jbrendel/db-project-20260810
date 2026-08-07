"""Category keys, display ordering, and the exclusion denylist."""

CORE_CATEGORIES = [
    "news",
    "trade_publications",
    "blog_posts",
    "press_releases",
    "social_posts",
    "newsletters",
    "podcasts",
]

BORDERLINE_CATEGORIES = ["reddit", "forums"]

DISPLAY_ORDER = {
    key: i for i, key in enumerate(CORE_CATEGORIES + BORDERLINE_CATEGORIES)
}

DENYLIST_DOMAINS = {
    "g2.com", "capterra.com", "amazon.com", "crunchbase.com",
    "trustpilot.com", "getapp.com",
    "reddit.com",  # borderline: excluded unless the reddit checkbox opts in
}

# Borderline checkbox -> the domains it admits when ticked (§19).
BORDERLINE_DOMAIN_MAP = {"reddit": {"reddit.com"}, "forums": set()}


def selected_category_keys(borderline_options):
    """Return core keys plus any ticked, known borderline keys, in order."""
    keys = list(CORE_CATEGORIES)
    for key, ticked in borderline_options.items():
        if key not in BORDERLINE_CATEGORIES:
            raise KeyError(f"Unknown borderline category: {key}")
        if ticked:
            keys.append(key)
    return sorted(keys, key=lambda k: DISPLAY_ORDER[k])
