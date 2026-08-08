"""DRF views: create/list/detail/refresh/delete (§11)."""
import logging
import os

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from research.models import Run
from research.serializers import (RunCreateSerializer, RunDetailSerializer,
                                 RunListSerializer, _create_categories)
from research.fencing import (bump_generation, append_celery_task_id,
                             SupersededGeneration)
from research.tasks import start_run

_log = logging.getLogger("drumbeat")


def exception_handler(exc, context):
    """Wrap every DRF error in the {detail, field} envelope (§13)."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    field, detail = None, None
    if isinstance(data, dict):
        if set(data.keys()) == {"detail"}:
            detail = str(data["detail"])
        else:
            first_field, msgs = next(iter(data.items()))
            if isinstance(msgs, (list, tuple)):
                detail = str(msgs[0])
            else:
                detail = str(msgs)
            field = None if first_field == "non_field_errors" else first_field
    elif isinstance(data, list):
        detail = str(data[0]) if data else "Invalid request."
    response.data = {"detail": detail, "field": field}
    return response


def revoke_task_ids(task_ids):
    """Best-effort revoke of Celery task ids. Correctness relies on fencing,
    not this (Section 5.7). Never terminate=True (would SIGTERM a sibling)."""
    from drumbeat.celery import app
    for task_id in task_ids or []:
        try:
            app.control.revoke(task_id)
        except Exception as exc:
            _log.warning("revoke failed: %s", exc)


def _dispatch(run_id):
    """Dispatch start_run and store its id (best-effort) at the current gen."""
    res = start_run.delay(run_id)
    try:  # fenced idempotent append at the CURRENT generation
        gen = Run.objects.values_list("generation", flat=True).get(id=run_id)
        append_celery_task_id(run_id, gen, str(res.id))
    except (SupersededGeneration, Run.DoesNotExist):
        pass  # a refresh/delete raced; id storage is best-effort only


class RunListCreateView(APIView):
    def get(self, request):
        default = int(os.environ.get("RUN_LIST_PAGE_SIZE", "50"))
        # Bad pagination input fails loud with a 400 (§16), not a silent
        # fallback. Large limits are still capped at 200.
        limit = min(_query_int(request, "limit", default, minimum=1), 200)
        offset = _query_int(request, "offset", 0, minimum=0)
        qs = Run.objects.all()  # Meta.ordering = ["-id"] -> newest first
        count = qs.count()
        rows = qs[offset:offset + limit]
        return Response({"results": RunListSerializer(rows, many=True).data,
                         "count": count})

    def post(self, request):
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            run = serializer.save()
            Run.objects.filter(id=run.id).update(started_at=timezone.now())
            run.refresh_from_db()
            transaction.on_commit(lambda: _dispatch(run.id))
        return Response(RunDetailSerializer(run).data,
                        status=status.HTTP_201_CREATED)


class RunDetailView(APIView):
    def get(self, request, pk):
        # Prefetch categories+items so the ~2s poll serializes in a constant
        # number of queries (no per-category count/N+1).
        run = (Run.objects.prefetch_related("categories__items")
               .filter(id=pk).first())
        if run is None:
            return _not_found()
        return Response(RunDetailSerializer(run).data)

    def delete(self, request, pk):
        run = _get_or_404(pk)
        if run is None:
            return _not_found()
        old_ids = list(run.celery_task_ids)
        run.delete()  # cascades to Category/ContentItem
        revoke_task_ids(old_ids)  # best-effort, outside any transaction
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunRefreshView(APIView):
    def post(self, request, pk):
        run = _get_or_404(pk)
        if run is None:
            return _not_found()
        old_ids = list(run.celery_task_ids)
        selected = list(run.selected_categories)
        with transaction.atomic():
            bump_generation(run.id)
            run.categories.all().delete()  # cascades to items
            Run.objects.filter(id=run.id).update(
                status="blue", started_at=timezone.now(), ended_at=None,
                executive_overview=None, error=None, warnings=[],
                celery_task_ids=[])
            run.refresh_from_db()
            _create_categories(run, selected)
            transaction.on_commit(lambda: _dispatch(run.id))
        revoke_task_ids(old_ids)  # best-effort, outside the transaction
        return Response(RunDetailSerializer(run).data)


def _query_int(request, name, default, minimum):
    """Parse an integer query param or raise a 400 (name-tagged) envelope."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: f"{name} must be an integer."})
    if value < minimum:
        raise ValidationError({name: f"{name} must be >= {minimum}."})
    return value


def _get_or_404(pk):
    return Run.objects.filter(id=pk).first()


def _not_found():
    return Response({"detail": "Run not found.", "field": None},
                    status=status.HTTP_404_NOT_FOUND)
