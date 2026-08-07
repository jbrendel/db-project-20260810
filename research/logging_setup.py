"""LLM-log handler setup (plans/INITIAL.md Section 7).

The `drumbeat.llm` logger gets its own per-process rotating file handler. If the
log directory cannot be created or written, this fails loud at startup — a
mid-run write error is handled inside `call_llm` and downgraded to a warning.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def configure_llm_logging(log_dir, max_bytes, backup_count):
    """Attach a per-PID RotatingFileHandler to the drumbeat.llm logger."""
    directory = Path(log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".llm-log-probe-{os.getpid()}"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:  # fail loud: an unusable log path stops startup
        raise ImproperlyConfigured(
            f"LLM log directory {directory!r} is not writable: {exc}"
        ) from exc

    logger = logging.getLogger("drumbeat.llm")
    filename = directory / f"llm-{os.getpid()}.log"
    already = any(
        isinstance(h, RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(filename)
        for h in logger.handlers
    )
    if not already:
        handler = RotatingFileHandler(
            filename, maxBytes=max_bytes, backupCount=backup_count)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # §7: the LLM log is a file distinct from the general application log. With
    # the dedicated handler installed, stop propagation so the full prompt/
    # response body does not also bloat the root/app log. Tests never call this
    # (skip switch), so the logger keeps default propagation and caplog works.
    logger.propagate = False
    return logger
