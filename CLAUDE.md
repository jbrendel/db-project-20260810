# CLAUDE.md — Drumbeat project guide

Orientation for working in this repo. The authoritative design is
`plans/INITIAL.md`; deferred work is in `docs/FUTURE-IMPROVEMENTS.md`. When this
file and the plan disagree, the plan wins — update this file to match.

## What this is

A locally-run web app that, given a company name or homepage URL, runs a
background job to find third-party content about the company (news, trade
press, blogs, press releases, social, newsletters, podcasts) from a
configurable recent window (default 36 months), and presents it as a clean,
categorised, reviewable list.

## Project status

Design is complete and adversarially reviewed (`plans/INITIAL.md`, rev 5).
Implementation has not started yet. Milestones are tracked in Section 22 of the
plan. Commands and paths below describe the intended system; they do not all
exist on disk yet.

## Tech stack (fixed — do not swap without a decision)

- Backend: Django + Django REST Framework (API only; no server-side rendering).
- Async: Redis + Celery (Django integration). Redis runs as a Docker container.
- Database: SQLite (WAL mode + busy_timeout).
- Frontend: React, served by Vite in dev; Vite proxies `/api/*` to Django.
- LLM: an OpenAI-compatible API (OpenAI or OpenRouter).
- Search: Tavily.
- Python 3.13 (NOT 3.14 — see constraints).

## Architecture in one screen

- Four processes started by `./start_all.sh`: Redis (Docker), Django, a Celery
  worker with embedded beat (`-B`), and Vite. All bind dynamically chosen free
  ports, propagated to every process via env vars.
- A run is a Celery **chord**: an IDENTITY step (resolve the company's own
  domain, to exclude it), then one subtask per selected category (fan-out),
  then a fan-in callback (executive overview + final status).
- Per-category subtask: QUERY_PLANNER -> Tavily search -> agentic CURATOR
  (relevance + exclusions + dedupe, may search again, bounded) ->
  CATEGORY_SUMMARY.
- Frontend learns progress by polling (~2s), not push.
- Data model: Run -> Category -> ContentItem (see plan Section 10).

## LLM configuration convention

All LLM calls go through one `call_llm(name, ...)` function. `name` selects env
vars `<NAME>_LLM_URL|API_KEY|MODEL|TOKENS|TEMP`, each falling back to
`DEFAULT_LLM_*`. The five `DEFAULT_LLM_*` are required. Call-points: IDENTITY,
QUERY_PLANNER, CURATOR, CATEGORY_SUMMARY, REPORT, SENTIMENT. `call_llm` is
single-shot; the
agentic loop lives in the CURATOR subtask, not inside `call_llm`. Every call is
logged (model, timings, tokens, full prompt+response) to a separate LLM log
file.

## Hard constraints (from the PRD and global guidelines)

- **Fail loud.** Missing config -> the app AND the Celery worker refuse to
  start. Bad API input -> a 400 with a clear message. Avoid defensive coding:
  prefer `data[key]` / `obj.attr` over `.get()` / `hasattr` when the field is
  genuinely expected. Genuinely-optional external data (e.g. Tavily's missing
  publish date) is modelled as nullable, not treated as malformed.
- **Boring stack.** No bleeding-edge frameworks. This is why Python is 3.13, not
  3.14.
- **No assumed ports.** Discover free ports at runtime; print them to the log.
- **Line length: 94 characters max** for any `.md`/`.txt` file and for code.
  Python docstring first lines: 80 max.
- Git: always `git diff --no-ext-diff` (and `--no-ext-diff` on `show`/`--staged`
  too). This is not yet a git repo.

## Non-obvious invariants — READ BEFORE "fixing" these

These look wrong without context. They are deliberate.

- **Broad `except` at chord boundaries is intentional.** A Celery chord fails
  entirely if any header task raises, so each category subtask, the fan-in
  callback, and the non-fatal IDENTITY step wrap their body in
  `try/except Exception`, record the error, and return normally. These are the
  sanctioned broad-except sites (plan Section 5.4). A fourth sanctioned
  non-fatal broad-except is `pipeline.score_sentiments` (per-item sentiment,
  inside the category subtask): it records `null` sentiment and re-raises
  `SoftTimeLimitExceeded` so it never masks a timeout, and never marks a
  category red. Code still fails loud UP TO those boundaries.
- **Generation fencing (plan Section 5.7) is how refresh/reaper stay correct,
  NOT task revocation.** `Run.generation` is bumped on refresh and by the
  reaper. Every DB write happens in a transaction whose first statement is a
  generation-conditional `UPDATE ... WHERE id=:id AND generation=:g`; if it
  affects zero rows, the code RAISES to roll the whole transaction back
  (a zero-row UPDATE is a silent no-op otherwise). Never use
  `SELECT ... FOR UPDATE` (a no-op on SQLite). `revoke` is best-effort only.
- **Never hold a DB transaction across an LLM/network call.** The fan-in
  callback computes the dedup plan and calls REPORT OUTSIDE any transaction, then
  opens one short generation-fenced transaction to write. Holding the SQLite
  writer lock across REPORT would block every other write and every poll.
- **`SupersededGeneration` is expected control flow, not an error.** A
  zero-row generation guard, or a run row that no longer exists (deleted/reset),
  raises `SupersededGeneration`, which is caught BEFORE the broad `except`. A
  superseded task returns normally: it does NOT mark the category red, does NOT
  alter run status, and logs at debug/info — never error.
- **Write ordering drives the UI.** A category flips off "running" only after
  its items+summary+ended_at are committed; a run flips off "blue" only after
  overview+ended_at are committed. This is what makes polling honest.
- **URL identity is centralized.** All URL/domain logic (input detection,
  registrable domain, dedupe canonicalization, subdomain-safe `domain_matches`)
  lives in ONE tested module (plan Section 19.1); never handle URLs ad hoc.
- **Run status measures completeness, not abundance.** GREEN = all categories
  finished cleanly AND >=1 item across the run; an empty-but-clean category does
  NOT demote. YELLOW = a category errored/timed out. RED = zero items or all
  errored (plan Section 8).
- **Reaper** finalizes runs stuck BLUE too long (worker/child death): bump
  generation, terminalize dangling categories, roll up status, write a fixed
  overview. It needs a live worker, so `start_all.sh` supervises/restarts the
  worker.
- **Status is never colour alone.** Every status chip carries a text label +
  icon (accessibility). Run and category chips use DIFFERENT vocabularies (plan
  Section 13).

## Commands

- `./start_all.sh` — start everything; tails all logs; Ctrl-C shuts all down.
  `--reset-db` wipes the SQLite DB (and its `-wal`/`-shm` sidecars) to empty.
- `./run_tests.sh` — run backend (`pytest`) and frontend (`vitest`) suites;
  exits non-zero if either fails.

## Testing conventions

TDD. Backend: `pytest` + `pytest-django`. Frontend: `vitest` + React Testing
Library. Mock LLM and Tavily at the `call_llm()` and `tavily_search()` seams —
no network in tests. See plan Section 18 for required coverage.

## Where to look

- `plans/INITIAL.md` — full design (source of truth). Section 22 = progress.
- `plans/PRD-initial.md` — the original client requirements.
- `docs/FUTURE-IMPROVEMENTS.md` — deliberately deferred items.
