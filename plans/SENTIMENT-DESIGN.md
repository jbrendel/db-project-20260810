# Drumbeat — Sentiment Graph: Design

Status: design/spec. Date: 2026-08-09.

An additive feature on top of the shipped Drumbeat app (`plans/INITIAL.md`).
Scores the sentiment of each found item and shows a run-level trend line of
average sentiment over the run's lookback window. Terminology and invariants
from `plans/INITIAL.md` apply unless overridden here.

## 1. Purpose and scope

Give the user a quick read on how third-party sentiment about a company has
developed over the selected window (default 36 months): each item is scored, and
the run-view shows a single monthly-average trend line plus a per-item sentiment
label.

In scope: per-item sentiment scoring, server-side monthly aggregation, a
run-level line chart, per-item sentiment labels, honest coverage reporting.

Out of scope (YAGNI): per-category sentiment lines / toggles, a stored per-item
sentiment rationale, sentiment-driven changes to run/category status, re-scoring
outside a normal re-run.

## 2. Sentiment representation (decision)

Each item carries:
- `sentiment_score` — float in [-1.0, +1.0]; -1 very negative, +1 very positive.
  `null` when unknown/unscored.
- `sentiment_label` — one of `positive` / `neutral` / `negative`; `null` when
  unknown. Derived from the score when the model omits or mislabels it.

Numeric scores average cleanly for the monthly trend; the label drives the
per-item chip colour.

## 3. Compute model (decision): per-item, best-effort, non-fatal

Sentiment is scored with **one LLM call per kept item** (the user's chosen
accuracy/cost trade-off), through the single `call_llm()` seam — a NEW sixth
call-point, `SENTIMENT`.

- `SENTIMENT` resolves `SENTIMENT_LLM_*` env with fallback to `DEFAULT_LLM_*`,
  exactly like the other call-points. JSON mode (`json_object=True`) is on.
- **Non-fatal, mirroring IDENTITY (INITIAL.md §5.4/§19).** A failed or malformed
  sentiment call sets that item's `sentiment_score`/`sentiment_label` to `null`,
  is logged server-side (never shown to the user), and does NOT turn the category
  red or change any status. Sentiment never affects completeness (INITIAL.md §8
  is unchanged).
- **Bounded.** Scoring runs on the already-curated, already-capped kept items,
  further bounded by `SENTIMENT_MAX_ITEMS` (default = `MAX_ITEMS_PER_CATEGORY`).
  A global `SENTIMENT_ENABLED` toggle (default `1`) disables the whole feature
  (no calls, no chart) for cost control.
- **Latency note.** Per-item calls are sequential inside the category subtask, so
  a busy category gains latency. `SENTIMENT_MAX_ITEMS` and the existing
  `task_soft_time_limit` bound the worst case; the cap is tunable.

### 3.1 Structured output contract

`SENTIMENT` -> `{ score: number in [-1,1], label: "positive"|"neutral"|
"negative" }`. Parsed tolerantly (like IDENTITY, since it is non-fatal):
- non-numeric / out-of-range `score` is clamped to [-1, 1]; a wholly unusable
  score makes the whole result unknown (`null`/`null`);
- a missing or invalid `label` is derived from the score (>= +0.15 positive,
  <= -0.15 negative, else neutral);
- only a non-JSON body fails the parse (caught as best-effort -> `null`).

## 4. Pipeline integration

`research_category` (INITIAL.md §5.2), after the curator loop and the
`MAX_ITEMS_PER_CATEGORY` cap, scores the kept items:
- a new pure helper `score_sentiments(company, items, run_id, category_key)`
  calls `SENTIMENT` per item (title + snippet + company as context), attaches
  `sentiment_score` / `sentiment_label` to each item dict, and on any per-item
  exception sets both to `null` and logs a warning. It respects
  `SENTIMENT_ENABLED` and `SENTIMENT_MAX_ITEMS`.
- item dicts flow unchanged to the subtask, which persists the two new fields on
  `ContentItem` in the same generation-fenced write (INITIAL.md §5.7). No new DB
  write ordering; sentiment is written with the items.

## 5. Aggregation (server-side; INITIAL.md §10/§11 "frontend never counts")

`RunDetailSerializer` gains two computed fields, built from the prefetched
categories/items (no N+1):

- `sentiment_timeline`: a continuous list of monthly buckets spanning the run's
  lookback window, `[{ month: "YYYY-MM", avg_score: float|null, item_count:
  int }]`. Buckets are computed from **dated, scored** items only
  (`published_at` not null AND `sentiment_score` not null). A month with no such
  items carries `avg_score: null`, `item_count: 0`, so the x-axis is continuous
  and gaps are explicit. Range: from the first day of the month `lookback_months`
  before the run's reference date, through the current month.
- `sentiment_summary`: `{ overall_avg: float|null, scored_count: int,
  undated_scored_count: int, unknown_count: int }`. `overall_avg` is the mean of
  all scored items' scores (dated and undated); the counts make coverage honest —
  undated items are scored but excluded from the line, and unscored/unknown items
  are reported, not hidden.

`ContentItemSerializer` gains `sentiment_score` and `sentiment_label`.

The lookback reference date is the run's `started_at` (falling back to now if
absent), so the window matches what was searched.

## 6. Frontend (React + Recharts)

- Add `recharts` as a frontend dependency (well-established; commit the updated
  lockfile).
- `SentimentGraph` component in the run-view, placed directly below the executive
  overview and above the category index. A responsive Recharts `LineChart` of
  `avg_score` by `month`, y-axis fixed to [-1, 1], a reference line at 0, a
  tooltip showing month / average / item count, and colour keyed to sign. Empty
  months (null avg) render as gaps. When fewer than 2 dated+scored points exist,
  the component shows a compact empty state ("Not enough dated, scored items to
  chart a trend yet") instead of a chart.
- A headline near the chart shows `sentiment_summary.overall_avg` as a label +
  value; a one-line note reports `undated_scored_count` ("N undated items are
  scored but not on the timeline") and `unknown_count` when > 0.
- `ContentItemRow` gains a small sentiment pill: green (positive) / grey
  (neutral) / red (negative) with the label and score, or a muted "—" when
  unknown. Colour is never the only signal — the label text is always present
  (WCAG 1.4.1, consistent with INITIAL.md §13).
- The graph is hidden while the run is blue and no scored data exists yet; it
  appears once there is data, and updates on the normal ~2s poll.

## 7. Status, config, and invariants

- Run/category **status computation is unchanged** (INITIAL.md §8). Sentiment is
  informational and non-fatal.
- New env (all optional, documented in `.env-example`): `SENTIMENT_ENABLED`
  (default `1`), `SENTIMENT_MAX_ITEMS` (default = `MAX_ITEMS_PER_CATEGORY`),
  `SENTIMENT_LLM_URL|API_KEY|MODEL|TOKENS|TEMP` (fall back to `DEFAULT_LLM_*`).
- Generation fencing, the three broad-except boundaries, and write ordering are
  all unchanged; sentiment persists inside the existing per-category fenced
  write.

## 8. Testing

- `schemas.parse_sentiment`: valid; out-of-range clamped; missing/invalid label
  derived from score; non-JSON -> raises (caught upstream as best-effort null).
- `pipeline.score_sentiments`: attaches score/label to items; a failing item ->
  null/null and does not raise; respects `SENTIMENT_ENABLED=0` (no calls) and
  `SENTIMENT_MAX_ITEMS`.
- Subtask persistence: scored items store `sentiment_score`/`sentiment_label`;
  a sentiment failure never marks the category red.
- Serializer: monthly bucketing over the window (dated+scored only), continuous
  months with null gaps, undated excluded from the line but counted in
  `undated_scored_count`, `overall_avg` across all scored items, empty case.
- Frontend: `SentimentGraph` renders points and the <2-point empty state;
  `ContentItemRow` pill for positive / negative / unknown.

## 9. Files touched

- `research/models.py` (+2 fields) and a new migration.
- `research/schemas.py` (`parse_sentiment`), `research/pipeline.py`
  (`score_sentiments` + call in `research_category`), `research/serializers.py`
  (timeline/summary + item fields), `research/config` docs.
- `frontend/src/components/SentimentGraph.jsx` (new), `ContentItemRow.jsx`
  (pill), `RunView.jsx` (mount the graph), `package.json` (+recharts).
- Tests alongside each unit; `.env-example` updated.
