"""Generation fencing: the authoritative anti-clobber primitive (Sec 5.7)."""
from django.db import connection, transaction
from research.models import Run


class SupersededGeneration(Exception):
    """Raised when a write targets a run whose generation moved on."""


def guard_generation(run_id, generation):
    """First statement of a write txn; raise if the generation moved on."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation "
            "WHERE id = %s AND generation = %s",
            [run_id, generation],
        )
        if cur.rowcount == 0:
            raise SupersededGeneration(f"run {run_id} gen {generation}")


def fenced_run_update(run_id, generation, **fields):
    """Single compare-and-set UPDATE of Run fields; raise if superseded.

    One statement (`UPDATE ... WHERE id AND generation`), so no separate guard
    is needed for a Run-only write (Codex impl point 16).
    """
    updated = Run.objects.filter(id=run_id, generation=generation).update(
        **fields)
    if updated == 0:
        raise SupersededGeneration(f"run {run_id} gen {generation}")


def bump_generation(run_id):
    """Atomically increment and return the new generation (one statement)."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation + 1 "
            "WHERE id = %s RETURNING generation",
            [run_id],
        )
        row = cur.fetchone()  # None if the run was deleted concurrently
        if row is None:
            raise SupersededGeneration(f"run {run_id} missing")
        return row[0]  # SQLite 3.35+ supports RETURNING


def bump_generation_if_stale(run_id, cutoff):
    """Bump generation ONLY for a still-blue, stale run (Codex impl point 5).

    Returns the new generation, or None if the run already completed (so the
    reaper does not bump a just-finished run's generation).
    """
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation + 1 "
            "WHERE id = %s AND status = 'blue' AND started_at < %s "
            "RETURNING generation",
            [run_id, cutoff],
        )
        row = cur.fetchone()
        return row[0] if row else None


def append_celery_task_id(run_id, generation, task_id):
    """Fenced, idempotent append to Run.celery_task_ids (Codex impl-2 pt 5).

    Re-reads the current list inside the guarded txn so concurrent create/
    start_run writes cannot overwrite each other.
    """
    with transaction.atomic():
        guard_generation(run_id, generation)
        ids = Run.objects.values_list("celery_task_ids", flat=True).get(
            id=run_id)
        if task_id not in ids:
            Run.objects.filter(id=run_id).update(
                celery_task_ids=ids + [task_id])
