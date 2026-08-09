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


def _flatten_report_text(value):
    """Coerce a report overview (str | dict | list) into readable prose.

    The overview is display text; when a model returns a structured object
    (e.g. separate positive/negative sections) we flatten it into labelled
    paragraphs rather than failing the whole report (mirrors the tolerant
    IDENTITY handling, §6.1). None -> "" so an empty overview still fails loud.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            text = _flatten_report_text(val).strip()
            if text:
                label = str(key).replace("_", " ").strip().capitalize()
                parts.append(f"{label}: {text}")
        return "\n\n".join(parts)
    if isinstance(value, list):
        return "\n\n".join(
            t for t in (_flatten_report_text(v) for v in value) if t.strip())
    return str(value)


def parse_report(content):
    data = _load(content)
    if not isinstance(data, dict) or "executive_overview" not in data:
        raise MalformedLLMOutput("report missing executive_overview")
    text = _flatten_report_text(data["executive_overview"]).strip()
    if not text:
        raise MalformedLLMOutput("empty executive_overview")
    return text[: int(os.environ.get("REPORT_MAX_CHARS", "4000"))]


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
    # Only `accepted` and `done` are load-bearing; `rejected`/`duplicates` are
    # accepted-but-unused, so they are optional. Requiring the model to echo
    # long rejected/duplicate lists risks truncating the response past
    # max_tokens (an "Unterminated string" JSON error).
    for key in ("accepted", "done"):
        if key not in data:
            raise MalformedLLMOutput(f"curator missing key: {key}")
    if not isinstance(data["done"], bool):
        raise MalformedLLMOutput("done must be bool")
    _require_url_list(data["accepted"], "accepted")  # accepted is [{url}] only
    data.setdefault("tool_call", None)
    data.setdefault("rejected", [])
    data.setdefault("duplicates", [])
    return data


def _normalize_confidence(value):
    """Map any confidence shape to high/medium/low (field is best-effort)."""
    if isinstance(value, str) and value.lower() in ("high", "medium", "low"):
        return value.lower()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "high" if value >= 0.66 else "medium" if value >= 0.33 else "low"
    return "medium"


def parse_identity(content):
    """Parse the IDENTITY response tolerantly.

    IDENTITY is non-fatal and best-effort (§5.4/§19): its whole purpose is the
    official domain for own-channel exclusion. Real models return `confidence`
    as a number and sometimes `matched` as evidence rather than a bool, so this
    parser SALVAGES a usable domain instead of discarding it over an unused
    field — otherwise own-domain exclusion would be needlessly skipped. Only a
    non-JSON body (caught by `_load`) fails. `matched` is authoritative only
    when it is a real bool AND a usable domain exists; otherwise it is derived
    from the presence of a string domain.
    """
    data = _load(content)
    dom = data.get("official_domain")
    if not (isinstance(dom, str) and dom.strip()):
        dom = None
    raw_matched = data.get("matched")
    if isinstance(raw_matched, bool):
        matched = raw_matched and dom is not None
    else:
        matched = dom is not None  # derive from a usable domain
    profiles = data.get("owned_profile_urls")
    profiles = [u for u in profiles if isinstance(u, str)] \
        if isinstance(profiles, list) else []
    handles = data.get("owned_social_handles")
    handles = [h for h in handles if isinstance(h, str)] \
        if isinstance(handles, list) else []
    return {
        "official_domain": dom, "matched": matched,
        "owned_profile_urls": profiles, "owned_social_handles": handles,
        "confidence": _normalize_confidence(data.get("confidence")),
    }


def _derive_sentiment_label(score):
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def parse_sentiment(content):
    """Tolerant sentiment parse -> {score in [-1,1] or None, label or None}.

    Non-fatal upstream (§5.4): an unusable score yields unknown sentiment
    rather than raising. Only a non-JSON body fails (via `_load`).
    """
    data = _load(content)
    unknown = {"score": None, "label": None, "summary": None}
    if not isinstance(data, dict):  # valid JSON but not an object -> unknown
        return unknown
    raw = data.get("score")
    # bool is an int subclass in Python; exclude it explicitly.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return unknown
    score = max(-1.0, min(1.0, float(raw)))
    label = data.get("label")
    if label not in ("positive", "neutral", "negative"):
        label = _derive_sentiment_label(score)
    summary = data.get("summary")
    if isinstance(summary, str):
        summary = summary.strip()[
            : int(os.environ.get("SENTIMENT_SUMMARY_MAX_CHARS", "400"))] or None
    else:
        summary = None
    return {"score": score, "label": label, "summary": summary}
