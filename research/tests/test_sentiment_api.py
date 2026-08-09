from datetime import datetime, timezone as tz
import pytest
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def _item(cat, url, published, score, label):
    return ContentItem.objects.create(
        category=cat, title="t", url=url, canonical_url=url, source="s",
        published_at=published, sentiment_score=score, sentiment_label=label)


def test_sentiment_timeline_and_summary(client):
    run = Run.objects.create(
        input_text="Acme", input_kind="name", lookback_months=3,
        started_at=datetime(2026, 3, 15, tzinfo=tz.utc))
    cat = Category.objects.create(run=run, key="news", status="green")
    _item(cat, "u1", datetime(2026, 1, 10, tzinfo=tz.utc), 0.5, "positive")
    _item(cat, "u2", datetime(2026, 3, 2, tzinfo=tz.utc), -0.5, "negative")
    _item(cat, "u3", None, 0.2, "neutral")           # undated, scored
    _item(cat, "u4", datetime(2026, 3, 5, tzinfo=tz.utc), None, None)  # unknown

    body = client.get(f"/api/runs/{run.id}/").json()

    tl = body["sentiment_timeline"]
    assert [b["month"] for b in tl] == ["2026-01", "2026-02", "2026-03"]
    assert tl[0]["avg_score"] == 0.5 and tl[0]["item_count"] == 1
    assert tl[1]["avg_score"] is None and tl[1]["item_count"] == 0
    assert tl[2]["avg_score"] == -0.5 and tl[2]["item_count"] == 1

    s = body["sentiment_summary"]
    assert s["scored_count"] == 3          # 3 items have a score
    assert s["undated_scored_count"] == 1  # u3
    assert s["unknown_count"] == 1         # u4
    assert s["overall_avg"] == round((0.5 - 0.5 + 0.2) / 3, 3)

    item0 = body["categories"][0]["items"][0]
    assert "sentiment_score" in item0 and "sentiment_label" in item0


def test_sentiment_timeline_empty_run(client):
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             lookback_months=1,
                             started_at=datetime(2026, 3, 15, tzinfo=tz.utc))
    Category.objects.create(run=run, key="news", status="yellow")
    body = client.get(f"/api/runs/{run.id}/").json()
    assert body["sentiment_timeline"] == [
        {"month": "2026-03", "avg_score": None, "item_count": 0}]
    assert body["sentiment_summary"]["overall_avg"] is None
    assert body["sentiment_summary"]["scored_count"] == 0
