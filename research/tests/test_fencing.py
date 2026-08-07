import pytest
from django.db import transaction
from research.models import Run, Category
from research import fencing

pytestmark = pytest.mark.django_db


def _run(gen=1):
    return Run.objects.create(input_text="A", input_kind="name",
                              generation=gen)


def test_guard_rolls_back_child_inserts():
    # Insert a child row, THEN hit a failing guard in the SAME transaction, to
    # prove the rowcount-abort discards the child insert (§18 requirement). In
    # production the guard is the FIRST statement, so the insert never happens;
    # this test deliberately orders it after to exercise the rollback.
    run = _run()
    fencing.bump_generation(run.id)  # generation == 2, so gen 1 is now stale
    with pytest.raises(fencing.SupersededGeneration):
        with transaction.atomic():
            Category.objects.create(run=run, key="news")  # child insert
            fencing.guard_generation(run.id, 1)            # 0 rows -> raise
    assert Category.objects.filter(run=run).count() == 0   # rolled back


def test_guard_allows_current_generation():
    run = _run()
    with transaction.atomic():
        fencing.guard_generation(run.id, 1)
        Category.objects.create(run=run, key="news")
    assert Category.objects.filter(run=run).count() == 1


def test_bump_is_atomic_increment():
    run = _run()
    assert fencing.bump_generation(run.id) == 2
    assert fencing.bump_generation(run.id) == 3


def test_bump_missing_run_raises():
    with pytest.raises(fencing.SupersededGeneration):
        fencing.bump_generation(999999)


def test_fenced_run_update_rejects_stale():
    run = _run()
    fencing.bump_generation(run.id)  # now generation 2
    with pytest.raises(fencing.SupersededGeneration):
        fencing.fenced_run_update(run.id, 1, status="green")
    run.refresh_from_db()
    assert run.status == "blue"  # not written


def test_fenced_run_update_applies_current():
    run = _run()
    fencing.fenced_run_update(run.id, 1, status="green")
    run.refresh_from_db()
    assert run.status == "green"


def test_bump_if_stale_skips_completed_run():
    from django.utils import timezone
    from datetime import timedelta
    old = timezone.now() - timedelta(hours=1)
    run = Run.objects.create(input_text="A", input_kind="name",
                             status="green", started_at=old)
    # Not blue -> reaper must not bump it.
    assert fencing.bump_generation_if_stale(run.id, timezone.now()) is None


def test_bump_if_stale_bumps_stuck_blue():
    from django.utils import timezone
    from datetime import timedelta
    old = timezone.now() - timedelta(hours=1)
    run = Run.objects.create(input_text="A", input_kind="name",
                             status="blue", started_at=old)
    assert fencing.bump_generation_if_stale(run.id, timezone.now()) == 2


def test_append_celery_task_id_is_idempotent():
    run = _run()
    fencing.append_celery_task_id(run.id, 1, "abc")
    fencing.append_celery_task_id(run.id, 1, "abc")  # dupe ignored
    fencing.append_celery_task_id(run.id, 1, "def")
    run.refresh_from_db()
    assert run.celery_task_ids == ["abc", "def"]


def test_append_celery_task_id_fenced():
    run = _run()
    fencing.bump_generation(run.id)  # now gen 2
    with pytest.raises(fencing.SupersededGeneration):
        fencing.append_celery_task_id(run.id, 1, "abc")
