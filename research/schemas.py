"""Strict parsers for structured LLM output (plans/INITIAL.md Section 6.1)."""
import json
import os


class MalformedLLMOutput(Exception):
    """Raised when a call-point's output does not match its schema."""


def _load(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedLLMOutput(str(exc)) from exc


def parse_query_planner(content):
    data = _load(content)
    queries = data["queries"]  # fail loud if key absent
    if not isinstance(queries, list) or not all(
        isinstance(q, str) for q in queries
    ):
        raise MalformedLLMOutput("queries must be a list of strings")
    return queries


def _bounded_str(value, env_var, default):
    if not isinstance(value, str):  # null/array/object must fail loud (§6.1)
        raise MalformedLLMOutput(
            f"expected string, got {type(value).__name__}")
    return value[: int(os.environ.get(env_var, default))]


def parse_report(content):
    return _bounded_str(_load(content)["executive_overview"],
                        "REPORT_MAX_CHARS", "4000")


def parse_category_summary(content):
    return _bounded_str(_load(content)["summary"], "SUMMARY_MAX_CHARS", "1200")


def _require_url_list(value, label):
    if not isinstance(value, list) or not all(
        isinstance(x, dict) and isinstance(x.get("url"), str) for x in value
    ):
        raise MalformedLLMOutput(f"{label} must be a list of {{url: str}}")
    return value


def parse_curator(content):
    data = _load(content)
    for key in ("accepted", "rejected", "duplicates", "done"):
        if key not in data:
            raise MalformedLLMOutput(f"curator missing key: {key}")
    if not isinstance(data["done"], bool):
        raise MalformedLLMOutput("done must be bool")
    _require_url_list(data["accepted"], "accepted")  # accepted is [{url}] only
    data.setdefault("tool_call", None)
    return data


def parse_identity(content):
    data = _load(content)
    for key in ("official_domain", "owned_profile_urls",
                "owned_social_handles", "confidence", "matched"):
        if key not in data:  # all documented keys required (§6.1)
            raise MalformedLLMOutput(f"identity missing key: {key}")
    if not isinstance(data["matched"], bool):
        raise MalformedLLMOutput("matched must be bool")
    if data["confidence"] not in ("high", "medium", "low"):
        raise MalformedLLMOutput("confidence must be high/medium/low")
    for k in ("owned_profile_urls", "owned_social_handles"):
        if not isinstance(data[k], list):
            raise MalformedLLMOutput(f"{k} must be a list")
    dom = data["official_domain"]
    if data["matched"] and not isinstance(dom, str):
        raise MalformedLLMOutput("matched=true requires a string domain")
    if dom is not None and not isinstance(dom, str):
        raise MalformedLLMOutput("official_domain must be str or null")
    return data
