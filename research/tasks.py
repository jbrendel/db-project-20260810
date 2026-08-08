"""Celery tasks: chord orchestration, fenced writes, reaper (Section 5)."""
import logging
import os
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from celery import shared_task, chord
from research.models import Run, Category, ContentItem
from research.pipeline import research_category
from research.identity import resolve_identity
from research.exclusion import ExclusionSet
from research.fencing import (guard_generation, bump_generation,
                              bump_generation_if_stale, fenced_run_update,
                              append_celery_task_id, SupersededGeneration)
from research.status import compute_run_status
from research.categories import BORDERLINE_DOMAIN_MAP
from research.llm import call_llm
from research import schemas, urls_util

_log = logging.getLogger("drumbeat")

# Shown to the user for any failed category. The real error (with traceback) is
# written to the application log, never surfaced in the API/UI (§16 fail-loud in
# the logs, generic in the UI).
GENERIC_CATEGORY_ERROR = "This category could not be researched due to an error."


@shared_task
def start_run(run_id):
    try:
        _start_run_body(run_id)
    except (SupersededGeneration, Run.DoesNotExist):
        return  # deleted/refreshed before start: expected control flow (§5.4)


def _start_run_body(run_id):
    run = Run.objects.get(id=run_id)
    gen = run.generation
    warnings = list(run.warnings)
    try:
        domain, profiles, handles = resolve_identity(run)
        if domain is None:
            warnings.append("identity: domain unresolved; own-domain "
                            "exclusion skipped")
    except Exception as exc:  # IDENTITY is non-fatal (Section 5.4)
        _log.warning("identity resolution failed for run %s: %s", run_id, exc,
                     exc_info=exc)
        domain, profiles, handles = None, [], []
        warnings.append("identity: domain unresolved; own-domain exclusion "
                        "skipped")
    # started_at is set at CREATE (Task 15, Codex impl point 20), not here.
    fenced_run_update(run_id, gen, resolved_domain=domain,
                      owned_profile_urls=profiles,
                      owned_social_handles=handles, warnings=warnings)
    header = [run_category.s(run_id, gen, c.key)
              for c in run.categories.all()]
    result = chord(header)(finalize_run.s(run_id, gen))
    # Track the chord/finalize id for best-effort revocation (fenced, idempotent
    # append so it can't clobber the parent id stored at create).
    try:
        append_celery_task_id(run_id, gen, result.id)
    except SupersededGeneration:
        pass


def _exclusion_for(run):
    allow = set()
    for key, ticked in run.borderline_options.items():
        if ticked:
            allow |= BORDERLINE_DOMAIN_MAP.get(key, set())
    return ExclusionSet(run.resolved_domain, run.owned_profile_urls,
                        run.owned_social_handles, allow)


def _order_items(items):
    dated = [i for i in items if i["published_at"] is not None]
    undated = [i for i in items if i["published_at"] is None]
    dated.sort(key=lambda i: i["published_at"], reverse=True)
    return dated + undated  # undated last (Section 10)


@shared_task
def run_category(run_id, generation, category_key):
    try:
        _run_category_body(run_id, generation, category_key)
    except (SupersededGeneration, Run.DoesNotExist):
        return  # refreshed/deleted/reaped; not a failure (§5.4)
    except Exception as exc:
        _mark_category_red(run_id, generation, category_key, exc)
    return category_key


def _run_category_body(run_id, generation, category_key):
    run = Run.objects.get(id=run_id)
    with transaction.atomic():
        guard_generation(run_id, generation)
        Category.objects.filter(run_id=run_id, key=category_key).update(
            status="running", started_at=timezone.now())
    result = research_category(run.input_text, category_key,
                              run.lookback_months, _exclusion_for(run))
    ordered = _order_items(result["items"])
    with transaction.atomic():
        guard_generation(run_id, generation)
        cat = Category.objects.get(run_id=run_id, key=category_key)
        cat.items.all().delete()  # delete-then-insert: redelivery-safe
        ContentItem.objects.bulk_create([
            ContentItem(
                category=cat, title=i["title"], url=i["url"],
                canonical_url=urls_util.canonicalize_url_for_dedupe(i["url"]),
                source=i["source"], published_at=i["published_at"],
                snippet=i["snippet"], display_order=n)
            for n, i in enumerate(ordered)])
        cat.summary = result["summary"]
        cat.status = "green" if ordered else "yellow"
        cat.ended_at = timezone.now()
        cat.save(update_fields=["summary", "status", "ended_at"])


def _mark_category_red(run_id, generation, category_key, exc):
    # Log the real error (with traceback) for the operator; store only a
    # generic, user-safe message so LLM/parse internals never reach the UI.
    _log.error("category %s failed for run %s: %s", category_key, run_id, exc,
               exc_info=exc)
    try:
        with transaction.atomic():
            guard_generation(run_id, generation)
            Category.objects.filter(run_id=run_id, key=category_key).update(
                status="red", error=GENERIC_CATEGORY_ERROR,
                ended_at=timezone.now())
    except SupersededGeneration:
        return  # superseded run: do NOT mark red (expected control flow)


@shared_task
def finalize_run(results, run_id, generation):
    try:
        _finalize_body(run_id, generation)
    except (SupersededGeneration, Run.DoesNotExist):
        return  # refreshed/deleted/reaped: expected control flow
    except Exception as exc:
        # Boundary 2 (§5.4): a REPORT/DB failure must still set a terminal
        # status, else the run is stuck BLUE until the reaper.
        _log.error("finalize failed for run %s: %s", run_id, exc, exc_info=exc)
        _degrade_run_terminal(run_id, generation)


def _degrade_run_terminal(run_id, generation):
    try:
        with transaction.atomic():
            guard_generation(run_id, generation)
            total = ContentItem.objects.filter(
                category__run_id=run_id).count()
            Run.objects.filter(id=run_id, generation=generation,
                               status="blue").update(
                status="yellow" if total else "red",
                executive_overview="Report generation failed; results below "
                                   "may be partial.",
                ended_at=timezone.now())
    except SupersededGeneration:
        return


def _finalize_body(run_id, generation):
    run = Run.objects.get(id=run_id)
    if run.generation != generation:
        raise SupersededGeneration(run_id)
    cats = sorted(run.categories.all(), key=lambda c: c.display_order)
    seen, remove_ids, kept, kept_items = set(), [], {}, []
    for cat in cats:  # dedup plan in memory (NO txn held; §5.3)
        n = 0
        for item in cat.items.all():
            if item.canonical_url in seen:
                remove_ids.append(item.id)  # a lower-priority duplicate
            else:
                seen.add(item.canonical_url)
                kept_items.append((cat.key, item))  # survives the dedup
                n += 1
        kept[cat.id] = n
    total = sum(kept.values())
    if total > 0:  # REPORT is a network call -> OUTSIDE any transaction.
        # Build the prompt from KEPT items only, so the overview never mentions
        # a duplicate about to be removed (Codex impl-2 point 6).
        overview = schemas.parse_report(call_llm(
            "REPORT", [{"role": "user",
                        "content": _report_prompt(run, kept_items)}],
            run_id=run_id, json_object=True)["content"])
    else:
        overview = ("No third-party content was found in the selected "
                    "time window.")
    with transaction.atomic():  # one short fenced write
        guard_generation(run_id, generation)
        ContentItem.objects.filter(id__in=remove_ids).delete()
        statuses = []
        for cat in cats:
            if kept[cat.id] == 0 and cat.status == "green":
                cat.status, cat.summary = "yellow", None
                cat.save(update_fields=["status", "summary"])
            statuses.append(cat.status)
        run_status = compute_run_status(statuses, total)
        updated = Run.objects.filter(
            id=run_id, generation=generation, status="blue").update(
            executive_overview=overview, ended_at=timezone.now(),
            status=run_status)
        if updated == 0:  # a same-generation duplicate finalize already
            raise SupersededGeneration(run_id)  # ran; roll back our dedup writes


def _report_prompt(run, kept_items):
    """kept_items is a list of (category_key, ContentItem) surviving dedup."""
    cap = int(os.environ.get("REPORT_MAX_ITEMS_TOTAL", "60"))
    snip = int(os.environ.get("REPORT_MAX_ITEM_SNIPPET_CHARS", "200"))
    lines = [f"[{key}] {item.title} :: {item.snippet[:snip]}"
             for key, item in kept_items[:cap]]
    body = "\n".join(lines)
    return (f'Write a concise executive overview of "{run.input_text}" from '
            f'these findings. Return JSON {{"executive_overview": "..."}}.\n'
            f'{body}')


@shared_task
def reap_stuck_runs():
    max_dur = int(os.environ.get("RUN_MAX_DURATION_SECONDS", "600"))
    cutoff = timezone.now() - timedelta(seconds=max_dur)
    for run in Run.objects.filter(status="blue", started_at__lt=cutoff):
        try:
            _reap_one(run.id, cutoff)
        except SupersededGeneration:
            continue  # overlapping sweep/refresh already handled it (§5.5)


def _reap_one(run_id, cutoff):
    # Conditional bump: only a still-blue, still-stale run (Codex impl point 5).
    gen = bump_generation_if_stale(run_id, cutoff)
    if gen is None:
        return  # run completed between the SELECT and now; do not touch it
    with transaction.atomic():
        guard_generation(run_id, gen)  # raises if a racing bump moved gen
        Category.objects.filter(run_id=run_id,
            status__in=["pending", "running"]).update(
            status="red", error="run timed out", ended_at=timezone.now())
        statuses = [c.status for c in
                    Run.objects.get(id=run_id).categories.all()]
        total = ContentItem.objects.filter(category__run_id=run_id).count()
        # After the conditional bump the run is still blue at our generation, so
        # this should affect exactly 1 row. Check the rowcount for discipline: a
        # 0 means a concurrent terminal writer won -> treat as superseded (Codex
        # impl-2 point 8), which rolls back our category writes too.
        updated = Run.objects.filter(
            id=run_id, generation=gen, status="blue").update(
            status=compute_run_status(statuses, total),
            executive_overview="Run timed out; results may be partial.",
            ended_at=timezone.now())
        if updated == 0:
            raise SupersededGeneration(f"run {run_id} reaper lost the race")
