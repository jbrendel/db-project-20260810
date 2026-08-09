import pytest
from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from research.models import Run, Category, ContentItem
from research import tasks
from research.fencing import bump_generation

pytestmark = pytest.mark.django_db

_REPORT = {"content": '{"executive_overview": "o"}', "tool_calls": [],
           "usage": None}


def test_subtask_error_degrades_to_yellow():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news", "podcasts"],
                             started_at=timezone.now())
    for i, key in enumerate(["news", "podcasts"]):
        Category.objects.create(run=run, key=key, display_order=i)
    gen = run.generation

    def fake_research(company, key, months, exclusion, run_id=None):
        if key == "podcasts":
            raise RuntimeError("boom")
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s",
                "sentiment_score": None, "sentiment_label": None,
                "sentiment_summary": None}],
                "summary": "sum"}

    with patch.object(tasks, "research_category", side_effect=fake_research), \
         patch.object(tasks, "call_llm", return_value=_REPORT):
        tasks.run_category.run(run.id, gen, "news")
        tasks.run_category.run(run.id, gen, "podcasts")
        tasks.finalize_run.run(["news", "podcasts"], run.id, gen)

    run.refresh_from_db()
    assert run.status == "yellow"
    assert run.ended_at is not None and run.executive_overview == "o"
    assert Category.objects.get(run=run, key="podcasts").status == "red"
    assert Category.objects.get(run=run, key="news").status == "green"


def test_category_error_is_generic_and_logged(caplog):
    import logging
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"],
                             started_at=timezone.now())
    Category.objects.create(run=run, key="news", display_order=0)
    gen = run.generation

    def boom(*a, **k):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with patch.object(tasks, "research_category", side_effect=boom):
        with caplog.at_level(logging.ERROR, logger="drumbeat"):
            tasks.run_category.run(run.id, gen, "news")

    cat = Category.objects.get(run=run, key="news")
    assert cat.status == "red"
    # The user-facing error is generic; the raw parser message is NOT stored.
    assert cat.error == tasks.GENERIC_CATEGORY_ERROR
    assert "Expecting value" not in (cat.error or "")
    # ...but the real error IS in the application log (the "no logs" bug).
    assert "Expecting value" in caplog.text
    assert "news" in caplog.text


def test_stale_subtask_after_refresh_does_not_mark_red():
    # A subtask from the old generation must return normally, not mark red.
    run = Run.objects.create(input_text="Acme", input_kind="name")
    Category.objects.create(run=run, key="news", status="pending")
    old_gen = run.generation
    bump_generation(run.id)  # simulate a refresh bumping the generation

    def boom(*a, **k):
        raise RuntimeError("should be swallowed as superseded")

    with patch.object(tasks, "research_category", side_effect=boom):
        tasks.run_category.run(run.id, old_gen, "news")  # must not raise
    assert Category.objects.get(run=run, key="news").status == "pending"


def test_finalize_dedups_across_categories():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             status="blue", started_at=timezone.now())
    c1 = Category.objects.create(run=run, key="news", display_order=0,
                                 status="green")
    c2 = Category.objects.create(run=run, key="press_releases",
                                 display_order=1, status="green")
    for c in (c1, c2):
        ContentItem.objects.create(category=c, title="t",
            url="https://n.com/a", canonical_url="https://n.com/a",
            source="n.com")
    with patch.object(tasks, "call_llm", return_value=_REPORT):
        tasks.finalize_run.run([], run.id, run.generation)
    assert ContentItem.objects.filter(category__run=run).count() == 1
    c2.refresh_from_db()
    assert c2.status == "yellow"  # emptied by dedup -> demoted, summary nulled


def test_finalize_report_prompt_excludes_duplicate():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             status="blue", started_at=timezone.now())
    c1 = Category.objects.create(run=run, key="news", display_order=0,
                                 status="green")
    c2 = Category.objects.create(run=run, key="press_releases",
                                 display_order=1, status="green")
    for c in (c1, c2):
        ContentItem.objects.create(category=c, title="Same",
            url="https://n.com/a", canonical_url="https://n.com/a",
            source="n.com")
    with patch.object(tasks, "call_llm", return_value=_REPORT) as llm:
        tasks.finalize_run.run([], run.id, run.generation)
    prompt = llm.call_args[0][1][0]["content"]
    assert prompt.count("Same") == 1  # duplicate absent from REPORT input


def test_finalize_zero_items_is_red_with_fixed_message():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             status="blue", started_at=timezone.now())
    Category.objects.create(run=run, key="news", display_order=0,
                            status="yellow")
    with patch.object(tasks, "call_llm") as llm:
        tasks.finalize_run.run([], run.id, run.generation)
    llm.assert_not_called()  # REPORT skipped when zero items
    run.refresh_from_db()
    assert run.status == "red"
    assert "No third-party content" in run.executive_overview


def test_stale_finalize_after_refresh_does_not_overwrite():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             status="blue", started_at=timezone.now())
    Category.objects.create(run=run, key="news", status="green")
    ContentItem.objects.create(
        category=Category.objects.get(run=run), title="t",
        url="https://n.com/a", canonical_url="https://n.com/a", source="n.com")
    old_gen = run.generation
    bump_generation(run.id)
    with patch.object(tasks, "call_llm", return_value=_REPORT):
        tasks.finalize_run.run([], run.id, old_gen)  # superseded
    run.refresh_from_db()
    assert run.status == "blue"  # not overwritten by the stale callback


def test_reaper_terminalizes_stuck_run():
    run = Run.objects.create(input_text="Acme", input_kind="name",
        status="blue", started_at=timezone.now() - timedelta(hours=1))
    Category.objects.create(run=run, key="news", status="running")
    tasks.reap_stuck_runs()
    run.refresh_from_db()
    assert run.status == "red"  # no items anywhere
    assert run.ended_at is not None
    assert Category.objects.get(run=run, key="news").status == "red"


def test_reaper_ignores_fresh_run():
    run = Run.objects.create(input_text="Acme", input_kind="name",
        status="blue", started_at=timezone.now())
    Category.objects.create(run=run, key="news", status="running")
    tasks.reap_stuck_runs()
    run.refresh_from_db()
    assert run.status == "blue"  # not stale enough to reap


def test_reaper_rolls_up_green_when_categories_done():
    # All categories finished green but finalize died -> reaper rolls up green.
    run = Run.objects.create(input_text="Acme", input_kind="name",
        status="blue", started_at=timezone.now() - timedelta(hours=1))
    cat = Category.objects.create(run=run, key="news", status="green")
    ContentItem.objects.create(category=cat, title="t", url="https://n.com/a",
        canonical_url="https://n.com/a", source="n.com")
    tasks.reap_stuck_runs()
    run.refresh_from_db()
    assert run.status == "green"


def test_report_prompt_enforces_item_cap(monkeypatch):
    monkeypatch.setenv("REPORT_MAX_ITEMS_TOTAL", "2")
    run = Run.objects.create(input_text="Acme", input_kind="name")
    cat = Category.objects.create(run=run, key="news")
    items = []
    for i in range(5):
        items.append(("news", ContentItem(category=cat, title=f"T{i}",
            url=f"https://n.com/{i}", canonical_url=f"https://n.com/{i}",
            source="n.com", snippet="s")))
    prompt = tasks._report_prompt(run, items)
    assert prompt.count("::") == 2  # only 2 item lines survive the cap


def test_report_prompt_includes_sentiment_and_pos_neg_instruction():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    cat = Category.objects.create(run=run, key="news")
    items = [("news", ContentItem(category=cat, title="Great launch",
             url="u", canonical_url="u", source="techcrunch.com", snippet="s",
             sentiment_score=0.7, sentiment_label="positive"))]
    prompt = tasks._report_prompt(run, items)
    # Instruction asks for the positive/negative source+theme breakdown.
    assert "POSITIVE coverage" in prompt and "NEGATIVE coverage" in prompt
    # The item line carries its sentiment label and source.
    assert "(positive; techcrunch.com)" in prompt


def test_stale_task_after_delete_is_superseded():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    Category.objects.create(run=run, key="news", status="pending")
    gen = run.generation
    run_id = run.id
    run.delete()  # run row gone
    with patch.object(tasks, "research_category") as rc:
        tasks.run_category.run(run_id, gen, "news")  # must not raise/recreate
    rc.assert_not_called()
    assert not Run.objects.filter(id=run_id).exists()


def test_subtask_persists_sentiment():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"],
                             started_at=timezone.now())
    Category.objects.create(run=run, key="news", display_order=0)

    def fake(company, key, months, exclusion, run_id=None):
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s",
                "sentiment_score": 0.5, "sentiment_label": "positive",
                "sentiment_summary": "Upbeat coverage."}],
                "summary": "s"}

    with patch.object(tasks, "research_category", side_effect=fake):
        tasks.run_category.run(run.id, run.generation, "news")

    item = ContentItem.objects.get(category__run=run)
    assert item.sentiment_score == 0.5
    assert item.sentiment_label == "positive"
    assert Category.objects.get(run=run, key="news").status == "green"


def test_subtask_sentiment_unknown_still_green():
    # A sentiment failure surfaces as None/None on the item (score_sentiments is
    # non-fatal); the category must still finish green (§5.4/§8, design §8).
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"],
                             started_at=timezone.now())
    Category.objects.create(run=run, key="news", display_order=0)

    def fake(company, key, months, exclusion, run_id=None):
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s",
                "sentiment_score": None, "sentiment_label": None,
                "sentiment_summary": None}],
                "summary": "s"}

    with patch.object(tasks, "research_category", side_effect=fake):
        tasks.run_category.run(run.id, run.generation, "news")

    assert Category.objects.get(run=run, key="news").status == "green"
    assert ContentItem.objects.get(category__run=run).sentiment_score is None
