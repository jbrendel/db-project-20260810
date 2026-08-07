"""Fail-loud validation of required environment variables."""
import os
from django.core.exceptions import ImproperlyConfigured

REQUIRED_VARS = [
    "DEFAULT_LLM_URL",
    "DEFAULT_LLM_API_KEY",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_TOKENS",
    "DEFAULT_LLM_TEMP",
    "TAVILY_API_KEY",
    "REDIS_URL",  # required at runtime; no localhost:6379 fallback (§14)
]


def validate_required_env():
    """Raise ImproperlyConfigured if any required env var is missing."""
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise ImproperlyConfigured(
            "Missing required env vars: " + ", ".join(sorted(missing))
        )
    return None
