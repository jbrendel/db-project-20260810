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


def call_llm(name, messages, tools=None, run_id=None, category_key=None):
    """One request -> one response. Logs the full turn. No internal loop."""
    import uuid
    import json
    cfg = resolve_llm_config(name)
    request_id = uuid.uuid4().hex
    started = time.time()
    resp = _client(cfg).chat.completions.create(
        model=cfg["model"], messages=messages, tools=tools or None,
        max_tokens=cfg["max_tokens"], temperature=cfg["temperature"],
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
            "response": result["content"],
        }))
    except Exception as exc:  # a logging failure must not kill the run
        logging.getLogger("drumbeat").warning("llm log failed: %s", exc)
    return result
