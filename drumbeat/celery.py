"""Celery app with explicit settings (plans/INITIAL.md Section 17.1)."""
import os
from celery import Celery
from celery.signals import worker_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "drumbeat.settings")
app = Celery("drumbeat")
# Pull CELERY_* from Django settings so tests can flip eager via settings/app.
app.config_from_object("django.conf:settings", namespace="CELERY")
# REDIS_URL is REQUIRED at runtime — no localhost:6379 fallback (§14). Tests set
# it via pytest.ini env. `os.environ["REDIS_URL"]` fails loud if absent.
app.conf.update(
    broker_url=os.environ["REDIS_URL"],
    result_backend=os.environ["REDIS_URL"],
    result_expires=24 * 3600,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # acks_late/reject_on_worker_lost = False (§17.1 decision): do NOT redeliver
    # lost tasks; the reaper owns lost-worker recovery, avoiding same-generation
    # duplicate execution.
    task_acks_late=False,
    task_reject_on_worker_lost=False,
    worker_prefetch_multiplier=1,
    worker_concurrency=int(os.environ.get("WORKER_CONCURRENCY", "4")),
    task_track_started=True,
    task_soft_time_limit=int(os.environ.get("SUBTASK_SOFT_LIMIT", "180")),
    task_time_limit=int(os.environ.get("SUBTASK_HARD_LIMIT", "210")),
    beat_schedule={
        "reap-stuck-runs": {
            "task": "research.tasks.reap_stuck_runs",
            "schedule": float(os.environ.get("REAPER_INTERVAL_SECONDS",
                                             "60")),
        }
    },
)
app.autodiscover_tasks(["research"])


@worker_init.connect
def _check_config(**kwargs):
    # worker_init fires ONCE in the master before forking, so a missing-config
    # worker refuses to boot (not a crash-loop of prefork children).
    from research.config_check import validate_required_env
    validate_required_env()
