# Sentiment Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score the sentiment of each found item and show a run-level line chart
of average sentiment per month over the run's lookback window, plus a per-item
sentiment label.

**Architecture:** A new non-fatal `SENTIMENT` LLM call-point scores each kept
item inside the existing per-category pipeline; the two new nullable fields
persist on `ContentItem` in the existing generation-fenced write; the run-detail
serializer computes a monthly timeline + summary server-side; the React run-view
renders a Recharts line chart and a per-item pill.

**Tech Stack:** Existing Drumbeat stack (Django + DRF, Celery, SQLite, React +
Vite + Vitest). Adds one frontend dependency: `recharts`.

**Source of truth:** `plans/SENTIMENT-DESIGN.md`. Base app design:
`plans/INITIAL.md` (section refs like "§5.4" point there).

## Global Constraints

- Python 3.13. No line of code or Markdown longer than **94 characters**; Python
  docstring first line ≤ 80.
- **Fail loud**, EXCEPT sentiment is deliberately **non-fatal / best-effort**
  (like IDENTITY, §5.4): a failed/malformed score → `null` sentiment, logged
  server-side, item kept, category never turned red, status unchanged (§8).
- All LLM calls go through `call_llm(name, ...)`; structured output through a
  `schemas.parse_*` function. Mock seams in tests: `call_llm`, `tavily_search`.
  No network in tests.
- Every task's DB write to `ContentItem` stays inside the existing
  generation-fenced per-category transaction (§5.7). No new write ordering.
- Counts/aggregates are computed **server-side** (§10/§11); the frontend never
  aggregates.
- Status is never colour alone: the per-item pill always carries the label text
  (§13). Run/category status logic is NOT changed by this feature.
- Commit at the end of every task. Run `pytest` (backend) and, for frontend
  tasks, `npx vitest run` in `frontend/`.
- Backend management commands need `DRUMBEAT_SKIP_CONFIG_CHECK=1` locally (the
  config check otherwise blocks them); `pytest.ini` already sets this for tests.

---

## File structure

- `research/schemas.py` — add `parse_sentiment` (Task 1).
- `research/models.py` + `research/migrations/0002_*.py` — two new
  `ContentItem` fields (Task 2).
- `research/pipeline.py` — `score_sentiments` + call in `research_category`
  (Task 3).
- `research/tasks.py` — persist the two fields in `_run_category_body` (Task 4).
- `research/serializers.py` — `sentiment_timeline`, `sentiment_summary`, and the
  two item fields (Task 5).
- `frontend/src/components/SentimentGraph.jsx` (new) + `package.json` (Task 6).
- `frontend/src/components/ContentItemRow.jsx` + `RunView.jsx` +
  `frontend/src/index.css` (Task 7).
- `.env-example`, `CLAUDE.md`, `plans/INITIAL.md` docs (Task 8).

## Progress tracker

| Task | Deliverable                                    | Status |
|------|------------------------------------------------|--------|
| 1    | `parse_sentiment` schema                       | DONE   |
| 2    | ContentItem sentiment fields + migration       | DONE   |
| 3    | `score_sentiments` pipeline integration        | DONE   |
| 4    | Subtask persists sentiment                     | DONE   |
| 5    | Serializer timeline + summary + item fields    | DONE   |
| 6    | Recharts + SentimentGraph component            | DONE   |
| 7    | Item pill + graph mounted in run-view          | DONE   |
| 8    | Config/docs + full gate                        | TODO   |

---

## Task 1: `parse_sentiment` schema

**Files:**
- Modify: `research/schemas.py`
- Test: `research/tests/test_schemas.py`

**Interfaces:**
- Consumes: `research.schemas._load`, `MalformedLLMOutput` (existing).
- Produces: `parse_sentiment(content: str) -> {"score": float|None,
  "label": "positive"|"neutral"|"negative"|None}`. Tolerant: clamps score to
  [-1, 1]; derives/overrides label from score; an unusable score → both `None`;
  only a non-JSON body raises `MalformedLLMOutput`.

- [ ] **Step 1: Write the failing tests**

Append to `research/tests/test_schemas.py` (add `parse_sentiment` to the import
line at the top of the file):

```python
def test_parse_sentiment_ok():
    d = parse_sentiment('{"score": 0.5, "label": "positive"}')
    assert d["score"] == 0.5 and d["label"] == "positive"


def test_parse_sentiment_clamps_score():
    assert parse_sentiment('{"score": 2.5, "label": "positive"}')["score"] == 1.0
    assert parse_sentiment('{"score": -9, "label": "negative"}')["score"] == -1.0


def test_parse_sentiment_derives_label_from_score():
    assert parse_sentiment('{"score": 0.4}')["label"] == "positive"
    assert parse_sentiment('{"score": -0.4}')["label"] == "negative"
    assert parse_sentiment('{"score": 0.0}')["label"] == "neutral"


def test_parse_sentiment_bad_label_is_derived():
    assert parse_sentiment('{"score": 0.4, "label": "great"}')["label"] \
        == "positive"


def test_parse_sentiment_unusable_score_is_unknown():
    d = parse_sentiment('{"score": "n/a", "label": "positive"}')
    assert d["score"] is None and d["label"] is None


def test_parse_sentiment_bool_score_is_unknown():
    d = parse_sentiment('{"score": true, "label": "positive"}')
    assert d["score"] is None and d["label"] is None


def test_parse_sentiment_non_json_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_sentiment("not json")


def test_parse_sentiment_non_object_json_is_unknown():
    # Valid JSON that is not an object (e.g. a bare number/array) -> unknown,
    # not an AttributeError.
    assert parse_sentiment("5") == {"score": None, "label": None}
    assert parse_sentiment("[1, 2]") == {"score": None, "label": None}
```

Update the existing import at the top of the file to include `parse_sentiment`:

```python
from research.schemas import (parse_query_planner, parse_report,
                              parse_category_summary, parse_curator,
                              parse_identity, parse_sentiment,
                              MalformedLLMOutput)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest research/tests/test_schemas.py -q`
Expected: FAIL (`ImportError: cannot import name 'parse_sentiment'`).

- [ ] **Step 3: Implement `parse_sentiment`**

Append to `research/schemas.py`:

```python
def _derive_sentiment_label(score):
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def parse_sentiment(content):
    """Tolerant sentiment parse -> {score in [-1,1] or None, label or None}.

    Non-fatal upstream (§5.4): an unusable score yields unknown sentiment
    rather than raising. Only a non-JSON body fails (via `_load`).
    """
    data = _load(content)
    if not isinstance(data, dict):  # valid JSON but not an object -> unknown
        return {"score": None, "label": None}
    raw = data.get("score")
    # bool is an int subclass in Python; exclude it explicitly.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return {"score": None, "label": None}
    score = max(-1.0, min(1.0, float(raw)))
    label = data.get("label")
    if label not in ("positive", "neutral", "negative"):
        label = _derive_sentiment_label(score)
    return {"score": score, "label": label}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest research/tests/test_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research/schemas.py research/tests/test_schemas.py
git commit -m "feat: tolerant parse_sentiment schema"
```

---

## Task 2: ContentItem sentiment fields + migration

**Files:**
- Modify: `research/models.py`
- Test: `research/tests/test_models.py`
- Create (generated): `research/migrations/0002_*.py`

**Interfaces:**
- Produces: `ContentItem.sentiment_score: float|None`,
  `ContentItem.sentiment_label: str|None` (both default `None`).

- [ ] **Step 1: Write the failing test**

Append to `research/tests/test_models.py`:

```python
def test_content_item_sentiment_defaults():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    cat = Category.objects.create(run=run, key="news")
    item = ContentItem.objects.create(
        category=cat, title="t", url="u", canonical_url="u", source="s")
    assert item.sentiment_score is None
    assert item.sentiment_label is None


def test_content_item_stores_sentiment():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    cat = Category.objects.create(run=run, key="news")
    item = ContentItem.objects.create(
        category=cat, title="t", url="u", canonical_url="u", source="s",
        sentiment_score=0.5, sentiment_label="positive")
    item.refresh_from_db()
    assert item.sentiment_score == 0.5 and item.sentiment_label == "positive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest research/tests/test_models.py -q`
Expected: FAIL (`TypeError: unexpected keyword 'sentiment_score'` / attribute
errors).

- [ ] **Step 3: Add the fields**

In `research/models.py`, in `class ContentItem`, add these two lines
immediately after the `display_order` field (before `class Meta`):

```python
    sentiment_score = models.FloatField(null=True, blank=True)
    sentiment_label = models.CharField(max_length=8, null=True, blank=True)
```

- [ ] **Step 4: Make the migration and run tests**

```bash
DRUMBEAT_SKIP_CONFIG_CHECK=1 python manage.py makemigrations research
pytest research/tests/test_models.py -q
```

Expected: a new `research/migrations/0002_*.py` is created; tests PASS.

- [ ] **Step 5: Commit**

```bash
git add research/models.py research/migrations/0002_*.py \
        research/tests/test_models.py
git commit -m "feat: ContentItem sentiment_score/label fields"
```

---

## Task 3: `score_sentiments` pipeline integration

**Files:**
- Modify: `research/pipeline.py`
- Test: `research/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `call_llm` (existing), `schemas.parse_sentiment` (Task 1).
- Produces: `score_sentiments(company, items, run_id=None, category_key=None)
  -> items` — mutates each item dict IN PLACE, setting `sentiment_score` and
  `sentiment_label` (both `None` on failure / when disabled / beyond the cap).
  `research_category` now calls it, so returned item dicts always carry the two
  keys — GENUINELY EXPECTED on every item downstream (Task 4 relies on this).
- Env: `SENTIMENT_ENABLED` (default `"1"`; `"0"` disables all scoring),
  `SENTIMENT_MAX_ITEMS` (default `"10"`, deliberately below the 20-item
  `MAX_ITEMS_PER_CATEGORY` so up-to-10 sequential per-item calls fit under the
  180s `task_soft_time_limit`).

- [ ] **Step 1: Write the failing tests**

Add `import pytest` to the top of `research/tests/test_pipeline.py` (it is not
imported yet and the soft-limit test below needs `pytest.raises`), then append:

```python
def test_score_sentiments_attaches(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "https://n.com/a", "source": "n.com",
              "published_at": None, "snippet": "s"}]
    out = {"content": '{"score": 0.6, "label": "positive"}',
           "tool_calls": [], "usage": None}
    with patch.object(pipeline, "call_llm", return_value=out):
        pipeline.score_sentiments("Acme", items, run_id=1, category_key="news")
    assert items[0]["sentiment_score"] == 0.6
    assert items[0]["sentiment_label"] == "positive"


def test_score_sentiments_failure_is_nonfatal(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm", side_effect=RuntimeError("boom")):
        pipeline.score_sentiments("Acme", items)  # must NOT raise
    assert items[0]["sentiment_score"] is None
    assert items[0]["sentiment_label"] is None


def test_score_sentiments_reraises_soft_time_limit(monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm", side_effect=SoftTimeLimitExceeded()):
        with pytest.raises(SoftTimeLimitExceeded):  # must NOT be swallowed
            pipeline.score_sentiments("Acme", items)


def test_score_sentiments_disabled_makes_no_calls(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "0")
    items = [{"title": "t", "url": "u", "source": "s",
              "published_at": None, "snippet": "s"}]
    with patch.object(pipeline, "call_llm") as llm:
        pipeline.score_sentiments("Acme", items)
    llm.assert_not_called()
    assert items[0]["sentiment_score"] is None


def test_score_sentiments_respects_cap(monkeypatch):
    monkeypatch.setenv("SENTIMENT_ENABLED", "1")
    monkeypatch.setenv("SENTIMENT_MAX_ITEMS", "1")
    items = [{"title": f"t{i}", "url": f"u{i}", "source": "s",
              "published_at": None, "snippet": "s"} for i in range(3)]
    out = {"content": '{"score": 0.2, "label": "neutral"}',
           "tool_calls": [], "usage": None}
    with patch.object(pipeline, "call_llm", return_value=out) as llm:
        pipeline.score_sentiments("Acme", items)
    assert llm.call_count == 1                 # only the first item scored
    assert items[1]["sentiment_score"] is None  # beyond the cap -> unknown
```

Also update the TWO existing `research_category` tests so the added SENTIMENT
calls do not change their mocked `call_llm` sequences: add
`monkeypatch.setenv("SENTIMENT_ENABLED", "0")` as the FIRST line of
`test_pipeline_filters_own_domain_and_summarizes` and
`test_pipeline_empty_yields_no_summary` (both already take `monkeypatch`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest research/tests/test_pipeline.py -q`
Expected: FAIL (`AttributeError: module 'research.pipeline' has no attribute
'score_sentiments'`).

- [ ] **Step 3: Implement `score_sentiments` and wire it in**

At the top of `research/pipeline.py`, add a logger and the soft-limit import
under the existing imports:

```python
import logging
from celery.exceptions import SoftTimeLimitExceeded

_log = logging.getLogger("drumbeat")
```

Add these two functions (place them just above `research_category`):

```python
def _sentiment_prompt(company, item):
    snip = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    return (
        f'Rate the sentiment toward "{company}" expressed by this item. '
        'Return JSON {"score": <number from -1 (very negative) to 1 (very '
        'positive)>, "label": "positive"|"neutral"|"negative"}.\n'
        f'Title: {item["title"]}\nSnippet: {item["snippet"][:snip]}')


def score_sentiments(company, items, run_id=None, category_key=None):
    """Attach sentiment_score/label to each item (best-effort, non-fatal).

    One LLM call per item, bounded by SENTIMENT_MAX_ITEMS. A per-item failure or
    a disabled feature leaves that item's sentiment None; it never raises and
    never affects category status (§5.4).
    """
    enabled = os.environ.get("SENTIMENT_ENABLED", "1") != "0"
    cap = int(os.environ.get("SENTIMENT_MAX_ITEMS", "10"))
    for idx, item in enumerate(items):
        item["sentiment_score"] = None
        item["sentiment_label"] = None
        if not enabled or idx >= cap:
            continue
        try:
            out = call_llm(
                "SENTIMENT",
                [{"role": "user", "content": _sentiment_prompt(company, item)}],
                json_object=True, run_id=run_id, category_key=category_key)
            data = schemas.parse_sentiment(out["content"])
            item["sentiment_score"] = data["score"]
            item["sentiment_label"] = data["label"]
        except SoftTimeLimitExceeded:
            # SoftTimeLimitExceeded IS an Exception; do NOT swallow it, or the
            # 180s soft limit is lost and the task grinds to the 210s hard
            # SIGKILL (stuck-blue). Let it propagate to the subtask boundary,
            # which marks the category red cleanly (§5.4/§5.5).
            raise
        except Exception as exc:  # non-fatal: unknown sentiment, keep the item
            _log.warning("sentiment scoring failed for %s: %s",
                         item.get("url"), exc)
    return items
```

In `research_category`, add the scoring call right after the item cap line
(`items = accepted[:max_items]`) and before the summary line:

```python
    items = accepted[:max_items]
    score_sentiments(company, items, run_id=run_id, category_key=category_key)
    summary = _summarize(company, category_key, items,
                         run_id=run_id) if items else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest research/tests/test_pipeline.py research/tests/test_curator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research/pipeline.py research/tests/test_pipeline.py
git commit -m "feat: per-item sentiment scoring (non-fatal, bounded)"
```

---

## Task 4: Subtask persists sentiment

**Files:**
- Modify: `research/tasks.py`
- Test: `research/tests/test_tasks.py`

**Interfaces:**
- Consumes: item dicts from `research_category` carrying `sentiment_score` /
  `sentiment_label` (Task 3).
- Produces: `_run_category_body` persists both fields on each `ContentItem`.

- [ ] **Step 1: Write the failing test**

Append to `research/tests/test_tasks.py`:

```python
def test_subtask_persists_sentiment():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"],
                             started_at=timezone.now())
    Category.objects.create(run=run, key="news", display_order=0)

    def fake(company, key, months, exclusion, run_id=None):
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s",
                "sentiment_score": 0.5, "sentiment_label": "positive"}],
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
                "sentiment_score": None, "sentiment_label": None}],
                "summary": "s"}

    with patch.object(tasks, "research_category", side_effect=fake):
        tasks.run_category.run(run.id, run.generation, "news")

    assert Category.objects.get(run=run, key="news").status == "green"
    assert ContentItem.objects.get(category__run=run).sentiment_score is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest research/tests/test_tasks.py::test_subtask_persists_sentiment -q`
Expected: FAIL (`sentiment_score` persists as `None` → `AssertionError`).

- [ ] **Step 3: Persist the fields**

In `research/tasks.py`, in `_run_category_body`, extend the `ContentItem(...)`
built inside `bulk_create` to include the two fields. Use direct `i[...]`
indexing (NOT `.get()`): `score_sentiments` (Task 3) sets both keys on EVERY
item, so they are genuinely expected — CLAUDE.md prefers `data[key]` over
`.get()` for expected fields, and a `KeyError` here should fail loud, not be
masked:

```python
            ContentItem(
                category=cat, title=i["title"], url=i["url"],
                canonical_url=urls_util.canonicalize_url_for_dedupe(i["url"]),
                source=i["source"], published_at=i["published_at"],
                snippet=i["snippet"], display_order=n,
                sentiment_score=i["sentiment_score"],
                sentiment_label=i["sentiment_label"])
```

Because the persist now requires the keys, update the ONE existing test fake
that returns items without them — `fake_research` in
`test_subtask_error_degrades_to_yellow` (research/tests/test_tasks.py:23-28) —
to include the two keys on its returned item (mirroring what `score_sentiments`
always produces):

```python
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s",
                "sentiment_score": None, "sentiment_label": None}],
                "summary": "sum"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest research/tests/test_tasks.py -q`
Expected: PASS (all task tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add research/tasks.py research/tests/test_tasks.py
git commit -m "feat: persist item sentiment in the category subtask"
```

---

## Task 5: Serializer timeline + summary + item fields

**Files:**
- Modify: `research/serializers.py`
- Test: `research/tests/test_sentiment_api.py` (new)

**Interfaces:**
- Consumes: prefetched `run.categories` / `category.items` (the detail view
  already prefetches `categories__items`).
- Produces on the run-detail payload:
  - `sentiment_timeline: [{month: "YYYY-MM", avg_score: float|None,
    item_count: int}]` — continuous months across the lookback window, from
    dated+scored items only.
  - `sentiment_summary: {overall_avg: float|None, scored_count: int,
    undated_scored_count: int, unknown_count: int}`.
  - Each item gains `sentiment_score`, `sentiment_label`.

- [ ] **Step 1: Write the failing tests**

Create `research/tests/test_sentiment_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest research/tests/test_sentiment_api.py -q`
Expected: FAIL (`KeyError: 'sentiment_timeline'`).

- [ ] **Step 3: Implement the serializer changes**

In `research/serializers.py`, add the import (top of file, with the other
imports):

```python
from django.utils import timezone
```

Add `sentiment_score` and `sentiment_label` to `ContentItemSerializer.Meta.
fields` (append both to the existing list).

Add two module-level helpers (above `RunDetailSerializer`):

```python
def _iter_months(start_ym, end_ym):
    """Yield (year, month) inclusive from start_ym to end_ym (both (y, m))."""
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def _window_start(ref, lookback_months):
    """First (year, month) of a lookback_months window ending in ref's month."""
    index = ref.year * 12 + (ref.month - 1) - (lookback_months - 1)
    return index // 12, index % 12 + 1
```

Add the two `SerializerMethodField`s to `RunDetailSerializer` (declare the
fields, add their names to `Meta.fields`, and implement the getters):

```python
    sentiment_timeline = serializers.SerializerMethodField()
    sentiment_summary = serializers.SerializerMethodField()
```

Add `"sentiment_timeline"` and `"sentiment_summary"` to
`RunDetailSerializer.Meta.fields`.

```python
    def _all_items(self, obj):
        for cat in obj.categories.all():          # prefetched -> no N+1
            for item in cat.items.all():
                yield item

    def get_sentiment_timeline(self, obj):
        ref = obj.started_at or timezone.now()
        start_ym = _window_start(ref, obj.lookback_months)
        buckets = {}
        for item in self._all_items(obj):
            if item.published_at is not None and \
                    item.sentiment_score is not None:
                key = (item.published_at.year, item.published_at.month)
                buckets.setdefault(key, []).append(item.sentiment_score)
        out = []
        for (y, m) in _iter_months(start_ym, (ref.year, ref.month)):
            scores = buckets.get((y, m), [])
            avg = round(sum(scores) / len(scores), 3) if scores else None
            out.append({"month": f"{y:04d}-{m:02d}", "avg_score": avg,
                        "item_count": len(scores)})
        return out

    def get_sentiment_summary(self, obj):
        scored, undated_scored, unknown = [], 0, 0
        for item in self._all_items(obj):
            if item.sentiment_score is None:
                unknown += 1
            else:
                scored.append(item.sentiment_score)
                if item.published_at is None:
                    undated_scored += 1
        overall = round(sum(scored) / len(scored), 3) if scored else None
        return {"overall_avg": overall, "scored_count": len(scored),
                "undated_scored_count": undated_scored,
                "unknown_count": unknown}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest research/tests/test_sentiment_api.py research/tests/test_api.py -q`
Expected: PASS. `test_detail_query_count_is_bounded` still holds unchanged: the
new getters iterate ONLY the already-prefetched `categories__items` relations
and read columns already in the row SELECT, so they add zero queries and the
`django_assert_max_num_queries(6)` bound stands.

- [ ] **Step 5: Commit**

```bash
git add research/serializers.py research/tests/test_sentiment_api.py \
        research/tests/test_api.py
git commit -m "feat: server-side sentiment timeline + summary in run detail"
```

---

## Task 6: Recharts + SentimentGraph component

**Files:**
- Modify: `frontend/package.json` (+ generated `package-lock.json`),
  `frontend/src/setupTests.js`
- Create: `frontend/src/components/SentimentGraph.jsx`
- Test: `frontend/src/components/__tests__/SentimentGraph.test.jsx`

**Interfaces:**
- Produces: `SentimentGraph({ timeline, summary })` — ALWAYS renders the headline
  (`summary.overall_avg`) and the coverage notes (`undated_scored_count`, and
  `unknown_count` when > 0); then renders a Recharts line chart of `avg_score`
  by `month` when ≥ 2 non-null points exist, or an inline empty line otherwise.
  The caller (Task 7) only mounts it when `summary.scored_count > 0`, so the
  headline/notes always have something meaningful to show.

- [ ] **Step 1: Add the dependency AND the ResizeObserver test shim**

In `frontend/package.json`, add to `"dependencies"`:

```json
    "recharts": "^2.13.0"
```

Recharts' `ResponsiveContainer` uses `ResizeObserver`, which jsdom does NOT
implement — without a shim the charted test throws `ResizeObserver is not
defined`. Add a minimal global stub to `frontend/src/setupTests.js` (append):

```js
// jsdom has no ResizeObserver; recharts' ResponsiveContainer needs it.
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
```

Then install and commit the lockfile BEFORE running Vitest (tests must never
implicitly fetch packages):

```bash
cd frontend && npm install && cd ..
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/__tests__/SentimentGraph.test.jsx`:

These tests assert only the headline / notes / empty-line TEXT, which render
OUTSIDE `ResponsiveContainer`. They deliberately do NOT assert on chart SVG
geometry — jsdom does no layout, so `ResponsiveContainer` yields a
zero-dimension chart and any SVG assertion would be meaningless/flaky. The tests
therefore verify branch selection and the coverage copy, not the pixels.

```jsx
import { render, screen } from "@testing-library/react";
import { SentimentGraph } from "../SentimentGraph";

test("shows inline empty line but keeps headline with <2 dated points", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: null, item_count: 0 }]}
      summary={{ overall_avg: 0.5, undated_scored_count: 2, unknown_count: 0 }}
    />,
  );
  expect(screen.getByText(/not enough dated/i)).toBeInTheDocument();
  expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument();
  expect(screen.getByText(/2 undated items/i)).toBeInTheDocument();
});

test("renders headline, undated + unknown notes when charted", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: -0.2, item_count: 2 }]}
      summary={{ overall_avg: 0.15, undated_scored_count: 3, unknown_count: 4 }}
    />,
  );
  expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument();
  expect(screen.getByText(/3 undated items/i)).toBeInTheDocument();
  expect(screen.getByText(/4 items could not be scored/i)).toBeInTheDocument();
});

test("omits the unknown note when unknown_count is 0", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: -0.2, item_count: 2 }]}
      summary={{ overall_avg: 0.15, undated_scored_count: 0, unknown_count: 0 }}
    />,
  );
  expect(screen.queryByText(/could not be scored/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run (in `frontend/`): `npx vitest run src/components/__tests__/SentimentGraph.test.jsx`
Expected: FAIL (cannot resolve `../SentimentGraph`).

- [ ] **Step 4: Implement `SentimentGraph`**

Create `frontend/src/components/SentimentGraph.jsx`:

```jsx
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
  ReferenceLine, CartesianGrid,
} from "recharts";

// Run-level average sentiment per month over the lookback window. The caller
// mounts this only when there is scored data (summary.scored_count > 0). The
// headline + coverage notes always render; the chart needs >= 2 dated points,
// otherwise an inline empty line replaces it (so overall/undated are never
// hidden — e.g. when every scored item is undated). Null months render as gaps.
export function SentimentGraph({ timeline, summary }) {
  const points = (timeline || []).filter((b) => b.avg_score !== null);
  const hasChart = points.length >= 2;
  const overall = summary?.overall_avg;
  return (
    <div className="sentiment-graph">
      <div className="sentiment-headline">
        Overall sentiment: <strong>{overall ?? "—"}</strong>
      </div>
      {hasChart ? (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={timeline} accessibilityLayer
                     margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} minTickGap={24} />
            <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
                   tick={{ fontSize: 12 }} width={36} />
            <ReferenceLine y={0} stroke="#888" />
            <Tooltip formatter={(v) => [v, "avg sentiment"]} />
            <Line type="monotone" dataKey="avg_score" stroke="#2f5bea"
                  connectNulls dot={{ r: 3 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="muted sentiment-empty-line">
          Not enough dated, scored items to chart a sentiment trend yet.
        </p>
      )}
      {summary?.undated_scored_count > 0 && (
        <p className="muted sentiment-note">
          {summary.undated_scored_count} undated items are scored but not on the
          timeline.
        </p>
      )}
      {summary?.unknown_count > 0 && (
        <p className="muted sentiment-note">
          {summary.unknown_count} items could not be scored.
        </p>
      )}
    </div>
  );
}
```

Note: the `.sentiment-empty` full-box style from the design is no longer used
(the empty state is now an inline line inside the graph card); Task 7's CSS adds
`.sentiment-empty-line` instead.

- [ ] **Step 5: Run tests to verify they pass, then commit**

Run (in `frontend/`): `npx vitest run`
Expected: PASS (all frontend tests).

```bash
git add frontend/package.json frontend/package-lock.json \
        frontend/src/setupTests.js \
        frontend/src/components/SentimentGraph.jsx \
        frontend/src/components/__tests__/SentimentGraph.test.jsx
git commit -m "feat: SentimentGraph component (recharts)"
```

---

## Task 7: Item pill + graph mounted in run-view

**Files:**
- Modify: `frontend/src/components/ContentItemRow.jsx`,
  `frontend/src/components/RunView.jsx`, `frontend/src/index.css`
- Test: `frontend/src/components/__tests__/ContentItemRow.test.jsx`,
  `frontend/src/components/__tests__/RunView.test.jsx`

**Interfaces:**
- Consumes: `item.sentiment_score`, `item.sentiment_label` (Task 5);
  `run.sentiment_timeline`, `run.sentiment_summary` (Task 5); `SentimentGraph`
  (Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/__tests__/ContentItemRow.test.jsx`:

```jsx
test("shows a sentiment pill for a scored item", () => {
  render(
    <ContentItemRow
      item={{ title: "H", url: "https://n.com/a", source: "n.com",
              is_undated: true, snippet: "s", sentiment_score: 0.6,
              sentiment_label: "positive" }}
    />,
  );
  expect(screen.getByText(/positive/i)).toBeInTheDocument();
  expect(screen.getByText(/\+0\.6/)).toBeInTheDocument();
});

test("shows a muted marker when sentiment is unknown", () => {
  render(
    <ContentItemRow
      item={{ title: "H", url: "https://n.com/a", source: "n.com",
              is_undated: true, snippet: "s", sentiment_score: null,
              sentiment_label: null }}
    />,
  );
  expect(screen.getByLabelText(/sentiment unknown/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (in `frontend/`): `npx vitest run src/components/__tests__/ContentItemRow.test.jsx`
Expected: FAIL (no pill text found).

- [ ] **Step 3: Add the pill to `ContentItemRow`**

In `frontend/src/components/ContentItemRow.jsx`, add this helper above the
`ContentItemRow` function:

```jsx
function SentimentPill({ score, label }) {
  if (score === null || score === undefined || !label) {
    return (
      <span className="sentiment-pill sentiment-unknown"
            aria-label="Sentiment unknown">
        —
      </span>
    );
  }
  const shown = score > 0 ? `+${score}` : `${score}`;
  return (
    <span className={`sentiment-pill sentiment-${label}`}>
      {label} {shown}
    </span>
  );
}
```

Then render it inside the existing `.item-meta` div (after the date/undated
span), so the row shows source · date · sentiment:

```jsx
        <SentimentPill score={item.sentiment_score} label={item.sentiment_label} />
```

- [ ] **Step 4: Mount the graph in `RunView`**

In `frontend/src/components/RunView.jsx`, add the import at the top:

```jsx
import { SentimentGraph } from "./SentimentGraph.jsx";
```

Render the graph in the non-empty branch, immediately BEFORE the
`<nav className="category-index" ...>` element (so it sits under the executive
overview and above the category index). Gate the mount on
`sentiment_summary.scored_count > 0` so a blue/in-progress run with nothing
scored yet, and a finished run where scoring was disabled or produced nothing,
simply omit the block (design §6 "hidden while blue with no data"):

```jsx
          {(run.sentiment_summary?.scored_count ?? 0) > 0 && (
            <SentimentGraph
              timeline={run.sentiment_timeline}
              summary={run.sentiment_summary}
            />
          )}
```

Add a test to `frontend/src/components/__tests__/RunView.test.jsx` verifying the
gate (append; `renderAt`/`api` helpers already exist in that file):

```jsx
test("shows the sentiment graph only when there is scored data", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 11, input_text: "Acme", status: "green",
    started_at: "2026-01-01T00:00:00Z", ended_at: "2026-01-02T00:00:00Z",
    executive_overview: "ok", total_item_count: 1, warnings: [],
    categories: [{ key: "news", status: "green", item_count: 1, items: [] }],
    sentiment_summary: { overall_avg: 0.3, scored_count: 2,
                         undated_scored_count: 0, unknown_count: 0 },
    sentiment_timeline: [
      { month: "2026-01", avg_score: 0.3, item_count: 1 },
      { month: "2026-02", avg_score: 0.3, item_count: 1 }],
  });
  renderAt(11);
  await waitFor(() =>
    expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument());
});

test("hides the sentiment graph when nothing is scored", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 12, input_text: "Acme", status: "green",
    started_at: "2026-01-01T00:00:00Z", ended_at: "2026-01-02T00:00:00Z",
    executive_overview: "ok", total_item_count: 1, warnings: [],
    categories: [{ key: "news", status: "green", item_count: 1, items: [] }],
    sentiment_summary: { overall_avg: null, scored_count: 0,
                         undated_scored_count: 0, unknown_count: 0 },
    sentiment_timeline: [{ month: "2026-01", avg_score: null, item_count: 0 }],
  });
  renderAt(12);
  // Wait on an unambiguous element ("News articles" appears in BOTH the index
  // nav and the section head, so getByText would match multiple).
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /refresh/i }))
      .toBeInTheDocument());
  expect(screen.queryByText(/overall sentiment/i)).not.toBeInTheDocument();
});
```

Note: the existing `RunView.test.jsx` fixtures omit `sentiment_summary`, so
`(run.sentiment_summary?.scored_count ?? 0) > 0` is `false` there and the graph
is not mounted — those tests are unaffected.

- [ ] **Step 5: Add styles**

First, let the item meta row wrap so the added pill never overflows on narrow
viewports (the row currently has two children; the pill is a third). In
`frontend/src/index.css`, change the `.item-meta` rule to add `flex-wrap: wrap;`
and `align-items: center;`:

```css
.item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 0.8rem;
  color: var(--muted);
  margin-top: 2px;
}
```

Then append the sentiment styles:

```css
.sentiment-graph {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  margin: 16px 0;
}

.sentiment-headline {
  font-size: 0.9rem;
  color: var(--muted);
  margin-bottom: 8px;
}

.sentiment-note {
  font-size: 0.8rem;
  margin: 8px 0 0;
}

.sentiment-empty-line {
  font-size: 0.9rem;
  margin: 8px 0;
}

.sentiment-pill {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  white-space: nowrap;
}

.sentiment-positive {
  color: var(--green);
  background: #eaf6ee;
}
.sentiment-neutral {
  color: var(--muted);
  background: #eef1f5;
}
.sentiment-negative {
  color: var(--red);
  background: #fbecea;
}
.sentiment-unknown {
  color: var(--muted);
}
```

- [ ] **Step 6: Run tests + build to verify, then commit**

Run (in `frontend/`): `npx vitest run` (expect PASS) and `npx vite build`
(expect success).

```bash
git add frontend/src/components/ContentItemRow.jsx \
        frontend/src/components/RunView.jsx frontend/src/index.css \
        frontend/src/components/__tests__/ContentItemRow.test.jsx \
        frontend/src/components/__tests__/RunView.test.jsx
git commit -m "feat: per-item sentiment pill and run-view graph"
```

---

## Task 8: Config/docs + full gate

**Files:**
- Modify: `.env-example`, `CLAUDE.md`, `plans/INITIAL.md`,
  `docs/FUTURE-IMPROVEMENTS.md`

**Interfaces:** none (documentation + verification only).

- [ ] **Step 1: Document the new env**

In `.env-example`, under the optional-tunables section, add:

```bash
# Sentiment scoring (per-item; see plans/SENTIMENT-DESIGN.md)
# SENTIMENT_ENABLED=1
# SENTIMENT_MAX_ITEMS=10   # per category; kept below the subtask soft limit
```

In the per-call-point overrides comment block of `.env-example`, add
`SENTIMENT` to the list of NAMEs (so `SENTIMENT_LLM_URL|API_KEY|MODEL|TOKENS|
TEMP` are documented like the others).

- [ ] **Step 2: Update ALL call-point enumerations + the broad-except invariant**

There are THREE places that enumerate the (previously five) call-points, plus
the broad-except invariant — update them together so the docs stay consistent:

1. `CLAUDE.md`, "LLM configuration convention": change the call-points list to
   `IDENTITY, QUERY_PLANNER, CURATOR, CATEGORY_SUMMARY, REPORT, SENTIMENT`.
2. `CLAUDE.md`, "Non-obvious invariants" → the broad-except bullet currently says
   the category subtask / fan-in callback / IDENTITY are the "ONLY three
   sanctioned broad-except sites". Add `score_sentiments` (inside the category
   subtask) as a fourth sanctioned non-fatal broad-except that re-raises
   `SoftTimeLimitExceeded` and marks no category red.
3. `plans/INITIAL.md` §6: change the sentence "There are **five** named
   call-points" (near line 349) to "**six**", and add a table row:
   `| SENTIMENT | Per-item sentiment score for the trend graph (non-fatal). |`.
   Add a line under §6 that SENTIMENT is best-effort/non-fatal like IDENTITY with
   its output contract in `plans/SENTIMENT-DESIGN.md` §3.1.
4. `plans/INITIAL.md` §14 (near line 756): add `SENTIMENT` to the list of
   optional per-call-point override NAMEs.
5. `plans/INITIAL.md` §22 (progress table): add a milestone row
   `|18 | Sentiment scoring + run-level trend graph | DONE |` (mark DONE when
   this plan completes) so the base progress table reflects the feature.

- [ ] **Step 3: Record deferred items in `docs/FUTURE-IMPROVEMENTS.md`**

Append a "Sentiment" subsection to `docs/FUTURE-IMPROVEMENTS.md` (the file's
purpose is "recorded here so they are not lost"), capturing what the design
(§1/§3) deferred:

```markdown
## Sentiment
- Per-category sentiment trend lines / a category toggle on the graph (the
  initial build ships a single run-level line only).
- A stored per-item sentiment rationale / explanation (only score + label are
  stored initially).
- Concurrent per-item scoring (the initial build scores sequentially inside the
  category subtask, bounded by SENTIMENT_MAX_ITEMS; parallelism would let the
  cap rise without approaching the subtask soft time limit).
- Incremental / cached sentiment across refreshes (a refresh re-scores from
  scratch, as it re-runs everything).
- Richer chart interactions (brushing, per-point drill-down, exportable series).
```

- [ ] **Step 4: Run the full gate**

```bash
./run_tests.sh
```

Expected: exit 0; all backend and frontend tests pass.

- [ ] **Step 5: Verify no long lines (incl. both plan docs)**

```bash
grep -rnE '.{95,}' --include="*.py" --include="*.jsx" --include="*.js" \
  --include="*.md" research frontend/src plans/SENTIMENT-DESIGN.md \
  plans/SENTIMENT-IMPLEMENTATION.md docs/FUTURE-IMPROVEMENTS.md \
  .env-example CLAUDE.md | grep -v node_modules
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add .env-example CLAUDE.md plans/INITIAL.md docs/FUTURE-IMPROVEMENTS.md \
        plans/SENTIMENT-IMPLEMENTATION.md
git commit -m "docs: SENTIMENT call-point, invariant, env, and deferrals"
```

---

## Self-review notes

- Spec coverage: representation (T1/T2), per-item non-fatal compute (T1/T3),
  bounded + toggle (T3), persistence in the fenced write (T4), server-side
  timeline/summary + item fields (T5), Recharts chart + empty state (T6),
  per-item pill + graph placement + undated note (T7), config/docs (T8). Status
  invariance is asserted in T4 (`status == "green"` after a scored subtask) and
  by NOT touching `status.py`.
- Type consistency: `score_sentiments` sets `sentiment_score`/`sentiment_label`
  on every item (T3) → persisted via `i["..."]` (T4, keys always present) →
  serialized on items and aggregated (T5) → consumed as
  `run.sentiment_timeline`/`sentiment_summary` and
  `item.sentiment_score`/`sentiment_label` (T6/T7). `parse_sentiment` returns
  `{"score", "label"}` (T1) consumed in T3.
- Non-fatal guarantee: `score_sentiments` catches per-item exceptions and never
  turns a category red (T3), EXCEPT it deliberately re-raises
  `SoftTimeLimitExceeded` so a genuine timeout still marks the category red
  cleanly at the subtask boundary rather than being masked (T3). Status
  computation (`status.py`) is untouched, asserted by T4's `status == "green"`.
- Review rounds (2026-08-09) folded in: recharts needs a `ResizeObserver` shim
  in `setupTests.js` (T6); the graph is gated on `scored_count > 0` and always
  shows headline + notes (T6/T7); `SoftTimeLimitExceeded` re-raise + lower cap
  default (T3); `data[key]` not `.get()` (T4); all call-point enumerations and
  the broad-except invariant updated together, deferrals recorded (T8).
