import pytest
from django.core.exceptions import ImproperlyConfigured
from research import config_check


def test_missing_required_vars_raise(monkeypatch):
    for var in config_check.REQUIRED_VARS:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ImproperlyConfigured) as exc:
        config_check.validate_required_env()
    assert "TAVILY_API_KEY" in str(exc.value)
    assert "DEFAULT_LLM_URL" in str(exc.value)


def test_all_present_passes(monkeypatch):
    for var in config_check.REQUIRED_VARS:
        monkeypatch.setenv(var, "x")
    assert config_check.validate_required_env() is None
