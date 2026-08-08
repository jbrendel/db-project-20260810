import json
import logging
from unittest.mock import patch

import pytest
from research import llm
from research.llm import resolve_llm_config, call_llm


def _set_defaults(monkeypatch, **over):
    # TOKENS/TEMP MUST be numeric strings: resolve_llm_config casts them.
    vals = {"URL": "d-url", "API_KEY": "d-key", "MODEL": "d-model",
            "TOKENS": "1000", "TEMP": "0.2"}
    vals.update(over)
    for k, v in vals.items():
        monkeypatch.setenv(f"DEFAULT_LLM_{k}", v)


def test_fallback_to_default(monkeypatch):
    _set_defaults(monkeypatch)
    monkeypatch.delenv("REPORT_LLM_MODEL", raising=False)
    cfg = resolve_llm_config("REPORT")
    assert cfg["model"] == "d-model"
    assert cfg["max_tokens"] == 1000 and cfg["temperature"] == 0.2


def test_override_wins(monkeypatch):
    _set_defaults(monkeypatch)
    monkeypatch.setenv("REPORT_LLM_MODEL", "gpt-x")
    assert resolve_llm_config("REPORT")["model"] == "gpt-x"


def test_invalid_numeric_fails_loud(monkeypatch):
    _set_defaults(monkeypatch, TOKENS="not-int")
    with pytest.raises(ValueError):
        resolve_llm_config("REPORT")


class _FakeUsage:
    def model_dump(self):
        return {"total_tokens": 12}


class _FakeMsg:
    def __init__(self):
        self.content = "hello"
        self.tool_calls = []


class _FakeChoice:
    def __init__(self):
        self.message = _FakeMsg()


class _FakeResp:
    def __init__(self):
        self.choices = [_FakeChoice()]
        self.usage = _FakeUsage()


class _FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return _FakeResp()


def test_call_llm_returns_and_logs(monkeypatch, caplog):
    _set_defaults(monkeypatch, API_KEY="super-secret-key")
    with patch.object(llm, "_client", return_value=_FakeClient()):
        with caplog.at_level(logging.INFO, logger="drumbeat.llm"):
            out = call_llm("REPORT", [{"role": "user", "content": "hi"}],
                           run_id=1, category_key="news")
    assert out["content"] == "hello"
    assert out["usage"] == {"total_tokens": 12}
    # Redaction by omission: the api_key must never reach the log.
    assert "super-secret-key" not in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["call_point"] == "REPORT"
    assert record["run_id"] == 1 and record["category_key"] == "news"
    # Full response is logged as content + tool_calls (§7).
    assert record["response"]["content"] == "hello"
    assert record["response"]["tool_calls"] == []


class _FakeToolCall:
    def model_dump(self):
        return {"id": "call_1", "function": {"name": "search",
                "arguments": '{"query": "x"}'}}


def test_call_llm_logs_tool_calls(monkeypatch, caplog):
    _set_defaults(monkeypatch)

    class _MsgWithTool(_FakeMsg):
        def __init__(self):
            super().__init__()
            self.content = ""
            self.tool_calls = [_FakeToolCall()]

    class _ChoiceTool(_FakeChoice):
        def __init__(self):
            self.message = _MsgWithTool()

    class _RespTool(_FakeResp):
        def __init__(self):
            self.choices = [_ChoiceTool()]
            self.usage = _FakeUsage()

    class _ClientTool:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _RespTool()

    with patch.object(llm, "_client", return_value=_ClientTool()):
        with caplog.at_level(logging.INFO, logger="drumbeat.llm"):
            out = call_llm("CURATOR", [{"role": "user", "content": "hi"}])
    assert out["tool_calls"][0]["function"]["name"] == "search"
    record = json.loads(caplog.records[-1].message)
    assert record["response"]["tool_calls"][0]["id"] == "call_1"


def test_call_llm_logging_failure_does_not_propagate(monkeypatch):
    _set_defaults(monkeypatch)
    with patch.object(llm, "_client", return_value=_FakeClient()), \
         patch.object(llm._llm_logger, "info", side_effect=RuntimeError("x")):
        out = call_llm("REPORT", [{"role": "user", "content": "hi"}])
    assert out["content"] == "hello"  # a logging fault must not kill the call
