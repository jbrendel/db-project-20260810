"""Single entry point for all LLM calls (plans/INITIAL.md Sections 6, 7)."""
import os
import time
import logging

_FIELDS = {
    "url": "URL", "api_key": "API_KEY", "model": "MODEL",
    "max_tokens": "TOKENS", "temperature": "TEMP",
}
_llm_logger = logging.getLogger("drumbeat.llm")


def resolve_llm_config(name):
    """Resolve <NAME>_LLM_* with fallback to DEFAULT_LLM_* for each field."""
    cfg = {}
    for field, suffix in _FIELDS.items():
        val = os.environ.get(f"{name}_LLM_{suffix}")
        if val is None:
            val = os.environ[f"DEFAULT_LLM_{suffix}"]  # required; fail loud
        cfg[field] = val
    cfg["max_tokens"] = int(cfg["max_tokens"])
    cfg["temperature"] = float(cfg["temperature"])
    return cfg


def _client(cfg):
    from openai import OpenAI  # imported lazily, per-process
    return OpenAI(base_url=cfg["url"], api_key=cfg["api_key"])


def call_llm(name, messages, tools=None, run_id=None, category_key=None,
             json_object=False):
    """One request -> one response. Logs the full turn. No internal loop.

    json_object=True asks the provider to return a valid JSON object
    (OpenAI-compatible JSON mode), which eliminates non-JSON/partial-prose
    replies for the structured call-points. Disable via LLM_JSON_MODE=0 for a
    provider that does not support response_format.
    """
    import uuid
    import json
    cfg = resolve_llm_config(name)
    request_id = uuid.uuid4().hex
    kwargs = {}
    if json_object and os.environ.get("LLM_JSON_MODE", "1") != "0":
        kwargs["response_format"] = {"type": "json_object"}
    started = time.time()
    resp = _client(cfg).chat.completions.create(
        model=cfg["model"], messages=messages, tools=tools or None,
        max_tokens=cfg["max_tokens"], temperature=cfg["temperature"],
        **kwargs,
    )
    choice = resp.choices[0].message
    result = {
        "content": choice.content or "",
        "tool_calls": [tc.model_dump() for tc in (choice.tool_calls or [])],
        "usage": resp.usage.model_dump() if resp.usage else None,
    }
    # Log ONE JSON payload as the message. Do NOT use extra={"name": ...} etc.:
    # "name"/"module"/"msg" are reserved LogRecord attrs and raise KeyError.
    # cfg (which holds api_key) is NEVER logged -> redaction by omission.
    try:
        _llm_logger.info(json.dumps({
            "request_id": request_id, "call_point": name,
            "model": cfg["model"], "run_id": run_id,
            "category_key": category_key,
            "duration_s": round(time.time() - started, 3),
            "usage": result["usage"], "prompt": messages,
            # Full response = content AND tool_calls (curator turns request
            # searches via tool_calls; §7 logs the full response).
            "response": {"content": result["content"],
                         "tool_calls": result["tool_calls"]},
        }))
    except Exception as exc:  # a logging failure must not kill the run
        logging.getLogger("drumbeat").warning("llm log failed: %s", exc)
    return result


def call_and_parse(call_fn, name, messages, parse_fn, run_id=None,
                   category_key=None, json_object=True):
    """Call an LLM and parse its JSON, RETRYING on malformed output.

    `call_fn` is a `call_llm` reference (passed in so the caller's mockable seam
    is used). On `MalformedLLMOutput` the model is re-prompted with the
    validation error appended, up to LLM_MAX_RETRIES times, then the error is
    raised for the caller to handle non-fatally. Every attempt is logged by
    `call_llm` itself (§7), so retries are visible.
    """
    from research.schemas import MalformedLLMOutput
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "2"))
    convo = list(messages)
    last_exc = None
    for _ in range(max_retries + 1):
        out = call_fn(name, convo, run_id=run_id, category_key=category_key,
                      json_object=json_object)
        try:
            return parse_fn(out["content"])
        except MalformedLLMOutput as exc:
            last_exc = exc
            convo = convo + [
                {"role": "assistant", "content": out["content"]},
                {"role": "user", "content": (
                    f"Your previous reply was not valid ({exc}). Reply with "
                    "ONLY valid JSON matching the required shape — no prose, "
                    "no markdown.")},
            ]
    raise last_exc
