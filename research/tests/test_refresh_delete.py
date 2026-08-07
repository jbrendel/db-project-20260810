import pytest
from unittest.mock import patch
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def test_refresh_bumps_generation_and_wipes(
        client, django_capture_on_commit_callbacks):
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"], status="green")
    cat = Category.objects.create(run=run, key="news", status="green")
    ContentItem.objects.create(category=cat, title="t", url="u",
                               canonical_url="u", source="s")
    with patch("research.views.start_run"):
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(f"/api/runs/{run.id}/refresh/")
    run.refresh_from_db()
    assert resp.status_code in (200, 202)
    assert run.generation == 2
    assert run.status == "blue"
    assert run.ended_at is None and run.executive_overview is None
    assert ContentItem.objects.filter(category__run=run).count() == 0
    # Fresh pending categories were recreated.
    assert run.categories.count() == 1
    assert run.categories.get().status == "pending"


def test_refresh_missing_run_404(client):
    resp = client.post("/api/runs/99999/refresh/")
    assert resp.status_code == 404


def test_delete_removes_run(client):
    run = Run.objects.create(input_text="Acme", input_kind="name")
    with patch("research.views.revoke_task_ids"):
        resp = client.delete(f"/api/runs/{run.id}/")
    assert resp.status_code in (200, 204)
    assert not Run.objects.filter(id=run.id).exists()


def test_delete_missing_run_404(client):
    resp = client.delete("/api/runs/99999/")
    assert resp.status_code == 404


def test_refresh_revokes_old_ids(client, django_capture_on_commit_callbacks):
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"],
                             celery_task_ids=["old-1", "old-2"])
    Category.objects.create(run=run, key="news")
    with patch("research.views.start_run"), \
         patch("research.views.revoke_task_ids") as revoke:
        with django_capture_on_commit_callbacks(execute=True):
            client.post(f"/api/runs/{run.id}/refresh/")
    revoke.assert_called_once_with(["old-1", "old-2"])
