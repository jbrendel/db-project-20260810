import pytest
from unittest.mock import patch
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def test_create_requires_input(client):
    resp = client.post("/api/runs/", {"input_text": "  "},
                       content_type="application/json")
    assert resp.status_code == 400
    assert "input" in resp.json()["detail"].lower()


def test_create_rejects_bad_lookback(client):
    resp = client.post("/api/runs/",
                       {"input_text": "Acme", "lookback_months": 0},
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_rejects_out_of_range_lookback(client):
    resp = client.post("/api/runs/",
                       {"input_text": "Acme", "lookback_months": 601},
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_rejects_over_length(client):
    resp = client.post("/api/runs/",
                       {"input_text": "x" * 3000},
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_rejects_unknown_borderline(client):
    resp = client.post("/api/runs/",
                       {"input_text": "Acme",
                        "borderline_options": {"nonsense": True}},
                       content_type="application/json")
    assert resp.status_code == 400
    assert resp.json()["field"] == "borderline_options"


@pytest.mark.parametrize("bad", ["https://", "http://", "https://?x=1",
                                 "example..com"])
def test_create_rejects_malformed_url(client, bad):
    resp = client.post("/api/runs/", {"input_text": bad},
                       content_type="application/json")
    assert resp.status_code == 400


def test_create_starts_run(client, django_capture_on_commit_callbacks):
    with patch("research.views.start_run") as start:
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post("/api/runs/",
                              {"input_text": "Acme", "lookback_months": 12},
                              content_type="application/json")
    assert resp.status_code == 201
    run = Run.objects.get()
    assert run.input_kind == "name"
    assert run.lookback_months == 12
    assert run.started_at is not None      # set at submission (point 20)
    start.delay.assert_called_once_with(run.id)  # dispatched on commit


def test_create_url_input_sets_resolved_domain(
        client, django_capture_on_commit_callbacks):
    with patch("research.views.start_run"):
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post("/api/runs/",
                              {"input_text": "https://www.acme.com/about"},
                              content_type="application/json")
    assert resp.status_code == 201
    run = Run.objects.get()
    assert run.input_kind == "url"
    assert run.resolved_domain == "acme.com"


def test_create_makes_pending_categories(
        client, django_capture_on_commit_callbacks):
    with patch("research.views.start_run"):
        with django_capture_on_commit_callbacks(execute=True):
            client.post("/api/runs/", {"input_text": "Acme"},
                        content_type="application/json")
    run = Run.objects.get()
    assert run.categories.count() == 7  # 7 core categories
    assert all(c.status == "pending" for c in run.categories.all())


def test_detail_contract_nests_items(client):
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"])
    cat = Category.objects.create(run=run, key="news", status="green")
    ContentItem.objects.create(category=cat, title="t",
        url="https://n.com/a", canonical_url="https://n.com/a", source="n.com")
    body = client.get(f"/api/runs/{run.id}/").json()
    assert body["status"] == "blue"
    assert body["total_item_count"] == 1
    assert body["warnings"] == []
    assert body["categories"][0]["item_count"] == 1
    assert body["categories"][0]["items"][0]["is_undated"] is True


def test_list_newest_first(client):
    r1 = Run.objects.create(input_text="One", input_kind="name")
    r2 = Run.objects.create(input_text="Two", input_kind="name")
    body = client.get("/api/runs/").json()
    ids = [row["id"] for row in body["results"]]
    assert ids[0] == r2.id and ids[1] == r1.id


def test_htp_prefix_classifies_as_name(
        client, django_capture_on_commit_callbacks):
    # The detector only recognizes http://https://; htp:// -> name (documented).
    with patch("research.views.start_run"):
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post("/api/runs/",
                              {"input_text": "htp://example.com"},
                              content_type="application/json")
    assert resp.status_code == 201
    assert Run.objects.get().input_kind == "name"
