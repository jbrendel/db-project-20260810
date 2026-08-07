# Drumbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app that researches third-party content about a
company via background jobs and presents it as a categorised, reviewable list.

**Architecture:** Django + DRF JSON API, Celery chord over Redis for the
research fan-out, SQLite (WAL) for storage, React + Vite frontend that polls for
progress. LLM calls go through one `call_llm(name)`; search through one
`tavily_search()`. Correctness under refresh/delete/timeout rests on
generation-fenced writes.

**Tech Stack:** Python 3.13, Django 5.2 LTS, DRF, Celery 5.4+, redis-py,
`openai` SDK (OpenAI-compatible), `tavily-python`, `tldextract`, pytest +
pytest-django; React 18, Vite, Vitest + React Testing Library.

**Source of truth:** `plans/INITIAL.md` (design, rev 6). Section references
below (e.g. "§5.7") point there. Deferred items: `docs/FUTURE-IMPROVEMENTS.md`.

## Global Constraints

- Python 3.13 (NOT 3.14). Boring, well-established stack only.
- **Fail loud.** Missing config → app AND Celery worker refuse to start. Bad API
  input → 400 with a clear message. Prefer `data[key]` / `obj.attr` over `.get()`
  / `hasattr` when a field is genuinely expected. Genuinely-optional external
  data (e.g. a Tavily result with no date) is modelled as nullable, not an error.
- **No line of code or Markdown longer than 94 characters.** Python docstring
  first line ≤ 80.
- **Never hold a DB transaction open across an LLM/network call** (§5.3).
- **Every task's DB write to Run/Category/ContentItem is generation-fenced**
  (§5.7). `SupersededGeneration` is expected control flow, not an error (§5.4).
- Status is never colour alone: text label + icon (§13). Run status uses the
  **completeness** model (§8).
- Redis is the Celery broker/result backend. No standard ports assumed.
- Git: always `git diff --no-ext-diff`. Commit at the end of every task. Only
  run `git init` if the directory is not already a repo; never overwrite or
  revert pre-existing user changes in the worktree (Codex impl point 23).
- All LLM/Tavily calls are mocked in tests (no network). Mock seams: `call_llm`
  and `tavily_search`.
- Snippet legend (Codex impl point 28): code blocks marked "test" are
  authoritative test skeletons (expand with the listed extra cases); the fencing,
  schema, `call_llm`, and task-orchestration snippets are "copy" — implement as
  shown; prose-described helpers are "shape only" — implement to the stated
  contract and tests.

---

## File structure

Backend (Django project `drumbeat`, single app `research`):

- `manage.py` — Django entry point.
- `drumbeat/settings.py` — settings; reads ports/URLs from env; SQLite WAL.
- `drumbeat/urls.py` — root URLconf; includes `research.urls` under `/api/`.
- `drumbeat/celery.py` — Celery app + explicit settings (§17.1).
- `research/apps.py` — `AppConfig.ready()` runs fail-loud config check.
- `research/config_check.py` — required-env validation, shared by Django+Celery.
- `research/categories.py` — core/borderline category keys, order, denylist.
- `research/urls_util.py` — URL/domain module (§19.1).
- `research/exclusion.py` — own-channel + denylist filtering (§19).
- `research/models.py` — Run, Category, ContentItem.
- `research/status.py` — completeness status computation (§8).
- `research/fencing.py` — generation-fenced write helper + SupersededGeneration.
- `research/llm.py` — `call_llm()` + env resolution + LLM logging.
- `research/schemas.py` — structured-output parsers (§6.1).
- `research/tavily.py` — `tavily_search()` wrapper + time-window (§9).
- `research/pipeline.py` — pure per-category research logic (planner→curator).
- `research/tasks.py` — Celery tasks: run start, subtask, fan-in, reaper.
- `research/serializers.py` — DRF serializers (§11 contract).
- `research/views.py` — DRF views (create/list/detail/refresh/delete).
- `research/urls.py` — app URLconf.
- `research/tests/` — one test module per unit above.

Frontend (`frontend/`):

- `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`.
- `frontend/src/main.jsx`, `frontend/src/App.jsx`.
- `frontend/src/api.js` — fetch wrappers.
- `frontend/src/usePolling.js` — polling hook (visibility-aware).
- `frontend/src/components/` — `HomePage`, `NewRunModal`, `RunList`,
  `RunView`, `CategorySection`, `StatusChip`, `ContentItemRow`.
- `frontend/src/**/__tests__/*.test.jsx` — Vitest tests.

Scripts: `start_all.sh`, `run_tests.sh` (repo root).

---

## Progress tracker

Update this row's status as each task lands (TODO / WIP / DONE). Per-step
checkboxes inside each task give finer detail; this table is the at-a-glance view.

| Task | Deliverable                                   | Status |
|------|-----------------------------------------------|--------|
| 1    | Scaffolding, Py3.13 env, Django + pytest      | DONE   |
| 2    | Env settings, SQLite WAL, config check        | DONE   |
| 3    | Category registry + denylist                  | DONE   |
| 4    | URL/domain module (§19.1)                      | DONE   |
| 5    | Exclusion module (own-channel + denylist)     | DONE   |
| 6    | Models + migrations                           | DONE   |
| 7    | Status computation (completeness)             | DONE   |
| 8    | Generation-fenced write helper                | DONE   |
| 9    | call_llm + resolution + logging + schemas     | DONE   |
| 10   | tavily_search + window filter + caps          | DONE   |
| 11   | Celery app + settings + beat                  | WIP    |
| 12   | Per-category research pipeline                 | TODO   |
| 13   | Bounded agentic curator loop                  | TODO   |
| 14   | IDENTITY + chord/subtask/fan-in/reaper        | TODO   |
| 15   | Serializers + create/list/detail endpoints    | TODO   |
| 16   | Refresh + delete flows                        | TODO   |
| 17   | Frontend scaffold, api client, polling        | TODO   |
| 18   | Home page, run list, New-run modal            | TODO   |
| 19   | Run-view                                      | TODO   |
| 20   | start_all.sh                                  | TODO   |
| 21   | run_tests.sh                                  | TODO   |
| 22   | End-to-end manual verification                | TODO   |

---

## Phase 0 — Scaffolding and configuration

### Task 1: Project scaffolding, Python 3.13 env, Django + pytest

**Files:**
- Create: `requirements.txt`, `manage.py`, `drumbeat/__init__.py`,
  `drumbeat/settings.py`, `drumbeat/urls.py`, `pytest.ini`,
  `research/__init__.py`, `research/apps.py`, `research/tests/__init__.py`,
  `research/tests/test_smoke.py`, `.gitignore`.

**Interfaces:**
- Produces: a Django project that boots and a passing pytest run.

- [ ] **Step 1: Create the Python 3.13 environment and requirements.txt**

```bash
uv venv --python 3.13
source .venv/bin/activate
```

`requirements.txt` (pin exact versions during install; floors shown):

```
Django>=5.2,<5.3
djangorestframework>=3.15
celery>=5.4
redis>=5.0
openai>=1.40
tavily-python>=0.5
tldextract>=5.1
python-dotenv>=1.0
pytest>=8
pytest-django>=4.8
pytest-env>=1.1
```

- [ ] **Step 2: Install and scaffold Django**

```bash
uv pip install -r requirements.txt
django-admin startproject drumbeat .
python manage.py startapp research
```

- [ ] **Step 3: Write the failing smoke test**

`research/tests/test_smoke.py`:

```python
def test_truth():
    assert 1 + 1 == 2
```

`pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = drumbeat.settings
python_files = test_*.py
```

- [ ] **Step 4: Register the app and run the test**

Add `"research"` and `"rest_framework"` to `INSTALLED_APPS` in
`drumbeat/settings.py`. Run: `pytest -q`. Expected: PASS.

- [ ] **Step 5: Add .gitignore and commit**

`.gitignore` includes `.venv/`, `__pycache__/`, `*.sqlite3`, `*.sqlite3-*`,
`.env`, `logs/`, `node_modules/`, `celerybeat-schedule*`.

```bash
git init
git add -A
git commit -m "chore: scaffold Django project and pytest"
```

### Task 2: Env-driven settings, SQLite WAL, fail-loud config check

**Files:**
- Modify: `drumbeat/settings.py`
- Create: `research/config_check.py`, `.env-example`,
  `research/tests/test_config_check.py`
- Modify: `research/apps.py`

**Interfaces:**
- Produces: `research.config_check.validate_required_env()` — raises
  `ImproperlyConfigured` listing every missing required var; returns None on
  success. `research.config_check.REQUIRED_VARS: list[str]`.

- [ ] **Step 1: Write the failing test**

`research/tests/test_config_check.py`:

```python
import pytest
from django.core.exceptions import ImproperlyConfigured
from research import config_check


def test_missing_required_vars_raise(monkeypatch):
    for var in config_check.REQUIRED_VARS:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ImproperlyConfigured) as exc:
        config_check.validate_required_env()
    assert "TAVILY_API_KEY" in str(exc.value)
    assert "DEFAULT_LLM_URL" in str(exc.value)


def test_all_present_passes(monkeypatch):
    for var in config_check.REQUIRED_VARS:
        monkeypatch.setenv(var, "x")
    assert config_check.validate_required_env() is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest research/tests/test_config_check.py -v`
Expected: FAIL (module/attribute missing).

- [ ] **Step 3: Implement `config_check.py`**

```python
"""Fail-loud validation of required environment variables."""
import os
from django.core.exceptions import ImproperlyConfigured

REQUIRED_VARS = [
    "DEFAULT_LLM_URL",
    "DEFAULT_LLM_API_KEY",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_TOKENS",
    "DEFAULT_LLM_TEMP",
    "TAVILY_API_KEY",
    "REDIS_URL",  # required at runtime; no localhost:6379 fallback (§14)
]


def validate_required_env():
    """Raise ImproperlyConfigured if any required env var is missing."""
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise ImproperlyConfigured(
            "Missing required env vars: " + ", ".join(sorted(missing))
        )
    return None
```

- [ ] **Step 4: Wire settings + AppConfig, run tests**

In `drumbeat/settings.py`: load `.env` via `python-dotenv`, read
`DJANGO_PORT`/`VITE_PORT`/`REDIS_URL` from env, set `ALLOWED_HOSTS =
["localhost", "127.0.0.1"]`, and configure SQLite with WAL:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"init_command": "PRAGMA busy_timeout=5000;"},
    }
}
```

Set WAL once via a connection signal in `research/apps.py`:

```python
from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _set_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.cursor().execute("PRAGMA journal_mode=WAL;")


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "research"

    def ready(self):
        import os
        from research.config_check import validate_required_env
        connection_created.connect(_set_sqlite_wal)
        # Fail loud on every Django entry point (runserver, WSGI/ASGI,
        # django-admin) EXCEPT under an explicit test switch.
        if os.environ.get("DRUMBEAT_SKIP_CONFIG_CHECK") != "1":
            validate_required_env()
```

Do NOT gate on `PYTEST_CURRENT_TEST` — it is set per-test, not during
pytest-django's initial `django.setup()`, so app-registry population could fail
before fixtures run (Codex impl point 1). Instead `pytest.ini` sets the switch
for the whole test process:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = drumbeat.settings
python_files = test_*.py
env =
    DRUMBEAT_SKIP_CONFIG_CHECK=1
    REDIS_URL=redis://localhost:6379/0
```

(`env =` requires the `pytest-env` dev dependency; add it to `requirements.txt`.
The test `REDIS_URL` only lets `drumbeat.celery` import; no test connects to it,
since Celery tasks are driven via `.run(...)`, not through the broker.)
This covers §14's "invoked by Django app startup" for ALL Django entry points.
The Celery worker validates separately via `worker_init` (Task 11). Individual
config tests still call `validate_required_env()` directly after `monkeypatch`.
Create `.env-example` documenting every var from §14. Run: `pytest -q`. Expected:
PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: env-driven settings, SQLite WAL, fail-loud config check"
```

---

## Phase 1 — Core primitives (pure, tested, before Celery)

### Task 3: Category registry and denylist

**Files:**
- Create: `research/categories.py`, `research/tests/test_categories.py`

**Interfaces:**
- Produces:
  - `CORE_CATEGORIES: list[str]` (7 keys, in display order).
  - `BORDERLINE_CATEGORIES: list[str]`.
  - `DISPLAY_ORDER: dict[str, int]` (core first, then borderline).
  - `DENYLIST_DOMAINS: set[str]` (registrable domains).
  - `selected_category_keys(borderline_options: dict) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
from research import categories as c


def test_core_always_selected():
    keys = c.selected_category_keys({})
    assert set(c.CORE_CATEGORIES) <= set(keys)
    assert "reddit" not in keys


def test_borderline_added_when_ticked():
    keys = c.selected_category_keys({"reddit": True})
    assert "reddit" in keys
    assert keys.index("news") < keys.index("reddit")  # core before borderline


def test_unknown_borderline_key_raises():
    import pytest
    with pytest.raises(KeyError):
        c.selected_category_keys({"nonsense": True})
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_categories.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `categories.py`**

```python
"""Category keys, display ordering, and the exclusion denylist."""

CORE_CATEGORIES = [
    "news",
    "trade_publications",
    "blog_posts",
    "press_releases",
    "social_posts",
    "newsletters",
    "podcasts",
]

BORDERLINE_CATEGORIES = ["reddit", "forums"]

DISPLAY_ORDER = {
    key: i for i, key in enumerate(CORE_CATEGORIES + BORDERLINE_CATEGORIES)
}

DENYLIST_DOMAINS = {
    "g2.com", "capterra.com", "amazon.com", "crunchbase.com",
    "trustpilot.com", "getapp.com",
    "reddit.com",  # borderline: excluded unless the reddit checkbox opts in
}

# Borderline checkbox -> the domains it admits when ticked (§19).
BORDERLINE_DOMAIN_MAP = {"reddit": {"reddit.com"}, "forums": set()}


def selected_category_keys(borderline_options):
    """Return core keys plus any ticked, known borderline keys, in order."""
    keys = list(CORE_CATEGORIES)
    for key, ticked in borderline_options.items():
        if key not in BORDERLINE_CATEGORIES:
            raise KeyError(f"Unknown borderline category: {key}")
        if ticked:
            keys.append(key)
    return sorted(keys, key=lambda k: DISPLAY_ORDER[k])
```

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_categories.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: category registry and denylist"
```

### Task 4: URL / domain normalization module (§19.1)

**Files:**
- Create: `research/urls_util.py`, `research/tests/test_urls_util.py`

**Interfaces:**
- Produces (§19.1):
  - `detect_input_kind(text: str) -> str` ("name" | "url").
  - `registrable_domain(host_or_url: str) -> str | None`.
  - `canonicalize_url_for_dedupe(url: str) -> str` (collapses http/https).
  - `registrable_domain_matches(candidate_url, target_domain) -> bool`.
  - `owned_profile_match(candidate_url, profile_url_or_handle) -> bool`.
  - `parse_homepage_input(text: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
from research import urls_util as u


def test_detect_input_kind():
    assert u.detect_input_kind("Acme Corp") == "name"
    assert u.detect_input_kind("https://acme.com") == "url"
    assert u.detect_input_kind("acme.com") == "url"
    assert u.detect_input_kind("acme.com/about") == "url"
    assert u.detect_input_kind("acme.com:8080") == "url"
    assert u.detect_input_kind("just a phrase") == "name"


def test_registrable_domain():
    assert u.registrable_domain("https://blog.acme.co.uk/x") == "acme.co.uk"
    assert u.registrable_domain("acme.com") == "acme.com"


def test_canonicalize_strips_tracking_and_fragment():
    a = u.canonicalize_url_for_dedupe("https://A.com/p/?utm_source=x#frag")
    b = u.canonicalize_url_for_dedupe("http://www.a.com/p")
    assert a == b


def test_registrable_domain_matches_subdomain_not_suffix_trick():
    assert u.registrable_domain_matches("https://news.acme.com/x", "acme.com")
    assert not u.registrable_domain_matches(
        "https://acme.com.evil.test/x", "acme.com")


def test_owned_profile_match_is_platform_and_path_aware():
    assert u.owned_profile_match("https://x.com/acmehq/status/1", "@acmehq")
    # third-party article merely mentioning the handle in the path is NOT a match
    assert not u.owned_profile_match(
        "https://techcrunch.com/2025/acmehq-raises", "@acmehq")
    # linkedin uses a two-segment account key (company/<slug>)
    assert u.owned_profile_match(
        "https://linkedin.com/company/acme/about",
        "https://linkedin.com/company/acme")
    # path-prefix false positive guarded
    assert not u.owned_profile_match(
        "https://linkedin.com/company/acme-competitor",
        "https://linkedin.com/company/acme")


def test_parse_homepage_input_edges():
    assert u.parse_homepage_input("acme.com") == "https://acme.com"
    for bad in ("https://", "http://", "https://?x=1", "example..com",
                ".com", "example.com.", "exa mple.com"):
        assert u.parse_homepage_input(bad) is None
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_urls_util.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `urls_util.py`**

```python
"""Deterministic URL/domain handling. tldextract runs offline (no fetch)."""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import tldextract

# suffix_list_urls=() disables network refresh so tests are deterministic.
_extract = tldextract.TLDExtract(suffix_list_urls=())

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_eid", "ref")


def _with_scheme(text):
    if "://" in text:
        return text
    return "https://" + text


def detect_input_kind(text):
    """Classify a single input as a company name or a URL."""
    t = text.strip()
    if t.startswith("http://") or t.startswith("https://"):
        return "url"
    if any(ch.isspace() for ch in t) or "." not in t:
        return "name"
    head = t.split("/")[0].split(":")[0].split("?")[0]
    ext = _extract(head)
    return "url" if ext.domain and ext.suffix else "name"


def registrable_domain(host_or_url):
    """Return the public-suffix registrable domain, or None."""
    ext = _extract(_with_scheme(host_or_url))
    if not (ext.domain and ext.suffix):
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def canonicalize_url_for_dedupe(url):
    """Lowercase host, drop www/fragment/tracking params, trim slash."""
    parts = urlsplit(_with_scheme(url))
    host = parts.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    return urlunsplit(("https", host.lower(), path, urlencode(query), ""))


def registrable_domain_matches(candidate_url, target_domain):
    """True if candidate's registrable domain equals target_domain.

    Subdomain-aware (news.acme.com matches acme.com). Use ONLY for own-domain /
    denylist checks, never for owned-profile matching on shared platforms.
    """
    cand = registrable_domain(candidate_url)
    return cand is not None and cand == target_domain.lower()


# Platforms whose account key is the FIRST path segment.
_SINGLE_SEG_PLATFORMS = {"x.com", "twitter.com", "github.com", "medium.com",
                         "substack.com", "facebook.com", "instagram.com",
                         "tiktok.com"}
# Platforms where the account key is the first TWO segments (prefix/slug).
_TWO_SEG_PREFIXES = {"linkedin.com": {"company", "in", "school"},
                     "youtube.com": {"channel", "c", "user"}}


def _account_key(url):
    """Platform-specific account key, or '' if none. Never a substring."""
    dom = registrable_domain(url)
    segs = [s for s in urlsplit(_with_scheme(url)).path.split("/") if s]
    if not segs:
        return ""
    if dom in _SINGLE_SEG_PLATFORMS:
        return f"{dom}:{segs[0].lower()}"
    if dom == "youtube.com" and segs[0].startswith("@"):
        return f"{dom}:{segs[0].lower()}"          # youtube.com/@handle
    prefixes = _TWO_SEG_PREFIXES.get(dom)
    if prefixes and len(segs) >= 2 and segs[0].lower() in prefixes:
        return f"{dom}:{segs[0].lower()}/{segs[1].lower()}"
    return ""


def owned_profile_match(candidate_url, profile_url_or_handle):
    """True only when candidate and reference resolve to the SAME platform
    account key (exact match; never substring/prefix; Codex impl points 9/10)."""
    cand = _account_key(candidate_url)
    if not cand:
        return False
    ref = profile_url_or_handle.strip()
    if "/" not in ref and "." not in ref:          # a bare handle
        handle = ref.lstrip("@").lower()
        return cand.endswith(f":{handle}") or cand.endswith(f"@{handle}")
    return _account_key(ref) == cand               # a full profile URL


def _is_valid_host(host):
    """Reject empty/edge labels; require a resolvable registrable domain."""
    if not host or host.startswith(".") or host.endswith("."):
        return False
    labels = host.split(".")
    if any(not lab or len(lab) > 63 for lab in labels):  # empty label = '..'
        return False
    if any(not all(c.isalnum() or c == "-" for c in lab) for lab in labels):
        return False
    return registrable_domain(host) is not None


def parse_homepage_input(text):
    """Normalize a URL-kind input to 'https://host', or None if invalid host."""
    host = (urlsplit(_with_scheme(text.strip())).hostname or "").lower()
    return f"https://{host}" if _is_valid_host(host) else None
```

Policy note (Codex impl point 11): `canonicalize_url_for_dedupe` deliberately
COLLAPSES http and https into one https form (and strips `www.`/fragment/tracking
params/trailing slash). This is intentional for article de-dup; a site serving
different content over http vs https is an accepted trade-off.

Add tests for `parse_homepage_input` (bare host, full URL, and an input that
yields no host → None) and for canonicalization of an IDN host and a
percent-encoded path, per §18/§19.1.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_urls_util.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: URL/domain normalization module"
```

### Task 5: Exclusion module (own-channel + denylist)

**Files:**
- Create: `research/exclusion.py`, `research/tests/test_exclusion.py`

**Interfaces:**
- Consumes: `urls_util.registrable_domain_matches`,
  `urls_util.owned_profile_match`, `categories.DENYLIST_DOMAINS`.
- Produces:
  - `ExclusionSet(resolved_domain, owned_profile_urls, owned_handles,
    allow_borderline_domains)` dataclass.
  - `is_excluded(url: str, exclusion: ExclusionSet) -> tuple[bool, str]`
    returning (excluded, reason_code). Reason codes: "own_domain",
    "own_profile", "denylist", "".

- [ ] **Step 1: Write the failing tests**

```python
from research.exclusion import ExclusionSet, is_excluded


def _es(**kw):
    base = dict(resolved_domain="acme.com", owned_profile_urls=[],
               owned_handles=[], allow_borderline_domains=set())
    base.update(kw)
    return ExclusionSet(**base)


def test_own_domain_excluded():
    ok, reason = is_excluded("https://news.acme.com/x", _es())
    assert ok and reason == "own_domain"


def test_denylist_excluded():
    ok, reason = is_excluded("https://www.g2.com/products/acme", _es())
    assert ok and reason == "denylist"


def test_reddit_excluded_by_default():
    ok, reason = is_excluded("https://reddit.com/r/acme", _es())
    assert ok and reason == "denylist"


def test_reddit_allowed_when_opted_in():
    es = _es(allow_borderline_domains={"reddit.com"})
    ok, _ = is_excluded("https://reddit.com/r/acme", es)
    assert not ok


def test_owned_handle_excluded():
    es = _es(owned_handles=["@acmehq"])
    ok, reason = is_excluded("https://x.com/acmehq/status/1", es)
    assert ok and reason == "own_profile"


def test_third_party_article_not_excluded():
    ok, reason = is_excluded("https://techcrunch.com/acme", _es())
    assert not ok and reason == ""
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_exclusion.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `exclusion.py`**

```python
"""Deterministic own-channel and denylist exclusion (runs before CURATOR)."""
from dataclasses import dataclass
from research import urls_util
from research.categories import DENYLIST_DOMAINS


@dataclass
class ExclusionSet:
    resolved_domain: str | None
    owned_profile_urls: list[str]
    owned_handles: list[str]
    allow_borderline_domains: set[str]


def is_excluded(url, exclusion):
    """Return (is_excluded, reason_code) for a candidate URL."""
    if exclusion.resolved_domain and urls_util.registrable_domain_matches(
        url, exclusion.resolved_domain
    ):
        return True, "own_domain"
    for owned in (exclusion.owned_profile_urls + exclusion.owned_handles):
        if urls_util.owned_profile_match(url, owned):  # platform+path aware
            return True, "own_profile"
    dom = urls_util.registrable_domain(url)
    if dom and dom in DENYLIST_DOMAINS:
        if dom not in exclusion.allow_borderline_domains:
            return True, "denylist"
    return False, ""
```

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_exclusion.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: own-channel and denylist exclusion"
```

### Task 6: Data model and migrations

**Files:**
- Create: `research/models.py`, `research/tests/test_models.py`
- Create (generated): `research/migrations/0001_initial.py`

**Interfaces:**
- Produces: `Run`, `Category`, `ContentItem` models with the fields in §10,
  including `Run.generation`, `Run.warnings` (JSON), `Category.error`,
  `Category.status`, `ContentItem.canonical_url`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def test_create_run_defaults():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"], lookback_months=36)
    assert run.status == "blue"
    assert run.generation == 1
    assert run.warnings == []


def test_category_and_items():
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"])
    cat = Category.objects.create(run=run, key="news", display_order=0)
    assert cat.status == "pending"
    ContentItem.objects.create(category=cat, title="t", url="https://x.com",
                               canonical_url="https://x.com/", source="x.com")
    assert cat.items.count() == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_models.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `models.py`**

```python
"""Run / Category / ContentItem (see plans/INITIAL.md Section 10)."""
from django.db import models

RUN_STATUS = [(s, s) for s in ("blue", "green", "yellow", "red")]
CAT_STATUS = [(s, s) for s in
              ("pending", "running", "green", "yellow", "red")]


class Run(models.Model):
    input_text = models.TextField()
    input_kind = models.CharField(max_length=8)
    resolved_domain = models.CharField(max_length=255, null=True, blank=True)
    owned_profile_urls = models.JSONField(default=list)
    owned_social_handles = models.JSONField(default=list)
    selected_categories = models.JSONField(default=list)
    borderline_options = models.JSONField(default=dict)
    lookback_months = models.IntegerField(default=36)
    status = models.CharField(max_length=8, choices=RUN_STATUS,
                              default="blue")
    generation = models.IntegerField(default=1)
    celery_task_ids = models.JSONField(default=list)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    executive_overview = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    warnings = models.JSONField(default=list)

    class Meta:
        ordering = ["-id"]


class Category(models.Model):
    run = models.ForeignKey(Run, related_name="categories",
                            on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    is_borderline = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    status = models.CharField(max_length=8, choices=CAT_STATUS,
                              default="pending")
    error = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_order"]


class ContentItem(models.Model):
    category = models.ForeignKey(Category, related_name="items",
                                 on_delete=models.CASCADE)
    title = models.TextField()
    url = models.TextField()
    canonical_url = models.TextField()
    source = models.CharField(max_length=255)
    published_at = models.DateTimeField(null=True, blank=True)
    snippet = models.TextField(default="")
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["display_order"]

    @property
    def is_undated(self):
        return self.published_at is None
```

- [ ] **Step 4: Make migrations and run tests**

```bash
python manage.py makemigrations research
pytest research/tests/test_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Run/Category/ContentItem models"
```

### Task 7: Status computation (completeness model, §8)

**Files:**
- Create: `research/status.py`, `research/tests/test_status.py`

**Interfaces:**
- Produces: `compute_run_status(category_statuses: list[str],
  total_item_count: int) -> str`. Inputs are terminal category statuses
  ("green"|"yellow"|"red"); returns "green"|"yellow"|"red".

- [ ] **Step 1: Write the failing tests**

```python
from research.status import compute_run_status


def test_all_clean_with_items_is_green():
    assert compute_run_status(["green", "yellow"], 5) == "green"


def test_error_makes_yellow():
    assert compute_run_status(["green", "red"], 5) == "yellow"


def test_zero_items_is_red():
    assert compute_run_status(["yellow", "yellow"], 0) == "red"


def test_all_errored_is_red():
    assert compute_run_status(["red", "red"], 0) == "red"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_status.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `status.py`**

```python
"""Run status uses the completeness model (plans/INITIAL.md Section 8)."""


def compute_run_status(category_statuses, total_item_count):
    """Roll terminal category statuses + item total into a run status."""
    if total_item_count <= 0 or all(s == "red" for s in category_statuses):
        return "red"
    if any(s == "red" for s in category_statuses):
        return "yellow"
    return "green"  # every category finished cleanly and items exist
```

Note: a timed-out category is recorded as "red" by the reaper (§5.5), so this
function needs no separate timeout state. "yellow" categories (None found) are
clean and do not demote.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_status.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: completeness run-status computation"
```

### Task 8: Generation-fenced write helper + SupersededGeneration

**Files:**
- Create: `research/fencing.py`, `research/tests/test_fencing.py`

**Interfaces:**
- Produces:
  - `class SupersededGeneration(Exception)`.
  - `fenced_run_update(run_id: int, generation: int, **fields) -> None` — one
    compare-and-set `UPDATE ... WHERE id AND generation`; raises
    `SupersededGeneration` on zero rows.
  - `guard_generation(run_id: int, generation: int) -> None` — first-statement
    guard `UPDATE research_run SET generation=generation WHERE id AND
    generation`; raises `SupersededGeneration` on zero rows (use inside a
    transaction that then writes child rows).
  - `bump_generation(run_id: int) -> int` — atomic `generation = generation +
    1`, returns the new value (used by refresh); raises `SupersededGeneration`
    if the run row is gone.
  - `bump_generation_if_stale(run_id: int, cutoff) -> int | None` — bumps only a
    still-blue run older than `cutoff`; returns new gen or None (used by reaper).
  - `append_celery_task_id(run_id: int, generation: int, task_id: str) -> None`
    — fenced, idempotent append to `celery_task_ids`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.db import transaction
from research.models import Run, Category
from research import fencing

pytestmark = pytest.mark.django_db


def _run(gen=1):
    return Run.objects.create(input_text="A", input_kind="name",
                              generation=gen)


def test_guard_rolls_back_child_inserts():
    # Insert a child row, THEN hit a failing guard in the SAME transaction, to
    # prove the rowcount-abort discards the child insert (§18 requirement). In
    # production the guard is the FIRST statement, so the insert never happens;
    # this test deliberately orders it after to exercise the rollback.
    run = _run()
    fencing.bump_generation(run.id)  # generation == 2, so gen 1 is now stale
    with pytest.raises(fencing.SupersededGeneration):
        with transaction.atomic():
            Category.objects.create(run=run, key="news")  # child insert
            fencing.guard_generation(run.id, 1)            # 0 rows -> raise
    assert Category.objects.filter(run=run).count() == 0   # rolled back


def test_guard_allows_current_generation():
    run = _run()
    with transaction.atomic():
        fencing.guard_generation(run.id, 1)
        Category.objects.create(run=run, key="news")
    assert Category.objects.filter(run=run).count() == 1


def test_bump_is_atomic_increment():
    run = _run()
    assert fencing.bump_generation(run.id) == 2
    assert fencing.bump_generation(run.id) == 3


def test_bump_missing_run_raises():
    with pytest.raises(fencing.SupersededGeneration):
        fencing.bump_generation(999999)
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_fencing.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `fencing.py`**

```python
"""Generation fencing: the authoritative anti-clobber primitive (Sec 5.7)."""
from django.db import connection, transaction
from research.models import Run


class SupersededGeneration(Exception):
    """Raised when a write targets a run whose generation moved on."""


def guard_generation(run_id, generation):
    """First statement of a write txn; raise if the generation moved on."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation "
            "WHERE id = %s AND generation = %s",
            [run_id, generation],
        )
        if cur.rowcount == 0:
            raise SupersededGeneration(f"run {run_id} gen {generation}")


def fenced_run_update(run_id, generation, **fields):
    """Single compare-and-set UPDATE of Run fields; raise if superseded.

    One statement (`UPDATE ... WHERE id AND generation`), so no separate guard
    is needed for a Run-only write (Codex impl point 16).
    """
    updated = Run.objects.filter(id=run_id, generation=generation).update(
        **fields)
    if updated == 0:
        raise SupersededGeneration(f"run {run_id} gen {generation}")


def bump_generation(run_id):
    """Atomically increment and return the new generation (one statement)."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation + 1 "
            "WHERE id = %s RETURNING generation",
            [run_id],
        )
        row = cur.fetchone()  # None if the run was deleted concurrently
        if row is None:
            raise SupersededGeneration(f"run {run_id} missing")
        return row[0]  # SQLite 3.35+ supports RETURNING


def bump_generation_if_stale(run_id, cutoff):
    """Bump generation ONLY for a still-blue, stale run (Codex impl point 5).

    Returns the new generation, or None if the run already completed (so the
    reaper does not bump a just-finished run's generation).
    """
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE research_run SET generation = generation + 1 "
            "WHERE id = %s AND status = 'blue' AND started_at < %s "
            "RETURNING generation",
            [run_id, cutoff],
        )
        row = cur.fetchone()
        return row[0] if row else None


def append_celery_task_id(run_id, generation, task_id):
    """Fenced, idempotent append to Run.celery_task_ids (Codex impl-2 pt 5).

    Re-reads the current list inside the guarded txn so concurrent create/
    start_run writes cannot overwrite each other.
    """
    with transaction.atomic():
        guard_generation(run_id, generation)
        ids = Run.objects.values_list("celery_task_ids", flat=True).get(
            id=run_id)
        if task_id not in ids:
            Run.objects.filter(id=run_id).update(
                celery_task_ids=ids + [task_id])
```

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_fencing.py -v`. Expected: PASS (the rollback
test proves rowcount-abort discards child inserts).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: generation-fenced write helper"
```

---

## Phase 2 — External integrations (mockable seams)

### Task 9: `call_llm()` with env resolution, fallback, logging, schemas

**Files:**
- Create: `research/llm.py`, `research/schemas.py`,
  `research/tests/test_llm.py`, `research/tests/test_schemas.py`

**Interfaces:**
- Produces:
  - `resolve_llm_config(name: str) -> dict` with keys url, api_key, model,
    max_tokens, temperature; each var `<NAME>_LLM_*` falling back to
    `DEFAULT_LLM_*`.
  - `call_llm(name: str, messages: list[dict], tools: list | None = None,
    run_id=None, category_key=None) -> dict` returning
    `{"content": str, "tool_calls": list, "usage": dict|None}`. Single-shot.
  - `schemas.parse_query_planner(content) -> list[str]`,
    `parse_report(content) -> str`, etc.; raise `MalformedLLMOutput` on bad
    data (fail-loud, §6.1).

- [ ] **Step 1: Write the failing tests for config resolution**

```python
import pytest
from research.llm import resolve_llm_config


def _set_defaults(monkeypatch, **over):
    # TOKENS/TEMP MUST be numeric strings: resolve_llm_config casts them.
    vals = {"URL": "d-url", "API_KEY": "d-key", "MODEL": "d-model",
            "TOKENS": "1000", "TEMP": "0.2"}
    vals.update(over)
    for k, v in vals.items():
        monkeypatch.setenv(f"DEFAULT_LLM_{k}", v)


def test_fallback_to_default(monkeypatch):
    _set_defaults(monkeypatch)
    monkeypatch.delenv("REPORT_LLM_MODEL", raising=False)
    cfg = resolve_llm_config("REPORT")
    assert cfg["model"] == "d-model"
    assert cfg["max_tokens"] == 1000 and cfg["temperature"] == 0.2


def test_override_wins(monkeypatch):
    _set_defaults(monkeypatch)
    monkeypatch.setenv("REPORT_LLM_MODEL", "gpt-x")
    assert resolve_llm_config("REPORT")["model"] == "gpt-x"


def test_invalid_numeric_fails_loud(monkeypatch):
    _set_defaults(monkeypatch, TOKENS="not-int")
    with pytest.raises(ValueError):
        resolve_llm_config("REPORT")
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_llm.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `resolve_llm_config` and `call_llm`**

```python
"""Single entry point for all LLM calls (plans/INITIAL.md Sections 6, 7)."""
import os
import time
import logging

_FIELDS = {
    "url": "URL", "api_key": "API_KEY", "model": "MODEL",
    "max_tokens": "TOKENS", "temperature": "TEMP",
}
_llm_logger = logging.getLogger("drumbeat.llm")


def resolve_llm_config(name):
    """Resolve <NAME>_LLM_* with fallback to DEFAULT_LLM_* for each field."""
    cfg = {}
    for field, suffix in _FIELDS.items():
        val = os.environ.get(f"{name}_LLM_{suffix}")
        if val is None:
            val = os.environ[f"DEFAULT_LLM_{suffix}"]  # required; fail loud
        cfg[field] = val
    cfg["max_tokens"] = int(cfg["max_tokens"])
    cfg["temperature"] = float(cfg["temperature"])
    return cfg


def _client(cfg):
    from openai import OpenAI  # imported lazily, per-process
    return OpenAI(base_url=cfg["url"], api_key=cfg["api_key"])


def call_llm(name, messages, tools=None, run_id=None, category_key=None):
    """One request -> one response. Logs the full turn. No internal loop."""
    import uuid
    import json
    cfg = resolve_llm_config(name)
    request_id = uuid.uuid4().hex
    started = time.time()
    resp = _client(cfg).chat.completions.create(
        model=cfg["model"], messages=messages, tools=tools or None,
        max_tokens=cfg["max_tokens"], temperature=cfg["temperature"],
    )
    choice = resp.choices[0].message
    result = {
        "content": choice.content or "",
        "tool_calls": [tc.model_dump() for tc in (choice.tool_calls or [])],
        "usage": resp.usage.model_dump() if resp.usage else None,
    }
    # Log ONE JSON payload as the message. Do NOT use extra={"name": ...} etc.:
    # "name"/"module"/"msg" are reserved LogRecord attrs and raise KeyError.
    # cfg (which holds api_key) is NEVER logged -> redaction by omission.
    try:
        _llm_logger.info(json.dumps({
            "request_id": request_id, "call_point": name,
            "model": cfg["model"], "run_id": run_id,
            "category_key": category_key,
            "duration_s": round(time.time() - started, 3),
            "usage": result["usage"], "prompt": messages,
            "response": result["content"],
        }))
    except Exception as exc:  # a logging failure must not kill the run
        logging.getLogger("drumbeat").warning("llm log failed: %s", exc)
    return result
```

Configure a dedicated `RotatingFileHandler` for the `drumbeat.llm` logger in
settings, with a per-process filename containing the PID and a bounded
`maxBytes`/`backupCount` (from §7 tunables). Redaction is by omission: `cfg`
(which holds `api_key`) is never passed to the logger. At startup (Task 11 /
`manage.py`), verify the log directory is writable and **fail loud** if not; a
mid-run write error is caught above and downgraded to a warning (never fails the
task). Add a test asserting an `api_key` value never appears in a captured log
record, and a test that a raised logging call does not propagate out of
`call_llm`.

- [ ] **Step 4: Write and pass schema tests (`test_schemas.py`)**

```python
import pytest
from research.schemas import (parse_query_planner, parse_report,
                              MalformedLLMOutput)


def test_parse_query_planner_ok():
    assert parse_query_planner('{"queries": ["a", "b"]}') == ["a", "b"]


def test_parse_query_planner_strips_code_fence():
    raw = "```json\n{\"queries\": [\"a\"]}\n```"
    assert parse_query_planner(raw) == ["a"]


def test_parse_query_planner_malformed_raises():
    with pytest.raises(MalformedLLMOutput):
        parse_query_planner("not json")


def test_parse_report_ok():
    assert parse_report('{"executive_overview": "hi"}') == "hi"
```

Implement `research/schemas.py`:

```python
"""Strict parsers for structured LLM output (plans/INITIAL.md Section 6.1)."""
import json


class MalformedLLMOutput(Exception):
    """Raised when a call-point's output does not match its schema."""


def _load(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedLLMOutput(str(exc)) from exc


def parse_query_planner(content):
    data = _load(content)
    queries = data["queries"]  # fail loud if key absent
    if not isinstance(queries, list) or not all(
        isinstance(q, str) for q in queries
    ):
        raise MalformedLLMOutput("queries must be a list of strings")
    return queries


def _bounded_str(value, env_var, default):
    import os
    if not isinstance(value, str):  # null/array/object must fail loud (§6.1)
        raise MalformedLLMOutput(f"expected string, got {type(value).__name__}")
    return value[: int(os.environ.get(env_var, default))]


def parse_report(content):
    return _bounded_str(_load(content)["executive_overview"],
                        "REPORT_MAX_CHARS", "4000")


def parse_category_summary(content):
    return _bounded_str(_load(content)["summary"], "SUMMARY_MAX_CHARS", "1200")


def _require_url_list(value, label):
    if not isinstance(value, list) or not all(
        isinstance(x, dict) and isinstance(x.get("url"), str) for x in value
    ):
        raise MalformedLLMOutput(f"{label} must be a list of {{url: str}}")
    return value


def parse_curator(content):
    data = _load(content)
    for key in ("accepted", "rejected", "duplicates", "done"):
        if key not in data:
            raise MalformedLLMOutput(f"curator missing key: {key}")
    if not isinstance(data["done"], bool):
        raise MalformedLLMOutput("done must be bool")
    _require_url_list(data["accepted"], "accepted")  # accepted is [{url}] only
    data.setdefault("tool_call", None)
    return data


def parse_identity(content):
    data = _load(content)
    for key in ("official_domain", "owned_profile_urls",
                "owned_social_handles", "confidence", "matched"):
        if key not in data:  # all documented keys required (§6.1)
            raise MalformedLLMOutput(f"identity missing key: {key}")
    if not isinstance(data["matched"], bool):
        raise MalformedLLMOutput("matched must be bool")
    if data["confidence"] not in ("high", "medium", "low"):
        raise MalformedLLMOutput("confidence must be high/medium/low")
    for k in ("owned_profile_urls", "owned_social_handles"):
        if not isinstance(data[k], list):
            raise MalformedLLMOutput(f"{k} must be a list")
    dom = data["official_domain"]
    if data["matched"] and not isinstance(dom, str):
        raise MalformedLLMOutput("matched=true requires a string domain")
    if dom is not None and not isinstance(dom, str):
        raise MalformedLLMOutput("official_domain must be str or null")
    return data
```

All five parsers are defined here so later tasks (12, 13, 14) can consume them.
They are STRICT: null/array/object where a string is expected, missing required
keys, wrong types, or bad `confidence` values all raise `MalformedLLMOutput`
(fail-loud, §6.1). `official_domain` may be null ONLY when `matched` is false.
Run: `pytest research/tests/test_llm.py research/tests/test_schemas.py -v`.
Expected: PASS. Add malformed-output tests: `parse_report` with a null/array
value; `parse_curator` with a missing key and with `accepted:[{title:...}]`
(no url); `parse_identity` with a missing `matched` key and a bad `confidence`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: call_llm, env resolution, output schemas"
```

### Task 10: `tavily_search()` wrapper with time-window and caps

**Files:**
- Create: `research/tavily.py`, `research/tests/test_tavily.py`

**Interfaces:**
- Produces: `tavily_search(query: str, lookback_months: int,
  max_results: int) -> list[dict]` where each dict is
  `{title, url, source, published_at (datetime|None), snippet}`. Snippet is
  truncated to `MAX_SNIPPET_CHARS`. The Tavily client call is isolated so tests
  patch it.

- [ ] **Step 1: Write the failing test (patching the raw client)**

```python
from datetime import datetime, timezone
from unittest.mock import patch
from research import tavily


def test_maps_and_truncates(monkeypatch):
    monkeypatch.setenv("MAX_SNIPPET_CHARS", "5")
    raw = {"results": [{"title": "T", "url": "https://x.com/a",
           "content": "abcdefgh", "published_date": "2025-01-02"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert items[0]["snippet"] == "abcde"
    assert items[0]["published_at"] == datetime(2025, 1, 2,
                                                tzinfo=timezone.utc)
    assert items[0]["source"] == "x.com"


def test_missing_date_is_none_and_kept(monkeypatch):
    raw = {"results": [{"title": "T", "url": "https://x.com/a",
           "content": "c"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert len(items) == 1 and items[0]["published_at"] is None


def test_out_of_window_dated_item_dropped():
    raw = {"results": [{"title": "old", "url": "https://x.com/a",
           "content": "c", "published_date": "2010-01-01"}]}
    with patch.object(tavily, "_raw_search", return_value=raw):
        items = tavily.tavily_search("q", 36, 10)
    assert items == []  # dated, older than the window -> dropped (§9 layer 2)
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_tavily.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `tavily.py`**

```python
"""Tavily search wrapper: the single mock seam for search (Section 9)."""
import os
from datetime import datetime, timedelta, timezone
from research import urls_util


def _raw_search(query, days, max_results):
    from tavily import TavilyClient  # lazy, per-process
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    # topic="news" is required for Tavily's day-window to apply; see the note
    # below on the known limitation for non-news categories.
    return client.search(query=query, max_results=max_results,
                         days=days, topic="news")


def _parse_date(value):
    if not value:
        return None
    try:  # tz-aware UTC so it stores cleanly under Django USE_TZ=True
        return datetime.fromisoformat(value[:10]).replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _within_window(published_at, lookback_months):
    if published_at is None:
        return True  # undated is kept: best-effort window (Section 9)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_months * 30)
    return published_at >= cutoff


def tavily_search(query, lookback_months, max_results):
    """Search, map, and post-filter by window (§9 layer 2). Undated kept."""
    days = lookback_months * 30
    max_snippet = int(os.environ.get("MAX_SNIPPET_CHARS", "300"))
    raw = _raw_search(query, days, max_results)
    items = []
    for r in raw["results"]:
        url = r["url"]
        published = _parse_date(r.get("published_date"))
        if not _within_window(published, lookback_months):
            continue  # drop dated-but-out-of-window results
        items.append({
            "title": r["title"],
            "url": url,
            "source": urls_util.registrable_domain(url) or "",
            "published_at": published,
            "snippet": (r.get("content") or "")[:max_snippet],
        })
    return items
```

Notes: `.get("published_date")`/`.get("content")` are legitimate here — these
fields are genuinely optional in Tavily results (§9/§16), not expected-present.
Known limitation: `topic="news"` is hardcoded because Tavily's `days` window
only applies under that topic; per-category topic tuning is deferred (see
`docs/FUTURE-IMPROVEMENTS.md`).

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_tavily.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: tavily_search wrapper with time-window"
```

---

## Phase 3 — Orchestration (Celery)

### Task 11: Celery app, explicit settings, worker-side config check

**Files:**
- Create: `drumbeat/celery.py`, `research/tests/test_celery_config.py`
- Modify: `drumbeat/__init__.py`, `manage.py`

**Interfaces:**
- Produces: `drumbeat.celery.app` configured per §17.1; both `manage.py` and the
  Celery worker call `validate_required_env()` at startup.

- [ ] **Step 1: Write the failing test**

```python
from drumbeat.celery import app


def test_celery_settings():
    conf = app.conf
    assert conf.task_serializer == "json"
    assert conf.task_acks_late is False   # §17.1 decision: no redelivery
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_reject_on_worker_lost is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_celery_config.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `drumbeat/celery.py`**

```python
"""Celery app with explicit settings (plans/INITIAL.md Section 17.1)."""
import os
from celery import Celery
from celery.signals import worker_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "drumbeat.settings")
app = Celery("drumbeat")
# Pull CELERY_* from Django settings so tests can flip eager via settings/app.
app.config_from_object("django.conf:settings", namespace="CELERY")
# REDIS_URL is REQUIRED at runtime — no localhost:6379 fallback (§14). Tests set
# it via pytest.ini env. `os.environ["REDIS_URL"]` fails loud if absent.
app.conf.update(
    broker_url=os.environ["REDIS_URL"],
    result_backend=os.environ["REDIS_URL"],
    result_expires=24 * 3600,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # acks_late/reject_on_worker_lost = False (§17.1 decision): do NOT redeliver
    # lost tasks; the reaper owns lost-worker recovery, avoiding same-generation
    # duplicate execution.
    task_acks_late=False,
    task_reject_on_worker_lost=False,
    worker_prefetch_multiplier=1,
    worker_concurrency=int(os.environ.get("WORKER_CONCURRENCY", "4")),
    task_track_started=True,
    task_soft_time_limit=int(os.environ.get("SUBTASK_SOFT_LIMIT", "180")),
    task_time_limit=int(os.environ.get("SUBTASK_HARD_LIMIT", "210")),
    beat_schedule={
        "reap-stuck-runs": {
            "task": "research.tasks.reap_stuck_runs",
            "schedule": float(os.environ.get("REAPER_INTERVAL_SECONDS",
                                             "60")),
        }
    },
)
app.autodiscover_tasks(["research"])


@worker_init.connect
def _check_config(**kwargs):
    # worker_init fires ONCE in the master before forking, so a missing-config
    # worker refuses to boot (not a crash-loop of prefork children).
    from research.config_check import validate_required_env
    validate_required_env()
```

In `drumbeat/__init__.py`: `from .celery import app as celery_app`. In
`manage.py`, call `validate_required_env()` before `execute_from_command_line`
(skip when running under pytest — see Task 2). Also add a log-path check at
startup (Task 9) so an unusable LLM-log directory fails loud here too.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_celery_config.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Celery app with explicit settings"
```

### Task 12: Per-category research pipeline (pure, mock-driven)

**Files:**
- Create: `research/pipeline.py`, `research/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `call_llm`, `tavily_search`, `exclusion.is_excluded`,
  `schemas.*`.
- Produces: `research_category(company, category_key, lookback_months,
  exclusion) -> dict` returning
  `{"items": [item...], "summary": str|None}`. It runs QUERY_PLANNER, searches,
  applies deterministic exclusion, runs the bounded CURATOR loop, dedupes within
  the category, caps items, and runs CATEGORY_SUMMARY. No DB access here.

- [ ] **Step 1: Write the failing test (all LLM/search mocked)**

```python
from unittest.mock import patch
from research import pipeline
from research.exclusion import ExclusionSet


def _es():
    return ExclusionSet("acme.com", [], [], set())


def test_pipeline_filters_own_domain_and_summarizes(monkeypatch):
    monkeypatch.setenv("MAX_ITEMS_PER_CATEGORY", "10")
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "1")
    search_items = [
        {"title": "A", "url": "https://acme.com/x", "source": "acme.com",
         "published_at": None, "snippet": "s"},
        {"title": "B", "url": "https://news.com/y", "source": "news.com",
         "published_at": None, "snippet": "s"},
    ]
    curator_out = {"content": '{"accepted": [{"url": "https://news.com/y"}],'
                   '"rejected": [], "duplicates": [], "tool_call": null,'
                   '"done": true}', "tool_calls": [], "usage": None}
    planner_out = {"content": '{"queries": ["acme news"]}',
                   "tool_calls": [], "usage": None}
    summary_out = {"content": '{"summary": "About Acme."}',
                   "tool_calls": [], "usage": None}
    with patch.object(pipeline, "tavily_search", return_value=search_items), \
         patch.object(pipeline, "call_llm",
                      side_effect=[planner_out, curator_out, summary_out]):
        result = pipeline.research_category("Acme", "news", 36, _es())
    urls = [i["url"] for i in result["items"]]
    assert "https://acme.com/x" not in urls   # own domain removed pre-curator
    assert "https://news.com/y" in urls
    assert result["summary"] == "About Acme."
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_pipeline.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `pipeline.py`**

```python
"""Pure per-category research (no DB): planner -> search -> curator loop."""
import os
from research.llm import call_llm
from research.tavily import tavily_search
from research.exclusion import is_excluded
from research.urls_util import canonicalize_url_for_dedupe
from research import schemas


def _plan_queries(company, category_key):
    prompt = (f"Company: {company}. Category: {category_key}. Return JSON "
              '{"queries": [...]} of focused web search queries.')
    out = call_llm("QUERY_PLANNER",
                   [{"role": "user", "content": prompt}])
    max_q = int(os.environ.get("QUERY_PLANNER_MAX_QUERIES", "3"))
    return schemas.parse_query_planner(out["content"])[:max_q]


def _ingest(queries, lookback_months, exclusion, pool, seen):
    """Search each query; add unique (by canonical URL), non-excluded items to
    `pool`, capped at MAX_CANDIDATES_PER_CATEGORY. Used for BOTH the initial and
    the curator's follow-up searches, so both honor window/caps/exclusion
    (Codex impl point 3)."""
    per = int(os.environ.get("TAVILY_RESULTS_PER_SEARCH", "10"))
    cap = int(os.environ.get("MAX_CANDIDATES_PER_CATEGORY", "40"))
    for q in queries:
        for item in tavily_search(q, lookback_months, per):
            key = canonicalize_url_for_dedupe(item["url"])
            excluded, _ = is_excluded(item["url"], exclusion)
            if excluded or key in seen:
                continue
            seen.add(key)
            pool.append(item)
            if len(pool) >= cap:
                return pool
    return pool


def research_category(company, category_key, lookback_months, exclusion):
    """Return {'items': [...], 'summary': str|None} for one category."""
    queries = _plan_queries(company, category_key)
    pool, seen = [], set()
    _ingest(queries, lookback_months, exclusion, pool, seen)
    accepted = _curate(company, category_key, pool, seen,
                       lookback_months, exclusion)
    max_items = int(os.environ.get("MAX_ITEMS_PER_CATEGORY", "20"))
    items = accepted[:max_items]
    summary = _summarize(company, category_key, items) if items else None
    return {"items": items, "summary": summary}
```

Implement the bounded `_curate` loop and `_summarize` in the same module (see
Task 13's curator detail). For this task, a single-iteration curator is enough
to pass the test; Task 13 hardens the loop and tool-calling.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_pipeline.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: per-category research pipeline"
```

### Task 13: Bounded agentic CURATOR loop with tool-calling

**Files:**
- Modify: `research/pipeline.py`
- Create: `research/tests/test_curator.py`

**Interfaces:**
- Produces: `_curate(company, category_key, pool, seen, lookback_months,
  exclusion) -> list[item]` running at most `CURATOR_MAX_ITERATIONS`, honouring
  `done`, routing follow-up searches through `_ingest` (window/caps/exclusion)
  up to `CURATOR_MAX_SEARCHES`.

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import patch
from research import pipeline


def test_curator_stops_at_iteration_cap(monkeypatch):
    monkeypatch.setenv("CURATOR_MAX_ITERATIONS", "2")
    monkeypatch.setenv("CURATOR_MAX_SEARCHES", "5")
    # Curator never says done, always requests one more search.
    from research.exclusion import ExclusionSet
    tool_turn = {"content": '{"accepted": [], "rejected": [],'
                 '"duplicates": [], "tool_call": {"query": "more"},'
                 '"done": false}', "tool_calls": [], "usage": None}
    es = ExclusionSet(None, [], [], set())
    with patch.object(pipeline, "call_llm", return_value=tool_turn), \
         patch.object(pipeline, "tavily_search", return_value=[]) as srch:
        items = pipeline._curate("Acme", "news", [], set(), 36, es)
    assert items == []
    assert srch.call_count <= 2  # bounded by iterations
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_curator.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `_curate` and `_summarize`**

```python
def _curate(company, category_key, pool, seen, lookback_months, exclusion):
    """Bounded curator: judge, optionally search more, return accepted items.

    Follow-up searches go through _ingest, so they honor the run's window, the
    result cap, and deterministic exclusion — never a hard-coded 36/10 (Codex
    impl point 3). `accepted` carries urls only; item metadata stays from Tavily.
    """
    max_iter = int(os.environ.get("CURATOR_MAX_ITERATIONS", "3"))
    max_search = int(os.environ.get("CURATOR_MAX_SEARCHES", "5"))
    accepted_urls, searches = [], 0
    for _ in range(max_iter):
        prompt = _curator_prompt(company, category_key, pool)
        out = call_llm("CURATOR", [{"role": "user", "content": prompt}])
        data = schemas.parse_curator(out["content"])
        accepted_urls = [a["url"] for a in data["accepted"]]
        if data["done"] or not data["tool_call"] or searches >= max_search:
            break
        searches += 1
        _ingest([data["tool_call"]["query"]], lookback_months, exclusion,
                pool, seen)
    by_url = {i["url"]: i for i in pool}
    return [by_url[u] for u in accepted_urls if u in by_url]


def _summarize(company, category_key, items):
    prompt = _summary_prompt(company, category_key, items)
    out = call_llm("CATEGORY_SUMMARY",
                   [{"role": "user", "content": prompt}])
    return schemas.parse_category_summary(out["content"])
```

`parse_curator` and `parse_category_summary` are already defined in Task 9's
`schemas.py`; `_curate`/`_summarize` just consume them.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_curator.py research/tests/test_schemas.py -v`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: bounded agentic curator loop"
```

### Task 14: IDENTITY resolution + Celery orchestration

**Files:**
- Create: `research/identity.py`, `research/tasks.py`,
  `research/tests/test_identity.py`, `research/tests/test_tasks.py`

**Interfaces:**
- Consumes: `pipeline.research_category`, `fencing.*`, `status.*`,
  `schemas.parse_identity`, `schemas.parse_report`, `exclusion.ExclusionSet`.
- Produces:
  - `identity.resolve_identity(run) -> (domain|None, profile_urls, handles)`.
  - `tasks.start_run(run_id)`, `tasks.run_category(run_id, gen, key)`,
    `tasks.finalize_run(results, run_id, gen)`, `tasks.reap_stuck_runs()`.

- [ ] **Step 1: TDD `resolve_identity`**

`research/tests/test_identity.py`:

```python
import pytest
from unittest.mock import patch
from research.models import Run
from research import identity

pytestmark = pytest.mark.django_db


def test_url_input_derives_domain_without_llm():
    run = Run.objects.create(input_text="https://acme.com/x",
                             input_kind="url")
    with patch.object(identity, "call_llm") as llm:
        domain, profiles, handles = identity.resolve_identity(run)
    assert domain == "acme.com"
    llm.assert_not_called()


def test_name_input_uses_llm_and_no_match_returns_none():
    run = Run.objects.create(input_text="Acme", input_kind="name")
    out = {"content": '{"matched": false, "official_domain": null,'
           '"confidence": "low", "owned_profile_urls": [],'
           '"owned_social_handles": []}',
           "tool_calls": [], "usage": None}
    with patch.object(identity, "tavily_search", return_value=[]), \
         patch.object(identity, "call_llm", return_value=out):
        domain, profiles, handles = identity.resolve_identity(run)
    assert domain is None
```

Implement `research/identity.py`:

```python
"""IDENTITY resolution: official domain + owned channels (Section 19)."""
from research.llm import call_llm
from research.tavily import tavily_search
from research import schemas, urls_util


def resolve_identity(run):
    """Return (domain|None, owned_profile_urls, owned_handles).

    URL input derives the domain deterministically (no LLM). Name input asks
    call_llm("IDENTITY"), aided by a Tavily lookup. Exceptions bubble up and are
    treated as non-fatal by the caller (Section 5.4).
    """
    if run.input_kind == "url":
        return urls_util.registrable_domain(run.input_text), [], []
    hints = [h["url"] for h in
             tavily_search(f"{run.input_text} official website", 36, 5)]
    prompt = (f'Company: "{run.input_text}". Candidate URLs: {hints}. '
              'Return JSON {official_domain, owned_profile_urls, '
              'owned_social_handles, confidence, matched}.')
    data = schemas.parse_identity(
        call_llm("IDENTITY", [{"role": "user", "content": prompt}],
                 run_id=run.id)["content"])
    if not data["matched"] or not data["official_domain"]:
        return None, data["owned_profile_urls"], data["owned_social_handles"]
    return (urls_util.registrable_domain(data["official_domain"]),
            data["owned_profile_urls"], data["owned_social_handles"])
```

Run: `pytest research/tests/test_identity.py -v`. Expected: PASS.

- [ ] **Step 2: Write the failing orchestration + reaper + fan-in tests**

Drive the task bodies DIRECTLY (`.run(...)`) rather than through an eager chord —
eager-chord result propagation is version-fragile and `task_store_eager_result`
would touch Redis. `start_run`'s chord dispatch is covered by the E2E run
(Task 22).

```python
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
                             selected_categories=["news", "podcasts"])
    for i, key in enumerate(["news", "podcasts"]):
        Category.objects.create(run=run, key=key, display_order=i)
    gen = run.generation

    def fake_research(company, key, months, exclusion):
        if key == "podcasts":
            raise RuntimeError("boom")
        return {"items": [{"title": "t", "url": "https://n.com/a",
                "source": "n.com", "published_at": None, "snippet": "s"}],
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


def test_reaper_terminalizes_stuck_run():
    run = Run.objects.create(input_text="Acme", input_kind="name",
        status="blue", started_at=timezone.now() - timedelta(hours=1))
    Category.objects.create(run=run, key="news", status="running")
    tasks.reap_stuck_runs()
    run.refresh_from_db()
    assert run.status == "red"  # no items anywhere
    assert run.ended_at is not None
    assert Category.objects.get(run=run, key="news").status == "red"
```

- [ ] **Step 3: Run and confirm failure**

Run: `pytest research/tests/test_tasks.py -v`. Expected: FAIL. All tests call
task bodies directly, so coverage does not depend on eager-chord result
propagation or a live Redis.

- [ ] **Step 4: Implement `tasks.py`**

```python
"""Celery tasks: chord orchestration, fenced writes, reaper (Section 5)."""
import os
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from celery import shared_task, chord
from research.models import Run, Category, ContentItem
from research.pipeline import research_category
from research.identity import resolve_identity
from research.exclusion import ExclusionSet
from research.fencing import (guard_generation, bump_generation,
                              bump_generation_if_stale, fenced_run_update,
                              append_celery_task_id, SupersededGeneration)
from research.status import compute_run_status
from research.categories import BORDERLINE_DOMAIN_MAP
from research.llm import call_llm
from research import schemas, urls_util


@shared_task
def start_run(run_id):
    try:
        _start_run_body(run_id)
    except (SupersededGeneration, Run.DoesNotExist):
        return  # deleted/refreshed before start: expected control flow (§5.4)


def _start_run_body(run_id):
    run = Run.objects.get(id=run_id)
    gen = run.generation
    warnings = list(run.warnings)
    try:
        domain, profiles, handles = resolve_identity(run)
        if domain is None:
            warnings.append("identity: domain unresolved; own-domain "
                            "exclusion skipped")
    except Exception as exc:  # IDENTITY is non-fatal (Section 5.4)
        domain, profiles, handles = None, [], []
        warnings.append(f"identity: {exc}")
    # started_at is set at CREATE (Task 15, Codex impl point 20), not here.
    fenced_run_update(run_id, gen, resolved_domain=domain,
                      owned_profile_urls=profiles,
                      owned_social_handles=handles, warnings=warnings)
    header = [run_category.s(run_id, gen, c.key)
              for c in run.categories.all()]
    result = chord(header)(finalize_run.s(run_id, gen))
    # Track the chord/finalize id for best-effort revocation (fenced, idempotent
    # append so it can't clobber the parent id stored at create).
    try:
        append_celery_task_id(run_id, gen, result.id)
    except SupersededGeneration:
        pass


def _exclusion_for(run):
    allow = set()
    for key, ticked in run.borderline_options.items():
        if ticked:
            allow |= BORDERLINE_DOMAIN_MAP.get(key, set())
    return ExclusionSet(run.resolved_domain, run.owned_profile_urls,
                        run.owned_social_handles, allow)


def _order_items(items):
    dated = [i for i in items if i["published_at"] is not None]
    undated = [i for i in items if i["published_at"] is None]
    dated.sort(key=lambda i: i["published_at"], reverse=True)
    return dated + undated  # undated last (Section 10)


@shared_task
def run_category(run_id, generation, category_key):
    try:
        _run_category_body(run_id, generation, category_key)
    except SupersededGeneration:
        return  # expected: refreshed/deleted/reaped; not a failure
    except Exception as exc:
        _mark_category_red(run_id, generation, category_key, str(exc))
    return category_key


def _run_category_body(run_id, generation, category_key):
    run = Run.objects.get(id=run_id)
    with transaction.atomic():
        guard_generation(run_id, generation)
        Category.objects.filter(run_id=run_id, key=category_key).update(
            status="running", started_at=timezone.now())
    result = research_category(run.input_text, category_key,
                              run.lookback_months, _exclusion_for(run))
    ordered = _order_items(result["items"])
    with transaction.atomic():
        guard_generation(run_id, generation)
        cat = Category.objects.get(run_id=run_id, key=category_key)
        cat.items.all().delete()  # delete-then-insert: redelivery-safe
        ContentItem.objects.bulk_create([
            ContentItem(
                category=cat, title=i["title"], url=i["url"],
                canonical_url=urls_util.canonicalize_url_for_dedupe(i["url"]),
                source=i["source"], published_at=i["published_at"],
                snippet=i["snippet"], display_order=n)
            for n, i in enumerate(ordered)])
        cat.summary = result["summary"]
        cat.status = "green" if ordered else "yellow"
        cat.ended_at = timezone.now()
        cat.save(update_fields=["summary", "status", "ended_at"])


def _mark_category_red(run_id, generation, category_key, message):
    try:
        with transaction.atomic():
            guard_generation(run_id, generation)
            Category.objects.filter(run_id=run_id, key=category_key).update(
                status="red", error=message, ended_at=timezone.now())
    except SupersededGeneration:
        return  # superseded run: do NOT mark red (expected control flow)


@shared_task
def finalize_run(results, run_id, generation):
    try:
        _finalize_body(run_id, generation)
    except SupersededGeneration:
        return  # refreshed/deleted/reaped: expected control flow
    except Exception:
        # Boundary 2 (§5.4): a REPORT/DB failure must still set a terminal
        # status, else the run is stuck BLUE until the reaper.
        _degrade_run_terminal(run_id, generation)


def _degrade_run_terminal(run_id, generation):
    try:
        with transaction.atomic():
            guard_generation(run_id, generation)
            total = ContentItem.objects.filter(
                category__run_id=run_id).count()
            Run.objects.filter(id=run_id, generation=generation,
                               status="blue").update(
                status="yellow" if total else "red",
                executive_overview="Report generation failed; results below "
                                   "may be partial.",
                ended_at=timezone.now())
    except SupersededGeneration:
        return


def _finalize_body(run_id, generation):
    run = Run.objects.get(id=run_id)
    if run.generation != generation:
        raise SupersededGeneration(run_id)
    cats = sorted(run.categories.all(), key=lambda c: c.display_order)
    seen, remove_ids, kept, kept_items = set(), [], {}, []
    for cat in cats:  # dedup plan in memory (NO txn held; §5.3)
        n = 0
        for item in cat.items.all():
            if item.canonical_url in seen:
                remove_ids.append(item.id)  # a lower-priority duplicate
            else:
                seen.add(item.canonical_url)
                kept_items.append((cat.key, item))  # survives the dedup
                n += 1
        kept[cat.id] = n
    total = sum(kept.values())
    if total > 0:  # REPORT is a network call -> OUTSIDE any transaction.
        # Build the prompt from KEPT items only, so the overview never mentions
        # a duplicate about to be removed (Codex impl-2 point 6).
        overview = schemas.parse_report(call_llm(
            "REPORT", [{"role": "user",
                        "content": _report_prompt(run, kept_items)}],
            run_id=run_id)["content"])
    else:
        overview = ("No third-party content was found in the selected "
                    "time window.")
    with transaction.atomic():  # one short fenced write
        guard_generation(run_id, generation)
        ContentItem.objects.filter(id__in=remove_ids).delete()
        statuses = []
        for cat in cats:
            if kept[cat.id] == 0 and cat.status == "green":
                cat.status, cat.summary = "yellow", None
                cat.save(update_fields=["status", "summary"])
            statuses.append(cat.status)
        run_status = compute_run_status(statuses, total)
        updated = Run.objects.filter(
            id=run_id, generation=generation, status="blue").update(
            executive_overview=overview, ended_at=timezone.now(),
            status=run_status)
        if updated == 0:  # a same-generation duplicate finalize already
            raise SupersededGeneration(run_id)  # ran; roll back our dedup writes


@shared_task
def reap_stuck_runs():
    max_dur = int(os.environ.get("RUN_MAX_DURATION_SECONDS", "600"))
    cutoff = timezone.now() - timedelta(seconds=max_dur)
    for run in Run.objects.filter(status="blue", started_at__lt=cutoff):
        try:
            _reap_one(run.id, cutoff)
        except SupersededGeneration:
            continue  # overlapping sweep/refresh already handled it (§5.5)


def _reap_one(run_id, cutoff):
    # Conditional bump: only a still-blue, still-stale run (Codex impl point 5).
    gen = bump_generation_if_stale(run_id, cutoff)
    if gen is None:
        return  # run completed between the SELECT and now; do not touch it
    with transaction.atomic():
        guard_generation(run_id, gen)  # raises if a racing bump moved gen
        Category.objects.filter(run_id=run_id,
            status__in=["pending", "running"]).update(
            status="red", error="run timed out", ended_at=timezone.now())
        statuses = [c.status for c in
                    Run.objects.get(id=run_id).categories.all()]
        total = ContentItem.objects.filter(category__run_id=run_id).count()
        # After the conditional bump the run is still blue at our generation, so
        # this should affect exactly 1 row. Check the rowcount for discipline: a
        # 0 means a concurrent terminal writer won -> treat as superseded (Codex
        # impl-2 point 8), which rolls back our category writes too.
        updated = Run.objects.filter(
            id=run_id, generation=gen, status="blue").update(
            status=compute_run_status(statuses, total),
            executive_overview="Run timed out; results may be partial.",
            ended_at=timezone.now())
        if updated == 0:
            raise SupersededGeneration(f"run {run_id} reaper lost the race")
```

Also implement the bounded prompt builders (kept simple; they enforce §6.2
caps). In `tasks.py`:

```python
def _report_prompt(run, kept_items):
    """kept_items is a list of (category_key, ContentItem) surviving dedup."""
    cap = int(os.environ.get("REPORT_MAX_ITEMS_TOTAL", "60"))
    snip = int(os.environ.get("REPORT_MAX_ITEM_SNIPPET_CHARS", "200"))
    lines = [f"[{key}] {item.title} :: {item.snippet[:snip]}"
             for key, item in kept_items[:cap]]
    body = "\n".join(lines)
    return (f'Write a concise executive overview of "{run.input_text}" from '
            f'these findings. Return JSON {{"executive_overview": "..."}}.\n'
            f'{body}')
```

Add `_curator_prompt(company, category_key, pool)` and
`_summary_prompt(company, category_key, items)` to `pipeline.py` as analogous
bounded builders — both MUST be defined or `_curate`/`_summarize` raise
`NameError`. (`BORDERLINE_DOMAIN_MAP` and the `reddit.com` denylist entry are
defined in Task 3.) The beat registration for `reap_stuck_runs` lives in
`celery.py` (Task 11).

- [ ] **Step 5: Run tests and commit**

Run: `pytest research/tests/test_tasks.py research/tests/test_identity.py -v`.
Expected: PASS. Add a **cap acceptance test** (Codex impl point 26): with
`REPORT_MAX_ITEMS_TOTAL=2`, pass a `kept_items` list of 5 `(key, item)` tuples and
assert `_report_prompt(run, kept_items)` contains at most 2 item lines — proving
the builder enforces the cap. Add the analogous cap test for `_curator_prompt`/
`_summary_prompt` in Task 13. Also add a **dedup test** (Codex impl-2 point 6):
two categories holding the same canonical URL → run `finalize_run` and assert the
REPORT prompt passed to `call_llm` (capture via the mock) contains the URL's item
exactly once (the lower-priority duplicate is absent).

```bash
git add -A && git commit -m "feat: identity, chord orchestration, fan-in, reaper"
```

---

## Phase 4 — API (DRF)

### Task 15: Serializers and read/create endpoints

**Files:**
- Create: `research/serializers.py`, `research/views.py`, `research/urls.py`,
  `research/tests/test_api.py`
- Modify: `drumbeat/urls.py`

**Interfaces:**
- Produces:
  - `POST /api/runs/` — validate (§11) and start a run; 400 on bad input.
  - `GET /api/runs/` — newest-first list with a default limit.
  - `GET /api/runs/<id>/` — the §11 serializer contract (item_count and
    total_item_count computed server-side).

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import patch
from research.models import Run

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


def test_detail_contract_nests_items(client):
    from research.models import Category, ContentItem
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
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_api.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement the error envelope, serializers, views, urls**

Error envelope (§13 needs a field to map errors to inputs): add a DRF custom
exception handler returning `{"detail": str, "field": str | null}` for every
400, and set it in `REST_FRAMEWORK["EXCEPTION_HANDLER"]`. `RunCreateSerializer`
raises validation errors carrying the offending field so the handler can fill
`field`.

`RunCreateSerializer` validation (all §11 paths, each → 400 via the envelope):
- `input_text`: strip; reject empty/whitespace-only; reject longer than
  `MAX_INPUT_LENGTH` (add to config, default 2000).
- compute `input_kind = detect_input_kind(input_text)`; if kind == "url",
  require `parse_homepage_input(input_text)` to yield a host, else raise
  `ValidationError` (covers bare `https://` with no host); set
  `resolved_domain = registrable_domain(input_text)` (a bare domain like
  `acme.com`, the form `registrable_domain_matches` expects — NOT the
  `https://host` string).
- `lookback_months`: integer in [1, 600]; default 36; else reject.
- `borderline_options`: dict; wrap `selected_category_keys(borderline_options)`
  in `try/except KeyError` and re-raise as a DRF `ValidationError` with
  `field="borderline_options"` (a raw `KeyError` would 500, not 400).
- build `selected_categories = selected_category_keys(borderline_options)`.

Read serializers with the exact §11 nesting:
- `ContentItemSerializer`: title, url, source, published_at, is_undated,
  snippet, display_order.
- `CategorySerializer`: key, is_borderline, display_order, status, error,
  summary, `item_count = SerializerMethodField` (server-computed via
  `obj.items.count()`), `items = ContentItemSerializer(many=True)`.
- `RunDetailSerializer`: id, input_text, input_kind, status, started_at,
  ended_at, executive_overview, error, warnings,
  `total_item_count = SerializerMethodField`, and `categories =
  CategorySerializer(many=True)` ordered by display_order.
- `RunListSerializer`: id, input_text, status, started_at.

Views (`RunViewSet` or APIViews) wired in `research/urls.py`, included under
`/api/` in `drumbeat/urls.py`. On create, in ONE `transaction.atomic()`: save the
Run with `started_at=timezone.now()` (submission time, point 20) and create the
pending Category rows (is_borderline, display_order from `DISPLAY_ORDER`). Then
dispatch AFTER commit so a fast worker can never read half-committed categories
(point 19):

```python
def _dispatch(run_id):
    res = start_run.delay(run_id)
    try:  # fenced idempotent append at the CURRENT generation
        gen = Run.objects.values_list("generation", flat=True).get(id=run_id)
        append_celery_task_id(run_id, gen, res.id)
    except (SupersededGeneration, Run.DoesNotExist):
        pass  # a refresh/delete raced; id storage is best-effort only

transaction.on_commit(lambda: _dispatch(run.id))
```

`_dispatch` reads the current generation rather than assuming 1, so it is safe on
the refresh path too (Task 16 reuses it). Return 201 with the created run. List
is newest-first with a default limit (config). Detail returns
`RunDetailSerializer`.

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_api.py -v`. Expected: PASS. Add one explicit
test per 400 path in §11: whitespace-only, over-length (> `MAX_INPUT_LENGTH`),
unknown borderline key, lookback out of range (0 and 601), and malformed
URL-kind inputs that yield no valid host — `https://`, `http://`, `https://?x=1`,
and `example..com` (Codex impl point 21). Each asserts status 400 with `detail`
and `field`. Note `htp://example.com` classifies as a NAME (the detector only
recognizes `http://`/`https://`), which is acceptable — document it in the test.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: DRF serializers and run endpoints"
```

### Task 16: Refresh and delete flows

**Files:**
- Modify: `research/views.py`, `research/urls.py`
- Create: `research/tests/test_refresh_delete.py`

**Interfaces:**
- Produces: `POST /api/runs/<id>/refresh/`, `DELETE /api/runs/<id>/` per §11.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import patch
from research.models import Run, Category, ContentItem

pytestmark = pytest.mark.django_db


def test_refresh_bumps_generation_and_wipes(client):
    run = Run.objects.create(input_text="Acme", input_kind="name",
                             selected_categories=["news"], status="green")
    cat = Category.objects.create(run=run, key="news", status="green")
    ContentItem.objects.create(category=cat, title="t", url="u",
                               canonical_url="u", source="s")
    with patch("research.views.start_run"):
        resp = client.post(f"/api/runs/{run.id}/refresh/")
    run.refresh_from_db()
    assert resp.status_code in (200, 202)
    assert run.generation == 2
    assert run.status == "blue"
    assert ContentItem.objects.filter(category__run=run).count() == 0


def test_delete_removes_run(client):
    run = Run.objects.create(input_text="Acme", input_kind="name")
    with patch("research.views.revoke_task_ids"):
        resp = client.delete(f"/api/runs/{run.id}/")
    assert resp.status_code in (200, 204)
    assert not Run.objects.filter(id=run.id).exists()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest research/tests/test_refresh_delete.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `revoke_task_ids`, refresh, and delete**

Add a best-effort revocation helper in `research/views.py` that takes the id
list explicitly (refresh reads the OLD ids before resetting the row):

```python
import logging


def revoke_task_ids(task_ids):
    """Best-effort revoke of Celery task ids. Correctness relies on fencing,
    not this (Section 5.7). Never terminate=True (would SIGTERM a sibling)."""
    from drumbeat.celery import app
    for task_id in task_ids or []:
        try:
            app.control.revoke(task_id)
        except Exception as exc:
            logging.getLogger("drumbeat").warning("revoke failed: %s", exc)
```

Refresh (revocation is a network call, so it stays OUTSIDE the DB transaction —
Codex impl-2 point 4):
1. Read and keep the old `celery_task_ids`.
2. In ONE `transaction.atomic()`: `bump_generation`; delete Category/ContentItem
   rows; reset run fields (status=blue, `started_at=now`, ended_at=None,
   overview=None, error=None, warnings=[], celery_task_ids=[]); recreate pending
   Category rows.
3. Register `transaction.on_commit(lambda: _dispatch(run.id))` (same `_dispatch`
   as Task 15, storing the new parent id), so no worker starts against
   half-refreshed state.
4. AFTER commit, best-effort revoke the OLD task ids outside any transaction; on
   failure, log a warning and continue (correctness rests on fencing, §5.7).

Delete: revoke old task ids (best-effort, outside a transaction), then delete the
Run (cascades). Refresh returns 200 with the run; delete returns 204. A stale
task from the old generation self-fences (§5.7); a task that finds the run gone
treats it as supersession (§5.4).

- [ ] **Step 4: Run tests**

Run: `pytest research/tests/test_refresh_delete.py -v`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: refresh and delete flows"
```

---

## Phase 5 — Frontend (React + Vite)

### Task 17: Frontend scaffolding, API client, polling hook

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`,
  `frontend/index.html`, `frontend/src/setupTests.js`, `frontend/src/main.jsx`,
  `frontend/src/App.jsx`, `frontend/src/api.js`, `frontend/src/usePolling.js`,
  stub `frontend/src/components/HomePage.jsx` and `RunView.jsx`,
  `frontend/src/__tests__/usePolling.test.jsx`

**Interfaces:**
- Produces: `api.listRuns()`, `api.getRun(id)`, `api.createRun(payload)`,
  `api.refreshRun(id)`, `api.deleteRun(id)`; `usePolling(fn, active, deps)` that
  fetches on mount, polls ~2s while `active`, stops on unmount, pauses on
  `document.hidden`, and refetches on visibility restore.

- [ ] **Step 1: Scaffold Vite + Vitest (incl. the test setup file)**

`package.json` deps: `react`, `react-dom`, `react-router-dom`; dev deps: `vite`,
`@vitejs/plugin-react`, `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`. `vite.config.js` sets the dev-server port
from `process.env.VITE_PORT`, proxies `/api` to
`http://localhost:${process.env.DJANGO_PORT}`, and MUST configure Vitest so the
component tests can run at all:

```js
test: {
  environment: "jsdom",
  globals: true,                        // enables bare test()/expect()
  setupFiles: "./src/setupTests.js",
}
```

`frontend/src/setupTests.js`:

```js
import "@testing-library/jest-dom/vitest";   // registers toBeInTheDocument etc.
```

After writing `package.json`, run `npm install` in `frontend/` and commit the
generated `package-lock.json` (Codex impl point 22) BEFORE running Vitest — the
tests must never implicitly fetch packages, and `start_all.sh`/`run_tests.sh`
require `node_modules` to exist.

Wire routing here too: `main.jsx` wraps `<App/>` in `<BrowserRouter>`; `App.jsx`
defines `<Routes>` with `/` → `HomePage` and `/runs/:id` → `RunView`. Create
trivial stubs for `HomePage`/`RunView` (each `return null`) so the app builds
now; Tasks 18/19 flesh them out (their Files list these as Modify). Navigation
is owned by page components (inside the Router), NOT by the modal (see Task 18).

- [ ] **Step 2: Write the failing polling test (with fake timers)**

```jsx
import { renderHook } from "@testing-library/react";
import { vi } from "vitest";
import { usePolling } from "../usePolling";

test("fetches on mount, polls while active, pauses when hidden", () => {
  vi.useFakeTimers();
  const fn = vi.fn().mockResolvedValue({});
  renderHook(() => usePolling(fn, true, []));
  expect(fn).toHaveBeenCalledTimes(1);          // mount fetch
  vi.advanceTimersByTime(2000);
  expect(fn).toHaveBeenCalledTimes(2);          // one poll
  vi.useRealTimers();
});
```

- [ ] **Step 3: Implement `api.js` and `usePolling.js`**

```jsx
export async function request(path, options) {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw Object.assign(new Error("request_failed"),
      { status: resp.status, body });
  }
  return resp.status === 204 ? null : resp.json();
}
export const listRuns = () => request("/runs/");
export const getRun = (id) => request(`/runs/${id}/`);
export const createRun = (p) =>
  request("/runs/", { method: "POST", body: JSON.stringify(p) });
export const refreshRun = (id) =>
  request(`/runs/${id}/refresh/`, { method: "POST" });
export const deleteRun = (id) =>
  request(`/runs/${id}/`, { method: "DELETE" });
```

```jsx
import { useEffect, useRef } from "react";
// fn should resolve to handle its own success/error (set stale flag);
// fn resolves on success and REJECTS on failure so the hook can back off.
export function usePolling(fn, active, deps) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    let timer = null;
    const fails = { n: 0 }, skip = { n: 0 };
    // Update BOTH counters inside the handlers: run() is async, so setting
    // skip.n outside would use a stale fails.n (Codex impl-2 point 7).
    const run = () => Promise.resolve(saved.current())
      .then(() => { fails.n = 0; skip.n = 0; })
      .catch(() => { fails.n = Math.min(fails.n + 1, 5); skip.n = fails.n; });
    run();                                 // fetch on mount
    const tick = () => {
      if (document.hidden) return;
      if (skip.n > 0) { skip.n -= 1; return; }   // backoff: skip ticks
      run();
    };
    if (active) timer = setInterval(tick, 2000);
    const onVis = () => { if (active && !document.hidden) run(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);
}
```

The hook owns backoff (skips ticks after consecutive failures, resetting on
success), so §12's "retries with backoff" is met without `fn` controlling the
interval. `fn` (in HomePage/RunView) sets a `stale` flag on error and **rejects**
so the hook counts the failure; both pages then render a non-blocking
"Connection problem — retrying" banner and keep the last-known data.

- [ ] **Step 4: Run tests**

Run (in `frontend/`): `npx vitest run`. Expected: PASS. Add three more cases:
(a) while `document.hidden` is true a tick does NOT call `fn` (pause); (b)
dispatching a `visibilitychange` event with `hidden=false` while `active` calls
`fn` (refetch on restore); (c) **backoff** — with `fn` rejecting, advance the
timer and assert a tick is skipped after a failure (fewer calls than ticks),
using `await` / `vi.runAllTicks()` so the rejected promise's `.catch` sets
`skip.n` before the next tick. Toggle `document.hidden` via
`Object.defineProperty(document, "hidden", { value, configurable: true })`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: frontend scaffolding, api client, polling"
```

### Task 18: Home page, run list, New-run modal

**Files:**
- Modify: `frontend/src/components/HomePage.jsx` (created as a stub in Task 17).
- Create: `frontend/src/components/RunList.jsx`, `StatusChip.jsx`,
  `NewRunModal.jsx`, and their `__tests__`.

**Interfaces:**
- Consumes: `api.*`, `usePolling`.
- Produces: the home route with a New-run button/modal and a polled run list.

- [ ] **Step 1: Write the failing modal test**

```jsx
import { render, screen, fireEvent, waitFor } from
  "@testing-library/react";
import { vi } from "vitest";
import * as api from "../../api";
import { NewRunModal } from "../NewRunModal";

test("maps a 400 field error to the input and stays open", async () => {
  // Use a VALID input so client pre-validation passes and createRun is hit.
  vi.spyOn(api, "createRun").mockRejectedValue(
    { status: 400, body: { detail: "Unknown company", field: "input_text" } });
  render(<NewRunModal onClose={() => {}} onCreated={() => {}} />);
  fireEvent.change(screen.getByLabelText(/name or url/i),
    { target: { value: "Acme" } });
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  await waitFor(() =>
    expect(screen.getByText(/unknown company/i)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run`. Expected: FAIL.

- [ ] **Step 3: Implement the components**

`StatusChip({ variant, status, count })` — takes an explicit `variant` because
run and category vocabularies DIFFER on the same status value (§13):
- `variant="run"`: green→"Complete", yellow→"Partial", red→"Failed",
  blue→"Running" (spinner).
- `variant="category"`: green→`Found (${count})`, yellow→"None found",
  red→"Error", pending/running→"Working" (spinner).
Each chip is label + icon (never colour alone); spinners carry an `aria-label`
matching the label text.

`NewRunModal({ onClose, onCreated })`: single input **labelled exactly
"Name or URL"** and a submit button **labelled "Start"** (the tests match on
these strings via `getByLabelText`/`getByRole`, so they are authoritative);
numeric look-back (default 36), borderline checkboxes; `role="dialog"` +
`aria-modal="true"`; the 400 field error is bound to its input via
`aria-describedby` so the mapping is testable; traps
focus, focuses the input on open, closes on `Escape`; client-side pre-validation
(non-empty; integer look-back in range). It does NOT navigate — on 2xx it calls
`onCreated(run)` and `onClose()`; the parent (HomePage, inside the Router)
navigates. On 400 it stays open and maps `err.body.field`→that input inline
(falling back to `err.body.detail` as a non-field line), preserving values. On
any other failure it stays open, re-enables submit, and shows `err.body.detail`
or a generic non-field message. Add a test for the non-400 path too (§18).

`RunList`: newest-first rows, each with `<StatusChip variant="run">` (spinner
while blue), a Delete control (confirm → `api.deleteRun` → refetch), and a row
click that navigates to `/runs/:id`. `HomePage`: owns
`useNavigate`; `usePolling(loadRuns, anyBlue, [])` where `loadRuns` sets a
`stale` flag on error and renders the §12 "Connection problem — retrying" banner
while retaining the last list. Passes `onCreated={(r) => navigate('/runs/'+r.id)}`
to the modal.

- [ ] **Step 4: Run tests**

Run: `npx vitest run`. Expected: PASS. Router-dependent components (RunList,
HomePage) are wrapped in `<MemoryRouter>` in their tests.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: home page, run list, new-run modal"
```

### Task 19: Run-view

**Files:**
- Modify: `frontend/src/components/RunView.jsx` (created as a stub in Task 17).
- Create: `frontend/src/components/CategorySection.jsx`,
  `ContentItemRow.jsx`, and their `__tests__`.

**Interfaces:**
- Consumes: `api.getRun`, `usePolling`.
- Produces: the run-view route.

- [ ] **Step 1: Write the failing test**

```jsx
import { render, screen } from "@testing-library/react";
import { CategorySection } from "../CategorySection";

test("empty finished category shows None-found copy", () => {
  render(<CategorySection category={{ key: "podcasts", status: "yellow",
    item_count: 0, summary: null, items: [] }} />);
  expect(screen.getByText(/no content found/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `npx vitest run`. Expected: FAIL.

- [ ] **Step 3: Implement the run-view**

`RunView`: sticky header (input_text, start/end/duration,
`<StatusChip variant="run">`); in-progress banner while blue; executive-overview
block hidden while overview is null; a **category index** (jump links to each
section); a list of collapsible `CategorySection`s. Default expansion (§13):
non-empty or still-working categories expand, empty finished ones start
collapsed; user toggles are remembered for the session (e.g. `sessionStorage`
keyed by run id + category). When the run is RED with zero items across all
categories, render a single **whole-run empty state** (plus the fixed overview
message) instead of a wall of empty sections. Poll `getRun(id)` while
`run.status === 'blue'`; on poll error set a `stale` flag → show the §12
"Connection problem — retrying" banner and keep the last-known data. A Refresh
button confirms then calls `api.refreshRun`.

`CategorySection`: `<StatusChip variant="category" count={item_count}>`, the
summary, then items or a spinner while pending/running; yellow → "No content
found for this category in the selected time window."; red → the recorded
`error` plus "You can retry via Refresh." `ContentItemRow`: title (link, new
tab, `rel="noopener noreferrer"`), source, published date or an "undated"
marker, truncated snippet.

Add tests for: the red-run whole-run empty state; the category chip showing
"Found (N)" for a green category; the stale banner appearing when the poll fn
rejects.

- [ ] **Step 4: Run tests**

Run: `npx vitest run`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: run-view with categories and items"
```

---

## Phase 6 — Orchestration scripts and verification

### Task 20: `start_all.sh`

**Files:**
- Create: `start_all.sh`

**Interfaces:**
- Produces: a bash script implementing §4/§15.

- [ ] **Step 1: Write the script**

Implement, in order: prerequisite checks (Python deps importable, `docker`
present, `frontend/node_modules` present else fail with "run npm install"); a
`find_free_port` bash function (bind-check + retry); export `REDIS_PORT`,
`DJANGO_PORT`, `VITE_PORT`, `REDIS_URL`; start Redis in a run-scoped container
name (`drumbeat-redis-$$`); wait for readiness via
`docker exec <name> redis-cli ping`; `python manage.py migrate`; start Django,
the Celery worker with `-B`, and Vite, each logging to `logs/`; `tail -f` all
logs; a `trap` on SIGINT/SIGTERM/EXIT that kills children and
`docker rm -f` the container; supervise/restart the worker if it exits.
`--reset-db` behavior (make it precise, Codex impl point 24): the reset runs at
the START of `start_all.sh`, BEFORE any service is launched. To avoid killing
another live instance's Redis (Codex impl-2 point 10), it first checks for a
RUNNING match and refuses if found:

```bash
if [ -n "$(docker ps -q --filter name=drumbeat-redis-)" ]; then
  echo "Refusing --reset-db: a drumbeat Redis container is running." >&2
  exit 1
fi
docker ps -aq --filter name=drumbeat-redis- | xargs -r docker rm -f  # stopped
```

It then deletes `db.sqlite3`, `-wal`, `-shm`, and `celerybeat-schedule*`, and
proceeds with the normal startup (which migrates). Running two instances
concurrently is otherwise supported (each uses its own free ports and a
`$$`-scoped container name); only `--reset-db` is guarded because it is
destructive.

- [ ] **Step 2: Smoke-check the script parses**

Run: `bash -n start_all.sh`. Expected: no syntax errors. Then a manual run is
part of Task 22.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: start_all.sh local orchestrator"
```

### Task 21: `run_tests.sh`

**Files:**
- Create: `run_tests.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
set -uo pipefail
rc=0
echo "== backend (pytest) =="
pytest -q || rc=1
echo "== frontend (vitest) =="
if [ ! -x frontend/node_modules/.bin/vitest ]; then
  echo "frontend deps missing — run 'npm install' in frontend/" >&2
  rc=1
else
  ( cd frontend && npm run test -- --run ) || rc=1
fi
exit "$rc"
```

Fail loud if `node_modules` is absent (Codex impl point 25) rather than letting
`npx` implicitly fetch packages. `package.json` defines `"test": "vitest"`.

- [ ] **Step 2: Verify it aggregates failures**

Run: `bash run_tests.sh`. Expected: exit 0 when both suites pass; non-zero if
either fails.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: run_tests.sh single test gate"
```

### Task 22: End-to-end manual verification

**Files:** none (verification only; update `plans/INITIAL.md` §22 table).

- [ ] **Step 1: Fill `.env` with real keys; run `./start_all.sh`**

Confirm chosen ports print to the log and all four services start.

- [ ] **Step 2: Start a run against a real company (by URL and by name)**

Verify: modal closes and navigates to the run-view; categories stream in with
spinners; executive overview appears; final status is sensible; own-domain
results are absent; undated items are flagged.

- [ ] **Step 3: Exercise refresh, delete, and `--reset-db`**

Verify refresh restarts cleanly (no orphan/duplicated items), delete removes the
run, and `./start_all.sh --reset-db` empties the DB.

- [ ] **Step 4: Mark milestones DONE in `plans/INITIAL.md` §22 and commit**

```bash
git add -A && git commit -m "docs: mark implementation milestones complete"
```

---

## Self-review

Spec coverage: env/scaffold (T1-2); status completeness (T7); URL module incl.
`parse_homepage_input` (T4); exclusion incl. owned-handle match (T5); fencing +
rowcount-abort test (T8); call_llm w/ non-reserved log keys + request id +
redaction, and ALL five schema parsers (T9); tavily + §9 layer-2 window filter +
tz-aware dates (T10); Celery settings + beat + `worker_init` (T11); pipeline +
bounded curator (T12-13); IDENTITY resolution + chord + fan-in dedup/CAS + reaper
(T14, with identity/finalize/reaper tests); serializers w/ error envelope,
`MAX_INPUT_LENGTH`, nested items, all 400 paths (T15); refresh/delete +
`revoke_task_ids` (T16); frontend scaffold w/ setupTests + routing + polling
(T17); home/list/modal w/ StatusChip variants + focus trap + navigation owned by
HomePage (T18); run-view w/ category chip, red-run empty state, index, session
toggles (T19); start_all.sh (T20); run_tests.sh (T21); E2E (T22).

Codex-review items: no-txn-across-REPORT (T14 `_finalize_body`), Superseded-
Generation non-error incl. `_mark_category_red` swallow (T8, T14), output schemas
+ malformed fail-loud (T9), volume caps (T9/T10/T12), completeness status (T7),
own-channel + URL module (T4-5, T14), serializer contract (T15), Celery settings
(T11), milestone ordering (this plan).

Type consistency: `research_category` returns `{items, summary}` WITHOUT
`canonical_url` (T12); the subtask derives `canonical_url` via
`canonicalize_url_for_dedupe` at persist (T14). `call_llm` returns
`{content, tool_calls, usage}` (T9) consumed in T12-14. `is_excluded` returns
`(bool, reason)` (T5). `resolve_identity` returns `(domain|None, profiles,
handles)` (T14). Schema parsers (`parse_query_planner/report/category_summary/
curator/identity`) all live in T9. `guard_generation`/`bump_generation`/
`fenced_run_update` (T8) consumed in T14/T16.

Known intentional deferrals (in `docs/FUTURE-IMPROVEMENTS.md`): per-item
summaries, SSE, Postgres, rich pagination, stricter undated-window policy,
per-category Tavily topic tuning.
