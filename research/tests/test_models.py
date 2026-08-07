import pytest
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def test_create_run_defaults():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"], lookback_months=36)
    assert run.status == "blue"
    assert run.generation == 1
    assert run.warnings == []
    assert run.celery_task_ids == []


def test_category_and_items():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"])
    cat = Category.objects.create(run=run, key="news", display_order=0)
    assert cat.status == "pending"
    item = ContentItem.objects.create(
        category=cat, title="t", url="https://x.com",
        canonical_url="https://x.com/", source="x.com")
    assert cat.items.count() == 1
    assert item.is_undated is True


def test_item_is_undated_property():
    from django.utils import timezone
    run = Run.objects.create(input_text="Acme", input_kind="name")
    cat = Category.objects.create(run=run, key="news")
    dated = ContentItem.objects.create(
        category=cat, title="t", url="u", canonical_url="u", source="s",
        published_at=timezone.now())
    assert dated.is_undated is False
