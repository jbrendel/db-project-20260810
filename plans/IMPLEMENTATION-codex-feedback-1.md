# Codex feedback on `plans/IMPLEMENTATION.md`

Date: 2026-08-08.

Overall assessment: `plans/INITIAL.md` revision 6 is much stronger than the prior
version and has absorbed the main design feedback well. The implementation plan is
also close: it has good task ordering, clear module boundaries, explicit test
intent, and it builds the core primitives before Celery. I would not throw it
away.

However, I would not yet hand `plans/IMPLEMENTATION.md` to an implementer as a
mechanical task-by-task plan. Several snippets are either inconsistent with the
updated design or would fail if followed literally. A senior implementer could
work around them, but an agentic worker following the document closely would
likely produce incorrect behavior in a few important places.

The findings below are ordered by implementation risk.


## 1. Test startup/config validation is probably broken

Task 2 wires `validate_required_env()` into `AppConfig.ready()` and skips it when
`PYTEST_CURRENT_TEST` is not set. The plan text assumes pytest sets that variable
early enough for Django app startup.

That assumption is unsafe. `PYTEST_CURRENT_TEST` is normally set while an
individual test is running, not necessarily during pytest-django's initial
`django.setup()` / app registry population. If required env vars are absent, the
test process can fail during collection or setup before test fixtures or
`monkeypatch` calls get a chance to run.

Recommended fix:

- Use an explicit test-mode switch such as `DRUMBEAT_SKIP_CONFIG_CHECK=1` set by
  `pytest.ini`, or
- use `pytest-env` to define dummy required env vars for the whole test process,
  or
- make `pytest.ini` set all required env vars via a supported mechanism.

The plan should avoid relying on `PYTEST_CURRENT_TEST` for startup behavior.
Individual unit tests can still call `validate_required_env()` directly after
using `monkeypatch`.

Affected area: Task 2, especially the `ResearchConfig.ready()` snippet and the
"pytest sets `PYTEST_CURRENT_TEST`" note.


## 2. LLM config tests contradict the implementation

Task 9's config-resolution test sets every `DEFAULT_LLM_*` value to a string like
`d-TOKENS` and `d-TEMP`. The implementation then casts `max_tokens` to `int` and
`temperature` to `float`.

That means the proposed test fails for the wrong reason:

```python
int("d-TOKENS")
float("d-TEMP")
```

Recommended fix:

- Set `DEFAULT_LLM_TOKENS` to something like `"1000"`.
- Set `DEFAULT_LLM_TEMP` to something like `"0.2"`.
- Keep string sentinels for URL, API key, and model only.
- Add explicit tests that invalid numeric env vars fail loud with a clear error.

Affected area: Task 9, config resolution tests and `resolve_llm_config()`.


## 3. Curator follow-up searches ignore run settings and exclusions

Task 12 gathers initial candidates through `tavily_search()` and applies
deterministic exclusion before the curator sees them. That matches the design.

Task 13's `_curate()` then performs follow-up searches like this:

```python
pool += tavily_search(data["tool_call"]["query"], 36, 10)
```

That has three problems:

- it hard-codes `lookback_months=36`, ignoring the run's selected window;
- it hard-codes `max_results=10`, ignoring `TAVILY_RESULTS_PER_SEARCH`;
- it does not apply deterministic own-domain/denylist exclusion to follow-up
  results before adding them to the candidate pool.

This can reintroduce own-channel results, denylisted pages, or out-of-window
search behavior after the initial deterministic filter.

Recommended fix:

- Change `_curate(company, category_key, candidates)` to also accept
  `lookback_months` and `exclusion`.
- Reuse one helper for all candidate ingestion, including follow-up searches.
- Enforce `MAX_CANDIDATES_PER_CATEGORY` across initial and follow-up results.
- Deduplicate by canonical URL, not raw URL.
- Pass `TAVILY_RESULTS_PER_SEARCH` into every Tavily call.

Affected area: Tasks 12 and 13.


## 4. Celery task IDs are not actually stored

The design depends on `Run.celery_task_ids` for best-effort revocation on refresh
and delete. The implementation plan defines the field and a revocation helper, but
the orchestration snippet does not store meaningful task IDs.

In Task 14:

```python
chord(header)(finalize_run.s(run_id, gen))
```

The result is discarded. In Task 15, create calls `start_run.delay(run.id)` but
the returned task id is not stored either. In Task 16, `revoke_run_tasks()` loops
over `run.celery_task_ids`, which will usually be empty.

Correctness still rests on generation fencing, so this is not a data-corruption
bug. But it means the documented revocation behavior is mostly non-functional.

Recommended fix:

- On API create, store the parent `start_run` task id immediately.
- In `start_run`, capture the chord/finalize result id if Celery exposes it.
- Store category task ids where practical, or explicitly document that only the
  parent/chord/finalize ids are stored and category revocation is best-effort
  limited.
- If storing every header task id is awkward, update the design and implementation
  plan so `celery_task_ids` is honest about what it contains.

Affected area: Tasks 14, 15, and 16.


## 5. The reaper can mutate a just-completed run

Task 14's reaper loops over blue runs selected by a query, then calls:

```python
gen = bump_generation(run_id)
```

`bump_generation()` increments generation without checking that the run is still
blue or still stale. There is a race:

1. The reaper selects a blue/stale run.
2. The fan-in callback completes the run.
3. The reaper calls `bump_generation(run_id)` anyway.
4. A terminal run's generation is incremented after completion.

The later terminal update uses `status="blue"` and may no-op, but the generation
has already been changed. That is unnecessary and violates the intent that reaper
generation bumps terminalize still-blue stale runs.

Recommended fix:

- Replace unconditional `bump_generation(run_id)` in the reaper with a conditional
  bump:

```sql
UPDATE research_run
SET generation = generation + 1
WHERE id = ?
  AND status = 'blue'
  AND started_at < ?
RETURNING generation
```

- If no row is returned, treat it as superseded/handled and do nothing.
- Keep `bump_generation()` for refresh, but use a reaper-specific helper for the
  stale-blue conditional bump.

Affected area: Task 14 reaper implementation and Task 8 fencing helpers.


## 6. Celery's Redis fallback violates the no-fixed-port rule

Task 11 configures Celery with:

```python
broker_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0")
result_backend=os.environ.get("REDIS_URL", "redis://localhost:6379/0")
```

That violates the project rule that standard ports are never assumed. Runtime
should fail loud if `REDIS_URL` is absent. Tests can inject a dummy `REDIS_URL`,
or settings can provide a test-only value under an explicit test-mode switch.

Recommended fix:

- Add `REDIS_URL` to required runtime config for processes that need Celery.
- Or validate it specifically in Celery startup and `start_all.sh`.
- Remove the `localhost:6379` fallback from production/runtime code.
- Set `REDIS_URL` explicitly in tests.

Affected area: Task 11 and possibly Task 2's config validation.


## 7. Structured parsers are not strict enough

Task 9 intends fail-loud structured output parsing, but the sample parser accepts
some malformed output silently.

Examples:

```python
def _bounded(text, env_var, default):
    return str(text)[: int(os.environ.get(env_var, default))]

def parse_report(content):
    return _bounded(_load(content)["executive_overview"],
                    "REPORT_MAX_CHARS", "4000")
```

If the model returns `{"executive_overview": null}` or an array/object, this code
turns it into `"None"` or a Python string representation instead of raising
`MalformedLLMOutput`.

Recommended fix:

- Validate that `executive_overview` is a string.
- Validate that `summary` is a string.
- Validate `IDENTITY` fields are the documented types, including `matched: bool`,
  list fields, and confidence values.
- Validate `CURATOR.accepted` item objects include expected keys and string URL
  fields, rather than only checking that `accepted` is a list.
- Keep code-fence stripping as the only mechanical repair.

Affected area: Task 9 schema parsers.


## 8. `parse_identity()` weakens the fail-loud rule too much

The updated design defines a strict `IDENTITY` schema with required keys and a
defined no-match shape. Task 9's parser uses `.get()` for all identity fields:

```python
"official_domain": data.get("official_domain"),
"owned_profile_urls": data.get("owned_profile_urls", []),
"owned_social_handles": data.get("owned_social_handles", []),
"confidence": data.get("confidence", "low"),
"matched": bool(data.get("matched", False)),
```

Optional values are fine when the schema says they are optional. But missing
`matched`, missing profile-list keys, or malformed types should not silently
become a low-confidence no-match. That hides malformed LLM output.

Recommended fix:

- Require all documented keys to exist.
- Allow `official_domain` to be `null` only when `matched` is false.
- Require profile/handle fields to be lists, even if empty.
- Require `confidence` to be one of `high`, `medium`, or `low`.
- Raise `MalformedLLMOutput` for missing keys or bad types.

Affected area: Task 9 and Task 14 identity handling.


## 9. Own-handle exclusion is too broad

Task 5 excludes any URL whose lowercase string contains an owned handle without
the leading `@`:

```python
if handle and handle.lower().lstrip("@") in lowered:
    return True, "own_profile"
```

That can exclude third-party content merely because it mentions the company's
handle in the article path or query string. For example, a legitimate article at
`techcrunch.com/.../acmehq...` could be dropped as an own profile.

Recommended fix:

- Make owned-handle matching platform-aware.
- Parse the candidate URL host and path.
- Only match handles against known profile URL shapes, for example first path
  segment on `x.com`, `twitter.com`, `linkedin.com`, `youtube.com`,
  `github.com`, etc.
- Prefer canonical owned profile URLs over handles where possible.

Affected area: Task 5 exclusion module.


## 10. Owned-profile URL matching is too loose

Task 5 checks whether the canonical owned profile URL is a substring of the
candidate canonical URL:

```python
if urls_util.canonicalize_url_for_dedupe(owned) in canon:
    return True, "own_profile"
```

Substring matching can create false positives. It also depends on the exact
canonical form, including path/trailing slash behavior.

Recommended fix:

- Parse both URLs.
- Require same registrable domain or same host, depending on the platform.
- Require the owned profile path to match exactly or as a path-prefix segment,
  never as an arbitrary substring.
- Add tests for false-positive path prefixes, such as `/company/acme` not
  matching `/company/acme-competitor`.

Affected area: Task 5 exclusion module and URL utility tests.


## 11. URL canonicalization test expectation is questionable

Task 4 expects these to canonicalize to the same URL:

```python
https://A.com/p/?utm_source=x#frag
http://www.a.com/p
```

The implementation produces a normalized HTTPS URL with path `/p` for both, so the
test passes. That is okay as a deliberate policy, but the plan should be explicit
that HTTP and HTTPS are collapsed for de-duplication.

There is a tradeoff: collapsing schemes is good for article de-dupe, but it can be
wrong for rare sites where HTTP/HTTPS serve different content. I think collapsing
is acceptable here, but the implementation plan should name it as policy, not an
accidental artifact.

Affected area: Task 4 and `INITIAL.md` Section 19.1.


## 12. `domain_matches()` name and behavior may surprise implementers

Task 4 documents:

```python
domain_matches(candidate_url, target_domain)
```

The implementation compares the candidate registrable domain to the target. That
means it matches `news.acme.com` to `acme.com`, which is right for own-domain and
denylist checks.

However, because it compares registrable domains, it would also match unrelated
subdomains under a shared registrable domain. That is usually desired for a
company's own domain but could be too broad for some third-party platform cases.

Recommended fix:

- Keep this behavior for own-domain/denylist matching.
- Do not reuse `domain_matches()` for owned profile matching on third-party
  platforms.
- Rename or document it as `registrable_domain_matches()` if possible.

Affected area: Tasks 4 and 5.


## 13. The pipeline does not preserve accepted item details from CURATOR

The `CURATOR` schema in `INITIAL.md` says `accepted` includes full item objects:

```text
accepted: [{title,url,source,published_at|null,snippet}]
```

Task 13's `_curate()` ignores all accepted item fields except URL and returns the
matching item from the original pool:

```python
accepted_urls = [a["url"] for a in data["accepted"]]
by_url = {i["url"]: i for i in pool}
return [by_url[u] for u in accepted_urls if u in by_url]
```

That is probably the right behavior because Tavily is the source of item metadata,
but it is inconsistent with the documented schema.

Recommended fix:

- Either change the CURATOR schema in the implementation plan to
  `accepted: [{url}]`, or
- use the full accepted item objects and validate them strictly.

I would prefer `accepted: [{url}]` plus reasoned rejects/duplicates, because it
avoids letting the LLM rewrite titles, sources, dates, or snippets.

Affected area: Task 9 parser, Task 13 curator loop, and `INITIAL.md` Section 6.1
if the design should be tightened too.


## 14. Same-generation duplicate category execution is only partly handled

The design notes that `task_acks_late` and worker loss can redeliver tasks. Task
14 makes final category persistence delete and reinsert items, which helps make a
same-generation duplicate subtask idempotent.

But duplicate execution can still affect intermediate state:

- a redelivered task can set a category back to `running` after it has already
  completed green/yellow/red;
- a duplicate that later fails can mark a previously successful category red;
- two same-generation subtasks can race on delete-then-insert for the same
  category.

Generation fencing does not distinguish duplicate attempts within the same
generation.

Recommended fix options:

- Keep Celery settings simple for local use and set `task_acks_late=False`, then
  rely on the reaper for lost workers, or
- add a per-category attempt token / status compare-and-set so only the first
  running attempt can finalize or mark red, or
- document that same-generation duplicate execution is accepted and add tests
  proving the chosen behavior.

Given this is a local app, the simplest route may be to avoid late acknowledgments
unless there is a strong reason to redeliver killed tasks. The reaper already
handles stuck blue runs.

Affected area: `INITIAL.md` Section 17.1 and Task 11 / Task 14.


## 15. `task_reject_on_worker_lost=True` may fight the reaper model

Related to the previous point: `task_reject_on_worker_lost=True` redelivers lost
tasks, while the reaper is also responsible for terminalizing stuck runs. That can
produce repeated same-generation category attempts after worker loss.

This is not automatically wrong, but the plan needs a deliberate decision:

- either use redelivery and make category attempts idempotent under duplicate
  execution, or
- do not redeliver lost tasks and let the reaper own recovery.

Right now the plan says fencing prevents cross-generation clobber, but fencing
does not solve same-generation duplicates.

Affected area: Task 11 Celery settings and Task 14 category writes.


## 16. `fenced_run_update()` performs two updates where one would do

Task 8's `fenced_run_update()` opens a transaction, calls `guard_generation()`,
then performs `Run.objects.filter(id=run_id).update(**fields)`.

Because the guard already verified generation inside the same transaction, this is
probably okay on SQLite. But it is less direct than the design's
compare-and-set-style update and can accidentally update a row after fields are
changed by another same-generation writer.

Recommended fix:

- Implement `fenced_run_update()` as one `UPDATE ... WHERE id=? AND generation=?`
  with rowcount check where practical, or
- keep the guard pattern only for child-row transactions, where the first-statement
  guard is specifically needed.

Affected area: Task 8.


## 17. Reaper terminal update does not check rowcount

In `_reap_one()`, after bumping generation and updating categories, the final
`Run.objects.filter(... status="blue").update(...)` result is ignored.

Given the intended compare-and-set behavior, ignoring the rowcount loses useful
control-flow information. It should either:

- raise/return superseded when the rowcount is zero, or
- explicitly comment that a zero-row update is expected and harmless.

If the conditional generation bump from finding 5 is implemented, this becomes
less risky, but it is still worth making explicit.

Affected area: Task 14 reaper implementation.


## 18. The refresh flow needs a transaction boundary

Task 16 describes refresh as bumping generation, revoking tasks, deleting category
rows, resetting the run, recreating categories, and dispatching a new task.

The plan should explicitly state which parts happen in one DB transaction:

- bump generation;
- delete old categories/items;
- reset run fields;
- recreate pending categories.

Dispatching the new Celery task should happen after commit, ideally via
`transaction.on_commit()`, so a worker cannot start against half-refreshed state.

Recommended fix:

- Use `transaction.atomic()` for all DB mutation in refresh.
- Use `transaction.on_commit(lambda: start_run.delay(run.id))`.
- Store the new parent task id after dispatch if task-id storage is kept.

Affected area: Task 16.


## 19. API create should dispatch on commit

Task 15 creates the Run and Category rows, then immediately calls
`start_run.delay(run.id)`. If this happens inside an atomic request transaction
later, or if the implementation adds atomicity, a fast worker can read before the
categories are committed.

Recommended fix:

- Wrap run/category creation in `transaction.atomic()`.
- Dispatch `start_run.delay()` using `transaction.on_commit()`.
- If the task id must be stored, decide whether to dispatch after commit and then
  update the row, or accept that create stores only the parent id after dispatch.

Affected area: Task 15.


## 20. Started timestamp ownership is inconsistent

The API create path creates a Run with `status=blue`, but `started_at` is not set
until `start_run` completes IDENTITY and performs `fenced_run_update()`.

This means a run can be blue with no `started_at` while queued or while IDENTITY is
running. It also means the reaper query on `started_at__lt=cutoff` will not catch a
run stuck before `started_at` is written.

Recommended fix:

- Set `started_at` when the run is created, since the user-visible job begins at
  submission time; or
- add a separate queued/created timestamp and make the reaper handle blue runs with
  null `started_at`.

The PRD asks for start time of a run, and users expect that to mean submission
time, not post-IDENTITY time.

Affected area: Tasks 14 and 15.


## 21. `parse_homepage_input()` and `registrable_domain()` should reject bad URL
inputs consistently

Task 15 says `input_kind == url` but an unparseable URL/host should return a 400.
Task 4's `parse_homepage_input()` returns `https://{host}` if `urlsplit` finds a
hostname.

Edge cases to ensure are tested:

- `https://`
- `http://`
- `https://?x=1`
- `.com`
- `example..com`
- host with invalid characters
- scheme-like typo such as `htp://example.com`, which the detector may classify as
  name because it only checks `http://` and `https://`.

The implementation plan already mentions `https://` with no host, but it should
add a few malformed host cases because URL validation is a fail-loud API boundary.

Affected area: Tasks 4 and 15.


## 22. Frontend dependency installation is missing

Task 17 creates `frontend/package.json` and later runs Vitest, but there is no
explicit `npm install` step. Task 20's `start_all.sh` is supposed to fail if
`frontend/node_modules` is missing, so the implementation plan should tell the
worker when to install the frontend dependencies.

Recommended fix:

- Add a Task 17 step: run `npm install` in `frontend/`.
- Commit `package-lock.json`.
- Then run `npx vitest run`.

Affected area: Task 17 and Task 20.


## 23. The plan says commit after every task, but starts from no Git repo

Task 1 includes `git init`, which is fine if the directory is not a repo. The
global constraints say "Commit at the end of every task."

This is usable, but the plan should acknowledge two cases:

- if the repo is already initialized, do not re-run `git init`;
- if the worktree has user changes, do not overwrite or revert them.

This matters for agentic workers operating in a shared workspace.

Affected area: Global constraints and Task 1.


## 24. `start_all.sh --reset-db` wording is slightly ambiguous

Task 20 says `--reset-db` should stop services, delete the DB/sidecars/beat file,
and migrate. Since this script is the thing starting services, "stop services" can
mean either:

- refuse if services are already running, or
- clean up any prior run-scoped container/processes it owns, then reset before
  starting.

The design says reset happens only while services are stopped. The implementation
plan should make the script behavior precise, especially around an existing Redis
container from a prior crashed run.

Affected area: Task 20.


## 25. `run_tests.sh` does not ensure frontend dependencies exist

Task 21 runs:

```bash
( cd frontend && npx vitest run ) || rc=1
```

If `node_modules` is missing, `npx` may try to fetch packages or behave
interactively depending on npm version/settings. For this project, tests should
not implicitly install dependencies.

Recommended fix:

- Check `frontend/node_modules/.bin/vitest` exists and fail loud with "run npm
  install" if not.
- Or use `npm test -- --run` with a lockfile and documented install step.

Affected area: Task 21.


## 26. Some snippets are too skeletal for an agentic worker

It is fine for an implementation plan to omit full code, but some omitted helpers
are load-bearing:

- `_curator_prompt`
- `_summary_prompt`
- strict schema validation for accepted curator items
- LLM log handler settings
- DRF exception handler implementation
- focus trap implementation
- worker supervision loop in `start_all.sh`

The plan calls these out in places, but an agentic worker may still create minimal
stubs that pass narrow tests while missing the intended behavior.

Recommended fix:

- Add acceptance tests or explicit behavior bullets for each load-bearing omitted
  helper.
- In particular, add tests that prompt builders enforce prompt caps and do not
  include more than the allowed item/snippet counts.

Affected area: Tasks 9, 13, 15, 18, and 20.


## 27. `INITIAL.md` still has one Redis-container inconsistency

The updated design later requires a run-scoped Redis container name, and the
implementation plan correctly uses `drumbeat-redis-$$`. But `INITIAL.md` Section 4
still says Redis runs as a Docker container named `drumbeat-redis`.

Recommended fix:

- Update Section 4 to say the container name is run-scoped/collision-free.
- Keep Section 15 as the detailed operational rule.

Affected area: `plans/INITIAL.md`, Section 4.


## 28. The implementation plan should distinguish exact code from pseudocode

Many tasks include code blocks that look copy-pasteable. Some are intended as
sketches, and some are authoritative. That ambiguity is risky for a worker using
the plan literally.

Recommended fix:

- Label snippets as one of:
  - "copy this implementation";
  - "shape only; adjust during implementation";
  - "test skeleton; expand with required cases".
- For critical primitives such as fencing, schemas, and task orchestration, make
  snippets closer to authoritative or add stronger acceptance tests.

Affected area: entire implementation plan.


## Summary verdict

`plans/IMPLEMENTATION.md` is close, but not ready as a mechanical handoff. I would
revise it before implementation, especially these blockers:

- replace `PYTEST_CURRENT_TEST` startup skipping;
- fix LLM config tests;
- pass lookback/exclusion/caps through curator follow-up searches;
- store task ids honestly or document the limitation;
- make the reaper generation bump conditional on still-blue/stale status;
- remove Celery's fixed Redis fallback;
- make structured parsers strict;
- make owned-profile/handle matching platform-aware;
- dispatch create/refresh tasks on DB commit;
- set `started_at` at submission or make reaper handle null starts;
- add `npm install` / frontend dependency handling.

After those changes, the plan would be solid enough for task-by-task execution.
