# Drumbeat

Find out what the world is saying about a company.

Drumbeat is a locally-run web app. You give it a company name or homepage URL,
and it launches a background job that searches for third-party content about
that company from a recent time window (default: the last 36 months). Results
arrive grouped into categories you can review at a glance.

## What it collects

Included content types (each is a category):
news articles, trade publications, third-party blog posts, press releases, major
social posts, newsletters, and podcasts. Optional "borderline" sources (e.g.
Reddit and similar forums) can be enabled per run.

Deliberately excluded: the company's own channels (its site, blog, LinkedIn,
etc.), link aggregators, product review/comparison pages, and ecommerce pages.

For each run you get: a run-level executive overview, a short summary per
category, the underlying items (title, source, date, snippet, link), and a
per-item sentiment score charted as a trend over time. A run shows a status —
Complete, Partial, Failed, or Running. Multiple runs can proceed in parallel.

## Project status

The application is implemented and runnable. Start it with `./start_all.sh`
(see "Running" below). The original design remains the source of truth in
`plans/INITIAL.md`; `NOTES.md` explains how the system was actually built.

## Tech stack

Django + Django REST Framework, Celery + Redis, SQLite, and a React frontend
served by Vite. Research uses an OpenAI-compatible LLM API and Tavily for web
search. Backend runs on Python 3.13.

## Prerequisites

- A POSIX/Linux system with `bash`.
- Python 3.13 and [`uv`](https://github.com/astral-sh/uv).
- Docker (Redis runs as a container).
- Node.js 20+ and npm (for the React frontend).
- API keys: an OpenAI-compatible LLM endpoint key, and a Tavily API key.

## Setup

```bash
# 1. Clone the repo, then create and activate a Python 3.13 virtualenv.
uv venv --python 3.13
source .venv/bin/activate

# 2. Install backend dependencies.
uv pip install -r requirements.txt

# 3. Install frontend dependencies (in the frontend directory).
(cd frontend && npm install)

# 4. Create your .env from the template and fill in the values.
cp .env-example .env
# then edit .env — see "Configuration" below.
```

If frontend dependencies are missing, `start_all.sh` fails loudly and tells you
to run `npm install` rather than starting with a broken frontend.

## Running

```bash
./start_all.sh
```

This one script:

- checks that dependencies and Docker are available (and errors out if not);
- picks **free ports** for Redis, Django, and Vite (it does not assume standard
  ports are free) and prints each chosen port to the log;
- starts Redis (Docker), applies database migrations, and starts Django, the
  Celery worker, and the Vite dev server;
- tails the logs of all services into one view.

Press **Ctrl-C** to shut everything down cleanly (including the Redis
container).

**Where to point your browser:** the script prefers fixed, non-standard ports,
so the frontend is usually at **http://localhost:5390**. To be sure, look for
these lines near the top of the output:

```
Ports -> Redis:6390  Django:8390  Vite:5390
Open the app at: http://localhost:5390
```

Use the `Open the app at:` URL — if port 5390 was already taken, the script
picks the next free port and prints the actual one there.

To wipe the database back to empty:

```bash
./start_all.sh --reset-db
```

## Using the app

1. On the home page, click **New run** (top right).
2. In the dialog, enter a company name or homepage URL, optionally adjust the
   look-back window (months), and tick any borderline sources you want included.
3. Submit. The run starts in the background and you are taken to its run-view.
4. Watch categories fill in live (each shows a spinner until it completes). Past
   runs remain on the home page; click any to reopen it.
5. Once items arrive, the run-view also shows a sentiment trend graph plotting
   each item's score over time.
6. On a run-view you can **Refresh** to wipe that run and start it over.

Multiple runs can be in progress at once.

## Configuration

All settings live in `.env`. `.env-example` documents every variable. The app
**fails to start** if a required variable is missing.

Required:

- `TAVILY_API_KEY` — for web search.
- `DEFAULT_LLM_URL`, `DEFAULT_LLM_API_KEY`, `DEFAULT_LLM_MODEL`,
  `DEFAULT_LLM_TOKENS`, `DEFAULT_LLM_TEMP` — the fallback LLM configuration.

Per-call-point overrides (optional): the app makes distinct kinds of LLM calls
(IDENTITY, QUERY_PLANNER, CURATOR, CATEGORY_SUMMARY, REPORT, SENTIMENT). Each can
use a different model by setting `<NAME>_LLM_URL|API_KEY|MODEL|TOKENS|TEMP`. Any
variable not set for a call-point falls back to its `DEFAULT_LLM_*` value. This
lets you, for example, use a cheaper model for planning and a stronger one for
the executive overview.

Because the API is OpenAI-compatible, `*_LLM_URL` can point at OpenAI,
OpenRouter, or any compatible endpoint.

## Testing

```bash
./run_tests.sh
```

Runs the backend (`pytest`) and frontend (`vitest`) unit tests as a single
pass/fail gate.

## Not included (for now)

Authentication, hosting, and CI/CD are out of scope. Other deferred ideas are
listed in `docs/FUTURE-IMPROVEMENTS.md`.

## Documentation

- `NOTES.md` — how the system was built: the approach, the stack rationale,
  what went beyond the original brief, and known unfinished business.
- `docs/ARCHITECTURE.md` — the architecture with diagrams (process view,
  per-category pipeline, run lifecycle, and key invariants), rendered from
  Mermaid.
- `docs/architecture.html` / `docs/architecture.pdf` — the same architecture as
  a self-contained page and printable PDF.
- `docs/pipeline.html` / `docs/pipeline.pdf` — the per-category research flow.
- `plans/INITIAL.md` — the full design and the source of truth.
- `plans/PRD-initial.md` — the original product requirements.
- `plans/SENTIMENT-DESIGN.md` — design for the sentiment-analysis feature.
- `CLAUDE.md` — architecture decisions, constraints, and key invariants.
- `docs/FUTURE-IMPROVEMENTS.md` — deliberately deferred work.
