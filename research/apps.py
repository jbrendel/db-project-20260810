from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _set_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.cursor().execute("PRAGMA journal_mode=WAL;")


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "research"

    def ready(self):
        import os
        from research.config_check import validate_required_env
        connection_created.connect(_set_sqlite_wal)
        # Fail loud on every Django entry point (runserver, WSGI/ASGI,
        # django-admin) EXCEPT under an explicit test switch. Do NOT gate on
        # PYTEST_CURRENT_TEST — it is set per-test, not during the initial
        # django.setup(), so app-registry population could fail before fixtures
        # run (Codex impl point 1).
        if os.environ.get("DRUMBEAT_SKIP_CONFIG_CHECK") != "1":
            validate_required_env()
