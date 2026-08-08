# Future improvements

Items deliberately deferred from the initial design (`plans/INITIAL.md`). They
are recorded here so they are not lost, and so the initial build stays focused.

## Product / research quality
- Per-item LLM summaries (one short blurb per content item). Deferred for cost;
  items currently show Tavily's own snippet.
- Cross-run entity resolution (recognising the same company across runs).
- Relevance ranking / scoring of items beyond recency ordering (the initial
  build ranks and cap-trims by published_at desc, undated last, insertion order).
- Stricter time-window handling for undated items: instead of counting them
  normally (the initial best-effort policy), either exclude undated items from
  making a category non-empty, or include them only when the query/window
  context strongly implies recency.
- Configurable per-run LLM overrides from the UI (currently env-only).
- Stronger structured-output enforcement for LLM call-points. The build now uses
  the OpenAI-compatible JSON mode (`response_format={"type":"json_object"}`, env
  `LLM_JSON_MODE`) plus strict parsers. A further step is a schema-constrained
  decoder / a library such as `instructor` (or provider `json_schema` mode) with
  a bounded retry, to eliminate the remaining shape/truncation failure modes
  rather than degrading the category to an error.
- Per-category Tavily topic tuning. The initial build hardcodes `topic="news"`
  because Tavily's `days` time-window only applies under that topic; non-news
  categories (podcasts, newsletters, forums) would benefit from category-specific
  topic/window strategies.

## Delivery / real-time
- Server-Sent Events or WebSockets for push updates (currently polling).
- Progressive streaming of the executive overview as tokens arrive.

## Scale / persistence
- Move from SQLite to PostgreSQL for higher write concurrency.
- Pagination / infinite scroll for very large run lists and result sets
  (initial build uses a simple newest-first limit).
- Full-text search across stored results.

## Reliability
- Redeliver killed Celery tasks (`task_acks_late=True`) with per-category
  attempt tokens / status compare-and-set to make same-generation duplicate
  execution safe. The initial build instead sets `task_acks_late=False` and lets
  the reaper own lost-worker recovery (simpler for a local app).

## Operations
- Authentication, user accounts, multi-tenancy (out of scope per PRD).
- Hosting, deployment, CI/CD (out of scope per PRD).
- Centralised, rotated, multi-process-safe log aggregation.
- Metrics/observability (per-call-point latency and token dashboards).

## Nice-to-have UX
- Bulk actions on the home list (multi-select delete).
- Export a run's results (CSV / JSON / PDF).
- Filtering/sorting of items within a category in the run-view.
