from drumbeat.celery import app


def test_celery_settings():
    conf = app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert conf.task_acks_late is False   # §17.1 decision: no redelivery
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_reject_on_worker_lost is False
    assert conf.task_track_started is True


def test_reaper_beat_registered():
    assert "reap-stuck-runs" in app.conf.beat_schedule
    entry = app.conf.beat_schedule["reap-stuck-runs"]
    assert entry["task"] == "research.tasks.reap_stuck_runs"
