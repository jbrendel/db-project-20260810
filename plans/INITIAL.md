# Drumbeat — Company Research App: Design

Status: design/spec (not an implementation plan). Date: 2026-08-07.
Revision: 6 (incorporates adversarial review rounds 1-4 and external Codex
review 1, `plans/INITIAL-codex-feedback-1.md`).

This document is the agreed design derived from `plans/PRD-initial.md` plus the
brainstorming and review decisions recorded below. It is decision-complete.
Deferred items live in `docs/FUTURE-IMPROVEMENTS.md`. Implementation progress is
tracked in Section 22 of this document.


## 1. Purpose and scope

Build a locally-run web app that, given a company **name or homepage URL**,
launches a background job to find third-party content about the company from a
**configurable recent time window (default: last 36 months)**, and presents the
results in a clean, reviewable, categorised list.

In scope: local-only operation, background research jobs (multiple concurrent),
categorised results with per-category and run-level summaries, live progress,
strict fail-loud validation and configuration.

Out of scope (per PRD): authentication, hosting, CI/CD. See
`docs/FUTURE-IMPROVEMENTS.md` for other deferrals.

Note on "name and/or URL": the PRD's UX section specifies a single input field
that "can hold either". We honour that single-field design. Supplying a URL is
preferred because the official domain is then derived directly and the LLM
IDENTITY step is skipped. Supplying a name and a URL simultaneously is not
supported by the single-field form; this is a deliberate, minor deviation from
the PRD's "and/or" phrasing, in favour of the PRD's own explicit UX instruction.


## 2. Content: what we look for and what we exclude

Core content types (each is a category, always searched):
- News articles
- Trade publications
- Blog posts (third-party)
- Press releases
- Major social posts
- Newsletters
- Podcasts

Excluded content:
- Product review / comparison pages
- Ecommerce pages
- The company's own channels (own website, blog, LinkedIn, etc.)
- Link aggregator sites

Borderline categories are opt-in. The New-run form shows checkboxes for extra
borderline sources (e.g. Reddit and similar forums). Each ticked checkbox adds
an extra category to the fan-out. Borderline categories are treated differently
from core categories when computing run status (Section 8).


## 3. Technology stack

Fixed by the PRD: Django + Django REST Framework (API only, no SSR); Redis +
Celery for async; SQLite; React served by Vite in development (Vite proxies
`/api/*` to Django); an OpenAI-compatible LLM API; Tavily for search.

Guardrail: boring, well-established technology only; no bleeding-edge
frameworks.

Decision D1 (resolved): target **Python 3.13**, not 3.14. Rationale: 3.14 is
too new to satisfy the boring-stack guardrail, and Django 5.2 LTS's supported
Python range does not reliably include 3.14 at time of writing (unverified
against the latest Django release notes — confirm during setup). The provided
3.14 virtualenv will be replaced with a 3.13 one during environment setup.

Pinned core versions (verify/adjust at setup): Django 5.2 LTS, DRF 3.15+,
Celery 5.4+, redis-py 5+, the `openai` Python SDK (OpenAI-compatible), and the
`tavily-python` client. Exact pins recorded in `requirements.txt`.


## 4. Process architecture and port propagation

`./start_all.sh` launches these processes, each on a **runtime-discovered free
port** (no standard port is assumed). Port selection is **deterministic**: each
service prefers a fixed, non-standard port (defaults Redis 6390, Django 8390,
Vite 5390; override with `DRUMBEAT_{REDIS,DJANGO,VITE}_PORT`) and only advances
to the next sequential free port if the preferred one is busy. This keeps the
Vite URL stable across restarts so the operator does not re-copy it each time,
while still avoiding fixed-port collisions between two checkouts.

1. Redis — Celery broker and result backend. Run as a Docker container with a
   **run-scoped, collision-free name** (e.g. `drumbeat-redis-<suffix>`; see
   Section 15), bound to a free host port (decision D2, resolved: Docker).
2. Django + DRF — serves the JSON API; runs DB migrations on start.
3. Celery worker with embedded beat (`-B`) — executes research tasks and runs
   the periodic reaper (Section 5.5).
4. Vite — React dev server; proxies `/api/*` to the Django port.

Port propagation (this is load-bearing — printing to a log is not enough): the
script discovers free ports and **exports them as environment variables** that
every child process inherits:
- `DJANGO_PORT`, `VITE_PORT`, `REDIS_PORT`
- `REDIS_URL` (derived), used for `CELERY_BROKER_URL` and result backend
- Django reads these from `os.environ`. `ALLOWED_HOSTS` includes
  `localhost`/`127.0.0.1` (host-only; ports are irrelevant). Because Vite
  proxies `/api/*` same-origin, CORS is normally unnecessary in dev; if it is
  enabled, `CORS_ALLOWED_ORIGINS` includes the chosen Vite origin. Celery reads
  `REDIS_URL` from env. `vite.config.js` reads `process.env.DJANGO_PORT` to set
  its proxy target and `process.env.VITE_PORT` for its own port.
Each chosen port is also printed to the log for the operator.


## 5. Research pipeline (core design)

A run executes as a Celery **chord**: a group of parallel per-category subtasks
plus a fan-in callback that runs after all of them settle.

### 5.1 Orchestration

```
create run (API):
  - validate input (Section 11); create Run row (status=blue, generation=1,
    started_at=now). started_at is set at SUBMISSION (Codex impl point 20), not
    after IDENTITY, so it reflects when the user's job began and the reaper's
    `started_at < cutoff` query catches runs stuck before IDENTITY finishes.
  - create ALL Category rows up-front (status=pending) for every selected
    category, so the run-view can render a spinner for not-yet-started ones
  - dispatch the parent task (via transaction.on_commit); store the parent task
    id on the Run (Section 11)

parent task:
  1. IDENTITY step (once, before fan-out) -- resolve official domain(s) so
     own channels can be excluded. NON-FATAL (Section 5.4).
       - input_kind == url  -> derive registrable domain directly (no LLM)
       - input_kind == name -> call_llm("IDENTITY") + a Tavily lookup
  2. chord: fan out one subtask per selected category (Section 5.2)
  3. fan-in callback after all subtasks settle (Section 5.3)
```

### 5.2 Category subtask

Each subtask wraps its ENTIRE body in a top-level try/except (Section 5.4) and
always returns a normal value, so the chord always completes.

```
category subtask(run_id, generation, category_key):
  - if run.generation != generation: return early (superseded; Section 5.7)
  - set category status = running AND set started_at -- this write is itself
    generation-fenced (via the first-statement Run-row guard, Section 5.7), so a
    stale task cannot revive a category on an already-terminalized run
  1. call_llm("QUERY_PLANNER") -> a small set of targeted queries. The prompt
     MUST steer toward INDEPENDENT, THIRD-PARTY coverage ABOUT the company (per
     category intent), passing the resolved own-domain so the planner avoids
     queries that mainly surface the company's own channels. Otherwise a query
     like "Google blog posts" returns Google's own blogs, which the CURATOR
     then rejects wholesale, leaving the category empty. Pipeline LLM calls also
     carry run_id/category_key for log correlation (Section 7).
  2. curator loop (bounded; Section 5.6):
       - tavily_search(...) constrained to the time window (Section 9)
       - call_llm("CURATOR") with the Tavily tool schema available; it judges
         relevance, enforces exclusions, dedupes within the category, and MAY
         request another search (a tool call). The subtask executes the tool
         and re-invokes call_llm, up to CURATOR_MAX_ITERATIONS /
         CURATOR_MAX_SEARCHES.
  3. call_llm("CATEGORY_SUMMARY") -> one summary paragraph (skipped if zero
     items; summary stays null)
  - persist items + summary + ended_at, THEN flip category status off "running"
    (green if >=1 item, yellow if zero) -- all in ONE transaction, and the write
    is generation-fenced (Section 5.7) so a poll never sees a done category with
    no content (Section 12 invariant) and a superseded task cannot overwrite a
    newer generation
  - on any exception: persist category status=red + Category.error (also
    generation-fenced), return normally
```

### 5.3 Fan-in callback

A hard rule (Codex review point 1): NEVER hold a SQLite write transaction open
across an LLM call. `REPORT` is a network call; holding the single SQLite writer
lock across it would block every other category's writes and every poll. So the
callback reads and computes OUTSIDE any transaction, calls `REPORT`, and only
then opens one short generation-fenced transaction to write.

```
fan-in callback(run_id, generation):
  # --- no DB transaction held below until the final short write ---
  - if run.generation != generation: return early (superseded)
  - read current run/category/item state
  - compute the cross-category de-dup PLAN in memory: if the same
    `canonical_url` (Section 19.1) appears under multiple categories, keep it in
    the highest-priority category (fixed core order; core before borderline),
    plan to remove the others; compute each category's post-dedup count/status
  - build the bounded REPORT input in memory (respecting REPORT_MAX_* caps,
    Section 6.2)
  - if >=1 item total: call_llm("REPORT") -> overview text (OUTSIDE any txn).
    If zero items total: skip REPORT; use the fixed message
    ("No third-party content was found in the selected time window.")
  # --- one short generation-fenced transaction (Section 5.7) ---
  - open txn; re-check generation/status is still current (guard UPDATE); if not,
    discard the report result and return normally as superseded work
  - apply the planned de-dup mutations; a category emptied by de-dup flips
    green -> yellow AND has its summary nulled (Section 10). A partly-emptied
    category keeps its summary (minor staleness, not a status/count lie)
  - recompute run status from the now-current category states (Section 8)
  - write executive_overview + ended_at, THEN flip run status off blue -- a
    compare-and-set on status == 'blue', so the first terminal writer wins
    (callback vs reaper) and the second no-ops. Overview/ended_at are written
    before the status flip so the client never stops polling on a half-written
    run (Section 12 invariant); commit
  - the callback body is wrapped so a REPORT failure still sets a terminal status
    (yellow if any items exist, else red) with ended_at, via the same short txn
```

### 5.4 Deliberate, scoped exception to fail-loud

The fail-loud guardrail forbids defensive coding in general. The sanctioned
exceptions are broad `try/except Exception` at exactly three boundaries:
1. the **category-subtask boundary** (a raising header task fails the whole
   chord and the callback never runs, so it must catch and return normally);
2. the **fan-in callback body** (same chord reasoning; a REPORT failure must
   still set a terminal status);
3. the **IDENTITY step in the parent task**, which is deliberately non-fatal
   (Section 5.1/19): failure leaves `resolved_domain` null, records a warning on
   the Run, and lets the run proceed without own-domain exclusion.
Inside every boundary, code still fails loud (`data[key]`, `obj.attr`,
`call_llm` raising on bad config) up to the boundary, where the error is caught,
recorded (on Category or Run), and turned into a red/degraded status. These are
the only places broad exception handling is permitted.

**Supersession is not a failure (Codex review point 2).** The generation guard
(Section 5.7) and a missing run (deleted, Section 11) raise a dedicated internal
exception, `SupersededGeneration`, which is caught SEPARATELY and BEFORE the
broad `except`, and treated as normal, expected control flow — NOT as a category
or run failure. Rules, applying to category subtasks, the fan-in callback,
refresh, delete, and reaper races:
- a superseded task returns normally;
- it must NOT mark the category red;
- it must NOT alter run status;
- it is logged at debug/info level, never error;
- a run row that no longer exists on task startup or final write is treated
  identically to a superseded generation (the generation cannot be read, so
  "run missing" IS supersession);
- the task must not recreate any part of a deleted/reset run.
Only genuine errors (a real LLM/Tavily/DB fault, malformed output) fall through
to the broad `except` and become red/degraded status.

### 5.5 Reaper (watchdog for hung runs / worker death)

A prefork *child* death (typical OOM-kill of a task process) or a merely-slow
run leaves the chord counter incomplete, so a run could stay BLUE indefinitely.
A periodic reaper task (Celery beat, embedded via `-B`, interval
`REAPER_INTERVAL_SECONDS`) handles any run BLUE longer than
`RUN_MAX_DURATION_SECONDS`, in this order:
1. **Conditionally bump `Run.generation`** with a single guarded statement
   `UPDATE ... SET generation = generation + 1 WHERE id AND status='blue' AND
   started_at < cutoff RETURNING generation` (Codex impl point 5). If zero rows
   (the run already completed between the reaper's SELECT and this write), skip
   it — do NOT bump a just-finished run's generation. This fences out any
   late-completing callback/subtask from the old generation (Section 5.7).
2. Transition every still-non-terminal Category (`pending`/`running`) to `red`
   with `Category.error = "run timed out"`, so no category is left showing a
   perpetual spinner on a now-terminal run.
3. Compute the run's terminal status via the **normal Section 8 rollup** over
   the (now all-terminal) category statuses — NOT a crude "items>0" heuristic,
   which would wrongly demote a run whose categories all finished green and only
   the fan-in callback died.
4. Set `executive_overview` to a fixed message ("Run timed out; results below
   may be partial.") AND compare-and-set the run status off `blue` with
   `ended_at`, in one fenced transaction. Writing the overview here preserves the
   Section 12 invariant (a run never leaves `blue` with a null overview) on the
   reaper path too. The reaper does NOT run REPORT or the cross-category dedup
   pass, so a reaped run keeps the fixed message and may retain cross-category
   duplicate URLs — an accepted trade-off for a timeout safety net.
5. Best-effort-revoke outstanding tasks.
Subtasks also carry a Celery `soft_time_limit` so an individual stuck category
fails cleanly.

`RUN_MAX_DURATION_SECONDS` must be sized comfortably ABOVE the worst-case
healthy run. Since categories fan out in parallel and each subtask's
`soft_time_limit` already caps its whole planner+curator+summary chain, that
worst case is roughly IDENTITY + the single slowest subtask (~`soft_time_limit`)
+ REPORT — not a sum or product across categories. If set too low the reaper
fences out live, legitimate subtasks and silently discards their real results —
so it is a safety net, not a normal completion path.

Two reaper sweeps can overlap (beat re-dispatch before a slow sweep finishes);
this is harmless because each run's terminal write is a `status == 'blue'`
compare-and-set and the per-category red writes are idempotent.

Scope of this guarantee (stated honestly): the reaper needs a live worker to
run, so it covers child/task death and slow runs, NOT the death of the entire
worker master (embedded beat dies with it). `start_all.sh` therefore supervises
the worker and restarts it if it exits (Section 15); a total, unrecoverable
worker outage is surfaced to the operator via the tailed logs.

### 5.6 Curator loop bounds (fail-loud on breach)

Configurable, with defaults: `CURATOR_MAX_ITERATIONS` (default 3),
`CURATOR_MAX_SEARCHES` per category (default 5). When a bound is reached the
loop terminates and keeps what it has found (it does not silently keep looping).
These bounds prevent runaway Tavily/LLM cost across many concurrent runs.

### 5.7 Generation fencing (the authoritative anti-clobber mechanism)

`Run.generation` is the single source of truth for "which run attempt is
current." Refresh (Section 11) and the reaper (Section 5.5) bump it. Task
`revoke` is treated as best-effort only (under prefork it cannot reliably stop an
already-running task, and `terminate=True` risks killing a sibling run's task),
so fencing — not revocation — is what guarantees correctness.

Every write a task makes is performed inside one transaction that begins with a
**generation-conditional compare-and-set whose affected-row count is checked**:
`UPDATE run SET ... WHERE id = :id AND generation = :g`. If it affects **zero
rows** (generation no longer current), the code **raises to roll back the entire
transaction**, discarding any `ContentItem` inserts made in the same
transaction. This is essential: a zero-row `UPDATE` is a successful SQL no-op,
NOT an error, so without the rowcount check the surrounding inserts would still
commit. Because `ContentItem`/`Category` rows carry no generation of their own,
a task whose payload touches only those child rows MUST issue a dedicated
**`Run`-row guard UPDATE as the very first statement of its write transaction**
(e.g. `UPDATE run SET generation = generation WHERE id = :id AND generation = :g`)
and abort on zero rows. That guard, rolled back atomically with the child-row
writes, is what actually fences the inserts. "Every write" below means literally
every DB write a task makes — the top-of-task set-running/`started_at`, each
dedup mutation, and the final persist — all occur inside such a guarded
transaction, never as bare unfenced statements.

Do NOT rely on `SELECT ... FOR UPDATE` — Django's SQLite backend silently
ignores it, so a "select-then-write" re-check is a real TOCTOU race on SQLite.
The single-statement compare-and-set (correct and atomic under SQLite's single
writer + WAL + `busy_timeout`) is the only sanctioned fencing form.

The top-of-task check ("if run.generation != generation: return early") is a
cheap optimization only; the transactional rowcount-abort above is the actual
protection. `generation` is always incremented as an atomic SQL expression
(`generation = generation + 1`, i.e. a Django F-expression), never a
read-modify-write in Python, so overlapping refresh/reaper bumps cannot lose an
update.

Terminal status writes additionally compare-and-set on `status == 'blue'`
(matched in the same `WHERE`), so exactly one writer — callback or reaper — sets
the terminal state and the loser no-ops.

Implementation note: this whole mechanism relies on the DB reporting the
matched-row count of the guard `UPDATE` (Django's `cursor.rowcount`). SQLite
reports it correctly even for a value-unchanged `UPDATE`; confirm this holds in
the chosen driver during milestone 7 (Section 22).


## 6. LLM call-points and `call_llm()`

There are **six** named call-points, each independently configurable:

| Name             | Purpose                                             |
|------------------|-----------------------------------------------------|
| IDENTITY         | Resolve official company domain (name-only input).  |
| QUERY_PLANNER    | Company + category -> THIRD-PARTY search queries.   |
| CURATOR          | Filter/exclude/dedupe; may request more searches.   |
| CATEGORY_SUMMARY | One summary paragraph per category.                 |
| REPORT           | One run-level executive overview.                   |
| SENTIMENT        | Per-item sentiment score for the trend graph.       |

All LLM interaction goes through a single function, `call_llm(name, ...)`.
`SENTIMENT` is best-effort/non-fatal like IDENTITY (a failed/malformed score
yields `null` sentiment, never a red category); its output contract and the
run-level trend graph are specified in `plans/SENTIMENT-DESIGN.md`.

- `name` selects the env-var set. For each call-point these may be defined:
  `<NAME>_LLM_URL`, `<NAME>_LLM_API_KEY`, `<NAME>_LLM_MODEL`,
  `<NAME>_LLM_TOKENS`, `<NAME>_LLM_TEMP`.
- Each variable independently falls back to the corresponding `DEFAULT_LLM_*`.
  All five `DEFAULT_LLM_*` are required (Section 14).
- `call_llm` is **single-shot** (one request → one response). It does NOT run a
  tool loop internally. When a call may use tools (CURATOR), the caller passes
  the tool schema and inspects the returned tool-call requests; the caller (the
  category subtask) executes the tool and calls `call_llm` again. This keeps
  Section 7's "one call = one logged prompt/response" model intact and confines
  the agentic control flow to the subtask.
- The OpenAI-compatible client is instantiated **lazily, per worker process**
  (not at import time), to avoid Celery prefork inheriting sockets/pools.

### 6.1 Structured output contracts (Codex review point 3)

Each structured call-point has a strict output schema, so implementation never
drifts into prompt-specific string scraping. Where the OpenAI-compatible
endpoint supports JSON schema / structured output, use it; otherwise use a
strict, tested parser (the only sanctioned mechanical repair is stripping a
surrounding Markdown code fence, and only if the parser explicitly allows it).

- `IDENTITY` -> `{ official_domain: str|null, owned_profile_urls: [str],
  owned_social_handles: [str], confidence: "high"|"medium"|"low",
  matched: bool }`. `matched=false` / null domain is the defined no-match shape
  (non-fatal, Section 19). **IDENTITY is parsed TOLERANTLY** (unlike the
  load-bearing call-points below): because it is non-fatal and its only
  load-bearing output is `official_domain`, the parser SALVAGES a usable domain
  from real model variance — `confidence` returned as a number is normalised to
  the enum, `matched` returned as evidence rather than a bool is derived from the
  presence of a domain — instead of discarding a good `official_domain` and
  needlessly skipping own-channel exclusion. Only a non-JSON body fails. The
  prompt states the exact field types and gives a one-shot example to minimise
  the variance in the first place.
- `QUERY_PLANNER` -> `{ queries: [str] }`, at most `QUERY_PLANNER_MAX_QUERIES`,
  no commentary.
- `CURATOR` -> `{ accepted: [{url}], rejected: [{url, reason_code}],
  duplicates: [{url, duplicate_of}], tool_call: {...}|null, done: bool }`.
  `accepted` carries ONLY urls (the item metadata stays sourced from Tavily, so
  the LLM cannot rewrite titles/dates/snippets). `tool_call` is the optional
  request-another-search shape; `done` is the no-more-searches signal.
- `CATEGORY_SUMMARY` -> `{ summary: str }` (max length bounded).
- `REPORT` -> `{ executive_overview: str }` (max length bounded).

Malformed output is a fail-loud condition: it fails the current call-point and
degrades through the existing category/run failure path (Section 5.4). It is NOT
silently repaired beyond the fence-stripping noted above.

### 6.2 Volume and prompt-size caps (Codex review point 4)

Explicit caps bound cost, frontend readability, SQLite growth, log size, LLM
context, and worst-case latency. Tunables (defaults chosen at implementation):
`QUERY_PLANNER_MAX_QUERIES`, `TAVILY_RESULTS_PER_SEARCH`,
`MAX_CANDIDATES_PER_CATEGORY`, `MAX_ITEMS_PER_CATEGORY`, `MAX_SNIPPET_CHARS`,
`REPORT_MAX_ITEMS_TOTAL`, `REPORT_MAX_ITEM_SNIPPET_CHARS`.

When a cap is exceeded, the survivors are chosen deterministically by the item
display order: `published_at` descending, undated last, then insertion order
(Section 10). Richer relevance ranking is deferred
(`docs/FUTURE-IMPROVEMENTS.md`). Caps are enforced in code, never left to the
LLM's discretion.


## 7. LLM call logging

`call_llm()` writes detailed records to a **separate log file** distinct from
the general application log. Each call (each single-shot turn, including each
curator turn) logs: the model, start and end time, tokens used (when the
provider returns them), and the full prompt and full response.

Operational limits (Codex review point 11):
- Per-process log directory and naming convention; the file name includes the
  process id (multi-process-safe), rotated via `RotatingFileHandler` with a
  bounded max size and backup count.
- Every record carries correlating ids: `run_id`, `category_key` (when
  applicable), and a per-call request id.
- **Redaction**: API keys and `Authorization` headers are never written to the
  log (the prompt/response body is logged; auth material is stripped).
- Logging must never corrupt a run. If the log path is unusable, the app/worker
  **fails loud at startup**. A mid-run write/rotation error is caught, degrades
  to a warning on the app log, and does NOT fail the research task (the run's
  results matter more than a lost log line).


## 8. Run and category status model

Per-category status: `pending` (created, not started), `running`, `green`
(finished, >=1 item), `yellow` (finished, zero items), `red` (errored).
`pending` and `running` both render as a spinner in the UI ("still in progress").

Overall run status measures **research completeness**, not per-category content
abundance (Codex review point 5). Computed in the fan-in callback, or by the
reaper:
- GREEN: every selected category (core and borderline) finished cleanly, i.e.
  none errored or timed out, AND at least one item exists across the whole run.
  A category that legitimately finished with zero items ("None found") does NOT
  demote the run — many companies have no podcasts/newsletters/etc. in-window.
- YELLOW: at least one item exists across the run, but at least one category
  errored, timed out, or otherwise degraded (partial/incomplete research).
- RED: zero items across the whole run, OR every category errored. (Matches the
  PRD's Red = "failed completely, no information could be retrieved".)
- BLUE: still in progress.

Note this is a change from an earlier revision, where an empty core category
demoted the run to YELLOW; the completeness model above is the chosen semantics.

Each status has a text label and icon in the UI, never colour alone (Section 13):
- GREEN → "Complete" (check icon)
- YELLOW → "Partial (N of M)" (warning-triangle icon; N categories finished
  without error out of M). UI copy clarifies Partial means "some categories
  could not be fully researched", i.e. an error/timeout — NOT merely that a
  category found nothing.
- RED → "Failed" (error/x icon)
- BLUE → "Running" (spinner)


## 9. Time-window enforcement

The run's `lookback_months` is enforced in two layers:
1. Tavily search is constrained as tightly as its API allows (a day count
   derived from the window, or the nearest supported range). Tavily's native
   controls are coarse, so this is a first-pass filter, not exact.
2. Post-fetch filtering by `published_at` against `now - lookback_months`.

Missing dates: Tavily may return a result with no publish date. A missing date
maps to `published_at = None` (this is expected data, NOT a malformed-input
error — Section 16 must not be misapplied here).

Undated-item policy (Codex review point 8), chosen explicitly: undated items are
**kept, flagged as undated in the UI, and count normally** toward a category's
item count and the run's status. This means the time-window guarantee is
**best-effort**: an undated item can make a category non-empty and keep a run out
of RED even though its date is not confirmed in-window. Because of this, the UI
labels results as "dated or undated results from searches constrained to this
window", rather than implying every item is verified within the window. (The
stricter alternatives — undated items cannot make a category non-empty by
themselves, or recency-heuristic inclusion — are deferred;
`docs/FUTURE-IMPROVEMENTS.md`.)


## 10. Data model (SQLite)

**Run**
- `id`
- `input_text` — raw name or URL; the run's display "name".
- `input_kind` — `name` or `url` (detection in Section 11).
- `resolved_domain` — official registrable domain for own-channel exclusion
  (nullable).
- `owned_profile_urls` — JSON list of the company's own profile URLs on
  third-party domains (LinkedIn/X/YouTube/Medium/Substack/GitHub, etc.), from
  IDENTITY; used for deterministic own-channel exclusion (Section 19).
- `owned_social_handles` — JSON list of owned handles for the same purpose.
- `selected_categories` — JSON list of category keys for this run.
- `borderline_options` — JSON of which borderline checkboxes were ticked.
- `lookback_months` — integer window size; default 36; per-run.
- `status` — blue / green / yellow / red.
- `generation` — integer, bumped on each refresh/reap; stale tasks are fenced.
- `celery_task_ids` — JSON of the tracked task ids for best-effort revocation:
  the parent `start_run` id (stored at create) and the chord/`finalize` id
  (stored by `start_run`). Individual category subtask ids are NOT tracked;
  category-level revocation is not attempted — correctness rests on fencing, and
  the reaper owns lost-worker recovery (Codex impl point 4).
- `started_at`, `ended_at` (nullable until finished).
- `executive_overview` — text (nullable until REPORT / fixed message).
- `error` — nullable text for a run-level FAILURE (fatal).
- `warnings` — JSON list of non-fatal notices (e.g. IDENTITY could not resolve a
  domain; own-channel exclusion is best-effort). Kept separate from `error` so a
  non-fatal warning never reads as a failure (Codex review point 12).

**Category**
- `id`, `run` (FK)
- `key` — e.g. `news`, `trade_publications`.
- `is_borderline` — bool. Under the completeness status model (Section 8) it
  does NOT change status handling (borderline and core are treated alike); it
  sets de-dup priority (core kept over borderline, Section 5.3) and ordering.
- `display_order` — int, for stable UI ordering (fixed core order first).
- `status` — pending / running / green / yellow / red.
- `error` — nullable text (per-category failure, surfaced in the UI).
- `summary` — text (nullable until CATEGORY_SUMMARY; null if zero items).
- `started_at`, `ended_at` (nullable).

**ContentItem**
- `id`, `category` (FK)
- `title`, `url` (as displayed), `source` (publisher/domain)
- `canonical_url` — the normalized form of `url` (Section 19.1), used for
  cross-category de-duplication so trivially-different URLs collapse correctly.
- `published_at` — nullable (undated allowed; Section 9).
- `is_undated` — bool convenience for the UI flag (derivable from
  `published_at is None`).
- `snippet` — Tavily's own snippet (no per-item LLM call), truncated to
  `MAX_SNIPPET_CHARS` (Section 6.2).
- `display_order` — int, for stable ordering (by `published_at` desc, undated
  last, then insertion order).

`Category.item_count` and `Run.total_item_count` are NOT stored columns; they
are computed server-side in the serializers (Section 11) so the frontend never
counts items itself.

The item's content type IS its category (`Category.key`); there is no separate
`content_type` field, to avoid a second source of truth. Duration is derived
(`ended_at - started_at`), not stored.


## 11. API (DRF)

### Endpoints
- `POST /api/runs/` — create and start a run. Returns the created run.
- `GET /api/runs/` — home list, **newest first**, with a sensible default limit
  (e.g. 50) and an offset/limit for older runs. Each row: id, input_text,
  status, started_at.
- `GET /api/runs/<id>/` — full run-view payload (serializer contract below).
- `POST /api/runs/<id>/refresh/` — wipe this run's results and restart from
  scratch (see "Refresh flow" below). Behind an "Are you sure?" confirmation.
- `DELETE /api/runs/<id>/` — remove a run (best-effort-revokes in-flight tasks
  first), so the home list does not grow unbounded (delete semantics below).

### Serializer contract (Codex review point 12)
The run-detail payload is explicit so the frontend infers nothing:
- Run: `id`, `input_text`, `input_kind`, `status` (enum-like, stable values
  blue/green/yellow/red), `started_at`, `ended_at`, `executive_overview`,
  `total_item_count` (server-computed), `warnings` (JSON list), `error`.
- Per Category: `key`, `is_borderline`, `display_order`, `status` (enum-like
  pending/running/green/yellow/red), `item_count` (server-computed), `summary`,
  `error`.
- Per ContentItem: `title`, `url`, `source`, `published_at`, `is_undated`,
  `snippet`, `display_order`.
Clients derive "is this run active?" from `status == 'blue'` (documented rule);
there is no separate `is_active` field, and status labels stay frontend-owned
(Section 13) while status VALUES stay server-owned and stable.

### `input_kind` detection (deterministic, decision-complete)
Implemented by `detect_input_kind` in the shared URL module (Section 19.1), so
the rule is identical everywhere it is needed. Applied to the single input
field, in order:
1. Trimmed value contains an explicit scheme (`http://` / `https://`) → URL.
2. Contains any whitespace, or contains no dot → name.
3. Otherwise, if the leading token (before any `/`, `:`, or `?`) is a
   `host.tld` matching a public-suffix-style pattern (label(s) + a known-style
   TLD, no spaces) → URL. This accepts `example.com`, `google.com/about`, and
   `example.com:8080`.
4. Anything else → name.
For URLs, the registrable domain is derived from the host and IDENTITY is
skipped.

### Validation (fail loud — every rejected input returns 400 with a clear
message)
- Empty or whitespace-only input → 400.
- Input longer than a defined maximum length → 400.
- `input_kind == url` but the value is not a parseable URL/host → 400.
- `lookback_months`: must be an integer in `[1, 600]`; non-integer, non-positive
  or out-of-range → 400. Omitted → defaults to 36.
- `borderline_options` containing an unknown key → 400.
- A resulting selected-category set that is empty → 400 (cannot happen while the
  7 core categories are always included, but validated defensively at the API
  boundary since it would otherwise create a no-op run).

### Refresh flow (concurrency-safe)
1. Bump `Run.generation`.
2. Best-effort-revoke `celery_task_ids` (may not stop already-running tasks).
3. Delete the run's Category and ContentItem rows; reset status=blue,
   timestamps, overview, error.
4. Re-create Category rows (pending) and re-dispatch; store new task ids.
Correctness does not depend on revocation: generation fencing (Section 5.7)
guarantees that any still-running task from the previous generation has its
writes atomically rejected, so a late old subtask or callback cannot overwrite
the new run — even if revoke failed to stop it. A second refresh while one is in
progress simply bumps the generation again (idempotent per generation).

### Delete semantics for in-flight runs (Codex review point 10)
- Delete is terminal from the user's perspective; it cascades to remove the
  run's Category and ContentItem rows in one transaction.
- It best-effort-revokes in-flight tasks, but correctness does not depend on it.
- A task that later wakes and finds the run row gone treats "run missing" as
  supersession (Section 5.4): it returns normally, does NOT log an application
  error, and does NOT recreate any part of the deleted run. This is distinct
  from generation fencing because the row no longer exists, so the generation
  cannot be read — "missing run" IS the superseded signal.


## 12. Live updates (polling) and consistency invariants

Two independent pollers, each ~2s:
- **Home poller**: fetches once on mount to seed state, then runs while
  `runs.some(r => r.status === 'blue')` and stops when no listed run is blue.
  Because the normal create flow navigates the user into the new run's run-view
  (Section 13), the Home list is re-seeded by its mount fetch whenever the user
  returns to it (a run started while away then appears, with its spinner).
- **Run-view poller**: runs while `run.status === 'blue'` for *that* run; stops
  on any terminal status. Fetches immediately on mount / when the id changes.

Both pollers stop on component unmount, pause while `document.hidden`, and
**refetch immediately on `visibilitychange` back to visible** so a re-shown tab
never lingers on stale data.

Consistency invariants the backend guarantees (Section 5):
- A category flips off `running` only after its items+summary+ended_at are
  committed (one transaction) — a poll never shows a "done" category with no
  content.
- The run flips off `blue` only after executive_overview+ended_at are committed
  — the client's stop-polling signal (terminal status) always coincides with a
  fully-written run, so the overview is never blank at the moment polling stops.
- The client always renders from the latest full `GET /api/runs/<id>/` payload.

Poll/API failure surface (fail loud in the UI): a failed poll or GET shows a
non-blocking "Connection problem — retrying" banner, keeps and visibly marks the
last-known data as stale (never silently frozen), and retries with backoff.


## 13. Frontend (React + Vite)

### Home page
- Header with a **"New run"** button at top right.
- Clicking it opens a **modal**: a single field (company name or homepage URL);
  a numeric **"look-back (months)"** field pre-filled with 36; checkboxes for
  borderline categories. Client-side pre-validation mirrors the server rules
  (non-empty input; integer look-back in range). Submit is disabled while the
  request is pending.
- On success (2xx): the modal closes and the user is taken into the new run's
  run-view so they immediately "see job status" (PRD flow).
- On 400: the modal **stays open**, maps the server message to the offending
  field inline, and preserves entered values.
- On any other failure (5xx / network / timeout): the modal **stays open**,
  re-enables the submit button, shows a non-field error line ("Could not start
  the run — please retry"), and preserves entered values. (The Section 12
  retry banner covers polls/GETs only; this covers the create POST.)
- Below the header: a list of past runs, **newest first**, each row showing
  input_text, started_at, a status chip (label + icon; spinner while blue), and
  a **Delete** control (trash icon) that, after an "Are you sure?" confirm, calls
  `DELETE /api/runs/<id>/`. Clicking elsewhere on a row opens its run-view.

### Run-view
- Sticky header: input_text, start time, end time (once finished), total
  duration, and a status chip (label + icon, not colour alone).
- An in-progress banner while blue.
- A visually distinct **executive overview** block (heavier weight / boxed) so
  it is not confused with the per-category summaries. It is **hidden while the
  run is blue** and the overview is null (no empty box); it appears once the
  overview text exists.
- A category index / list of collapsible sections (7+ categories each with items
  is a long scroll; collapsible sections + an index keep it uncluttered). Each
  category section shows: the category name, its category status chip
  (vocabulary below), an item count, its summary, then its items — or a spinner
  while pending/running. **Default expansion**: on first load ALL categories
  start collapsed (product decision, superseding the earlier "non-empty/working
  expanded" rule), keeping the run-view compact; the user's per-section toggle
  is remembered for the session.
- Item row template (consistent, scannable): title (links out, opens new tab,
  `rel="noopener noreferrer"`), source, published date (or an "undated" marker),
  and a truncated one-line snippet. Items ordered by `display_order`.
- Empty/error states are explicit:
  - Yellow category (finished, zero items): "No content found for this category
    in the selected time window."
  - Red category (errored): shows a GENERIC message that the category could not
    be researched and can be retried via Refresh. The specific error (LLM/parse/
    network) is written to the application log server-side, never shown to the
    user (`Category.error` stores only the generic message).
  - Red run (nothing anywhere): a whole-run empty state instead of blank
    sections, plus the fixed overview message.
- A **Refresh** button that, after an "Are you sure?" dialog, wipes and restarts
  the run (works whether the run is finished or still blue).

### Styling and accessibility
- Modern, enterprise, uncluttered: neutral palette, generous whitespace,
  restrained typography, no gimmicks.
- Status is conveyed by **text label + icon + colour**, never colour alone
  (WCAG 1.4.1). Interactive controls are keyboard reachable; the modal traps
  focus and closes on Escape.
- Run-status chip vocabulary (Section 8): GREEN "Complete" (check), YELLOW
  "Partial (N of M)" (warning triangle; N = categories that finished without
  error, M = total categories, so the user sees the scope of the partial
  result), RED "Failed" (error/x), BLUE "Running" (spinner). In the home list
  (no per-category data) the yellow chip reads just "Partial".
- **Category-status chip vocabulary** is separate, because a category's five
  states differ in meaning from a run's four (e.g. a yellow category means
  "none found", not "partial run"):
    - green → "Found (N)" with a check (N = item count)
    - yellow → "None found" with a muted dash icon
    - red → "Error" with an x icon
    - pending / running → "Working" with a spinner
  Spinners carry an accessible text name (`aria-label`) so status is not
  conveyed by the animation alone.


## 14. Configuration and environment

- `.env` provides all settings; `.env-example` documents every variable.
- Required at startup (fail loud if missing), validated by a shared module that
  is invoked by **both** Django app startup (`AppConfig.ready`) and Celery
  worker startup — so a worker cannot boot with missing config and fail deep in
  a task:
  - `DEFAULT_LLM_URL`, `DEFAULT_LLM_API_KEY`, `DEFAULT_LLM_MODEL`,
    `DEFAULT_LLM_TOKENS`, `DEFAULT_LLM_TEMP`
  - `TAVILY_API_KEY`
  - `REDIS_URL` — required at runtime; there is NO `localhost:6379` fallback
    (no standard port is assumed). `start_all.sh` sets it to the chosen port.
- Optional per-call-point overrides (`IDENTITY`, `QUERY_PLANNER`, `CURATOR`,
  `CATEGORY_SUMMARY`, `REPORT`, `SENTIMENT`):
  `<NAME>_LLM_URL|API_KEY|MODEL|TOKENS|TEMP`.
- Optional tunables (with defaults): `CURATOR_MAX_ITERATIONS`,
  `CURATOR_MAX_SEARCHES`, `RUN_MAX_DURATION_SECONDS`, `REAPER_INTERVAL_SECONDS`,
  run-list page size; and the volume/prompt caps (Section 6.2):
  `QUERY_PLANNER_MAX_QUERIES`, `TAVILY_RESULTS_PER_SEARCH`,
  `MAX_CANDIDATES_PER_CATEGORY`, `MAX_ITEMS_PER_CATEGORY`, `MAX_SNIPPET_CHARS`,
  `REPORT_MAX_ITEMS_TOTAL`, `REPORT_MAX_ITEM_SNIPPET_CHARS`.
- Log limits (Section 7): LLM log directory, max size, backup count.
- `requirements.txt` must exist so the env can be built with `uv pip` / `pip`.


## 15. Running locally (`./start_all.sh`)

Responsibilities:
- Verify prerequisites and **error out** with a clear message if missing:
  required Python packages installed, **Docker present** (needed for Redis), and
  the frontend's `node_modules` present — if it is missing, either run
  `npm install` or fail loudly telling the user to (Codex review point 9). No
  silent start with a broken frontend.
- Discover free ports for Redis, Django, and Vite; export them as env vars
  (Section 4) and print each to the log. Port discovery uses a bind-check with a
  short retry loop to reduce (unavoidable) TOCTOU races.
- Start the Redis Docker container with a **collision-free, run-scoped name**
  (path- or PID-derived, e.g. `drumbeat-redis-<suffix>`, NOT a fixed name), so
  two checkouts / two instances do not clash — consistent with the no-fixed-ports
  stance. The cleanup trap removes exactly that container.
- **Wait for Redis readiness** BEFORE starting any dependent that connects
  (else fail-loud config crashes an early connector). Readiness does NOT assume a
  host `redis-cli`: poll via `docker exec <container> redis-cli ping`, or a short
  Python snippet using the installed redis client, or a Docker health check.
- Then run Django migrations, start Django, start the Celery worker with embedded
  beat (`-B`), and start Vite.
- **Supervise the Celery worker**: if it exits unexpectedly, restart it (so the
  embedded-beat reaper, Section 5.5, comes back). Log every restart.
- **Tail the log files** of all services.
- Trap **SIGINT (Ctrl-C), SIGTERM, and EXIT** and shut everything down,
  including `docker rm -f` of the run-scoped Redis container so it never leaks.
- Accept **`--reset-db`**: only while services are stopped, delete the SQLite
  file **and its `-wal` / `-shm` sidecars**, and the ephemeral
  `celerybeat-schedule` file, then re-run migrations.


## 16. Error-handling philosophy

Fail loudly, everywhere, with the single scoped exception in Section 5.4:
- Missing configuration → the app (and the worker) fail to start.
- Malformed/insufficient API input → a meaningful 400 with explanation.
- Malformed user form input → clear inline errors in the form.
- Prefer `data[key]` / `obj.attr` over `.get()` / `hasattr` when the field is
  genuinely expected. Genuinely-optional external data (e.g. Tavily's missing
  publish date, Section 9) is modelled as nullable, not treated as malformed.
- Per-category failures are caught only at the subtask boundary, **logged to the
  application log with a full traceback**, and recorded on the Category (→
  yellow/red run) as a GENERIC user-safe message. This is deliberate
  partial-failure handling, not silent swallowing: the operator sees the real
  error in the log; the user sees only "could not be researched, retry via
  Refresh". The fan-in degrade and non-fatal IDENTITY paths log likewise.


## 17. Concurrency and SQLite

The PRD requires multiple concurrent runs, so multiple subtasks (and the
callback) write concurrently while Django reads on every poll. To avoid
`database is locked`:
- SQLite `journal_mode=WAL` and a `busy_timeout` (e.g. 5000 ms) set in Django's
  `DATABASES['default']['OPTIONS']`.
- Keep write transactions short and scoped (the atomic per-category commit in
  Section 5.2 is the main write).
- Redis (not SQLite) is the Celery result backend.
- Celery worker concurrency is kept modest for local use; this is an accepted
  ceiling documented here (Postgres is the scale path — see
  `docs/FUTURE-IMPROVEMENTS.md`).

### 17.1 Explicit Celery settings (Codex review point 13)

These are set explicitly, not left implicit, because they materially affect
duplicate execution, reaper behaviour, and SQLite write pressure:
- `result_backend` = Redis; `result_expires` set long enough that a chord's
  results outlive the slowest run (comfortably above `RUN_MAX_DURATION_SECONDS`).
- `task_serializer` / `result_serializer` = JSON (no pickle).
- `task_soft_time_limit` and `task_time_limit` per subtask (soft < hard), so a
  stuck category fails cleanly and the reaper's sizing note (Section 5.5) holds.
- `task_acks_late` = FALSE and `task_reject_on_worker_lost` = FALSE (decision,
  Codex impl-review points 14/15). Rationale: generation fencing prevents
  cross-generation clobber but NOT same-generation duplicate execution; rather
  than add per-category attempt tokens, we simply do not redeliver lost tasks.
  A worker killed mid-category leaves that category `pending`/`running`; the
  reaper (Section 5.5) then terminalizes the whole run — the reaper already OWNS
  lost-worker recovery, so redelivery would only create racing same-generation
  duplicates. The final persist still uses delete-then-insert (defence in depth).
- `worker_prefetch_multiplier` = 1 (fair dispatch; avoids one worker hoarding
  the fan-out) and a modest `worker_concurrency` default given single-file
  SQLite.
- `task_track_started` = true, so the API/reaper can distinguish queued from
  running.


## 18. Testing strategy

TDD throughout. Backend: `pytest` + `pytest-django`. Frontend: **Vitest** +
React Testing Library. A single **`./run_tests.sh`** runs both suites and exits
non-zero if either fails (aggregating exit codes, not just the last), so it is
one pass/fail gate.

Mocking seams are explicit: mock at `call_llm()` and at a single
`tavily_search()` wrapper (no network in tests). Env-resolution and request
construction below those seams are unit-tested directly.

Coverage must include, at least:
- `call_llm` env resolution and `DEFAULT_*` fallback (each of the five vars).
- `input_kind` detection across all branches (incl. `example.com`).
- Exclusion: own-domain derivation and denylist matching, including subdomain /
  `www.` / case-insensitivity edge cases.
- Time-window filtering, including items with null `published_at`.
- Status computation (completeness model, Section 8): an empty-but-clean
  category does NOT demote from green; an errored/timed-out category → yellow;
  zero-items-everywhere → red.
- The chord orchestration with fakes, including a subtask that raises (must
  degrade to red, chord still completes) and the fan-in write ordering.
- The curator loop honouring its iteration/search bounds.
- IDENTITY failure being non-fatal (run proceeds without own-channel exclusion).
- API validation (every 400 path) and the refresh flow, including a
  concurrent/while-running refresh (generation fencing; no orphan writes).

Additional cases required by Codex review point 15:
- Stale category task after refresh returns normally and does NOT mark red
  (raises `SupersededGeneration`, treated as non-error).
- Stale fan-in callback after refresh does not overwrite the new run.
- Stale task after delete returns normally and does not recreate rows
  ("run missing" == supersession).
- Reaper racing the fan-in leaves exactly one terminal writer (CAS on `blue`).
- The generation-guard helper rolls back child inserts on a zero-row guard
  update (rowcount-abort proven).
- Malformed LLM JSON at each structured call-point degrades through the intended
  category/run failure path (fail-loud, no silent repair).
- `QUERY_PLANNER_MAX_QUERIES`, `TAVILY_RESULTS_PER_SEARCH`, and the retained
  item caps (Section 6.2) are enforced.
- URL canonicalization catches tracking params, fragments, host case, `www.`,
  and trailing-slash variants; `registrable_domain_matches` catches subdomains
  and does NOT match suffix tricks (`example.com.evil.test`); `owned_profile_match`
  is platform+path aware (no substring false positives).
- Undated-only category behaviour matches the chosen policy (Section 9: counts
  normally, best-effort window).
- Frontend shows the stale-data banner on poll failure and refetches on
  visibility restore; the create modal preserves input on both 400 and non-400
  failures.
- `start_all.sh --reset-db` removes the SQLite `-wal`/`-shm` sidecars and the
  beat schedule file.


## 19. Exclusion enforcement

Own-channel detection (Codex review point 6). The PRD excludes the company's own
website, blog, AND its channels on third-party domains (LinkedIn, X, YouTube,
Medium, Substack, GitHub, etc.). A registrable-domain check alone misses the
latter, so IDENTITY builds an **owned-channel exclusion set** stored on the Run:
- `resolved_domain` — the official registrable domain.
- `owned_profile_urls` / `owned_social_handles` — the company's own profiles on
  third-party platforms.
Sources of the set:
- URL input: derive and exclude the registrable domain plus subdomains
  immediately; IDENTITY may still enrich the profile/handle lists.
- Name input: IDENTITY resolves the domain AND the owned profiles/handles.
- If IDENTITY cannot resolve (Section 5.4 non-fatal path), `resolved_domain`
  stays null, own-channel exclusion is skipped, a **warning** is recorded on
  `Run.warnings`, and the run proceeds (denylist + CURATOR still apply).
Enforcement is **deterministic and happens BEFORE the CURATOR LLM sees
candidates**: the exclusion module drops any candidate whose registrable domain
matches `resolved_domain` (via `registrable_domain_matches`, Section 19.1).
Owned-profile/handle matching is **platform-aware, NOT substring** (Codex impl
points 9/10): a candidate is an own profile only when its host is a known profile
platform AND its first path segment equals the owned handle/profile path — so a
third-party article at `techcrunch.com/.../acmehq...` is NEVER dropped, and
`/company/acme` does not match `/company/acme-competitor`. The CURATOR still
catches borderline cases, but the primary own-channel filter never depends solely
on the LLM. Own-social matching is best-effort and labelled as such in
`Run.warnings` when IDENTITY confidence is low.

Aggregators / review / ecommerce:
- A small, curated denylist of well-known domains (e.g. G2, Capterra, Amazon,
  Crunchbase; Reddit and similar unless the matching borderline checkbox was
  ticked), in a single editable config module. Matching is case-insensitive and
  subdomain-aware (`registrable_domain_matches`, Section 19.1).
- The CURATOR LLM additionally judges borderline cases against explicit written
  exclusion rules in its prompt.

### 19.1 URL / domain normalization module (Codex review point 7)

URL identity is load-bearing for own-channel exclusion, denylist matching,
Tavily candidate filtering, and cross-category de-dup, so it lives in ONE shared,
heavily-tested module used everywhere — no ad hoc URL handling elsewhere. It uses
a pinned public-suffix library (`tldextract`, configured to NOT fetch updates at
runtime, so tests are offline and deterministic).

Functions:
- `detect_input_kind(text)` — the Section 11 name-vs-URL rule.
- `parse_homepage_input(text)` — normalize a homepage input to a host/URL.
- `registrable_domain(host_or_url)` — public-suffix registrable domain.
- `canonicalize_url_for_dedupe(url)` — the `ContentItem.canonical_url` form.
- `registrable_domain_matches(candidate, target)` — subdomain-aware,
  suffix-trick-safe comparison of registrable domains (matches
  `blog.example.com` to `example.com`, but NOT `example.com.evil.test`). Named
  for what it does; it is used ONLY for own-domain and denylist checks, never for
  owned-profile matching on shared third-party platforms (Codex impl point 12).
- `owned_profile_match(candidate_url, profile_url_or_handle)` — platform-aware
  profile match (host is a known platform AND first path segment equals the
  handle/profile path; never an arbitrary substring; Codex impl points 9/10).

Canonicalization POLICY (Codex impl point 11): `canonicalize_url_for_dedupe`
deliberately **collapses http and https to a single https form** (and strips
`www.`, fragments, tracking params, trailing slash). This is intentional for
article de-dup; the rare site that serves different content over http vs https is
an accepted trade-off, documented here rather than an accidental artifact.

Deterministic handling required and tested: public-suffix registrable domains,
`www.` normalization, case-insensitive hosts, default ports, trailing slashes,
fragments, common tracking query params, http/https collapse, percent-encoding
edge cases, and internationalized domain names (IDN).


## 20. Deferred items

Recorded in `docs/FUTURE-IMPROVEMENTS.md` (per-item LLM summaries, SSE/
WebSockets, Postgres, rich pagination, exports, auth/hosting/CI-CD, etc.).


## 21. Open decisions

None. D1 (Python 3.13) and D2 (Docker Redis) are resolved in Sections 3 and 4.

Decisions taken in response to Codex review 1 (all now folded into the sections
above): run status uses the **completeness** model, not per-category abundance
(Section 8, confirmed with the product owner as it changed an earlier choice);
undated items **count normally** with a best-effort window label (Section 9);
own-channel exclusion is **deterministic + LLM**, with owned profiles/handles
stored on the Run (Section 19); structured LLM output contracts are strict and
fail-loud on malformed output (Section 6.1).

The one item to verify (not decide) at setup time is that the pinned Django /
Celery / DRF versions install cleanly on Python 3.13 in this environment.


## 22. Implementation progress tracking

Update this table as implementation proceeds (status: TODO / WIP / DONE).
Ordering follows Codex review point 14: generation fencing, status computation,
and the URL/exclusion module are CORE PRIMITIVES built and tested BEFORE Celery
orchestration — not a finishing layer — so the task persistence path is not
rewritten later.

| # | Milestone                                                    | Status |
|---|--------------------------------------------------------------|--------|
| 1 | Python 3.13 env, requirements.txt, project scaffolding       | DONE   |
| 2 | .env / .env-example + fail-loud config validation (shared)   | DONE   |
| 3 | Data model + migrations (Run / Category / ContentItem)       | DONE   |
| 4 | Status computation (completeness model, Section 8), tested   | DONE   |
| 5 | URL/domain module (19.1) + exclusion (own-channel+denylist)  | DONE   |
| 6 | Generation-fenced write helper + SupersededGeneration; tests | DONE   |
| 7 | call_llm() + fallback + LLM log + structured-output parsers  | DONE   |
| 8 | tavily_search() wrapper + time-window + volume caps          | DONE   |
| 9 | Celery app + settings; chord/subtask/fan-in/reaper (helper)  | DONE   |
|10 | Curator agentic loop (bounded) with tool-calling             | DONE   |
|11 | DRF endpoints + validation + serializer contract             | DONE   |
|12 | Refresh + delete flows using the fencing helper              | DONE   |
|13 | React app: home, New-run modal, run list, polling            | DONE   |
|14 | React run-view: overview, categories, items, states          | DONE   |
|15 | start_all.sh (ports, scoped Redis, readiness, traps, reset)  | DONE   |
|16 | run_tests.sh + backend/frontend test suites                  | DONE   |
|17 | End-to-end manual verification against a real company        | PARTIAL|
|18 | Sentiment scoring + run-level trend graph (SENTIMENT-*.md)   | DONE   |
