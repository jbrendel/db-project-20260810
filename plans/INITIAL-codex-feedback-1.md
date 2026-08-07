# Codex feedback on `plans/INITIAL.md`

Date: 2026-08-07.

Overall assessment: this is a strong design. I would keep the chosen stack, the
Celery chord shape, polling rather than push, the local-first assumptions, and
especially the generation-fencing model. The plan has clearly already absorbed
several hard concurrency lessons.

The feedback below is focused on changes I would make before implementation. The
main theme is to remove ambiguity at the boundaries where the system can otherwise
drift: long-running LLM calls, stale tasks, schema-less model output, URL identity,
and local orchestration.


## 1. Do not hold a DB transaction across `REPORT`

Section 5.3 says the fan-in callback performs cross-category de-duplication, may
call `REPORT`, and then persists the executive overview and terminal status. It
also says the de-dup mutations and terminal write occur within the callback's
single generation-fenced transaction.

That should be tightened so the implementation never holds a SQLite write
transaction while waiting on an LLM call.

Suggested shape:

1. Read the current run/category/item state.
2. Compute the intended de-duplication plan in memory.
3. Build the bounded `REPORT` input in memory.
4. Call `call_llm("REPORT")` outside any DB transaction.
5. Open one short generation-fenced transaction.
6. Re-check generation/status, apply de-dup mutations, recompute status, write
   `executive_overview`, `ended_at`, and terminal status.

This preserves the important invariant that terminal status is written only after
the overview exists, while avoiding a long SQLite writer lock. Polling and other
running categories should not be blocked behind an external network call.

If the final transaction finds the generation/status is no longer current, it
should discard the report result and return normally as superseded work.


## 2. Define stale-task behavior explicitly

Generation fencing intentionally turns a zero-row guard update into an exception
so the surrounding transaction rolls back. That is correct. The plan should also
define how that exception moves through the sanctioned broad `except` boundaries.

Without a special case, a stale category subtask can do this:

1. Attempt a generation-fenced final write.
2. Raise because the run was refreshed, deleted, or reaped.
3. Get caught by the category-level broad `except`.
4. Attempt to mark the category red with the stale generation.
5. Raise again, or create noisy logs for expected supersession.

I would introduce a named internal exception, for example
`SupersededGeneration`, and make it non-error control flow at task boundaries.

Recommended rule:

- A stale generation is not a category failure.
- A stale generation must not mark the category red.
- A stale generation must not alter the run status.
- A stale generation may be logged at debug/info level, not error level.
- The same rule applies to runs deleted while tasks are still in flight.

This should be covered for category subtasks, fan-in callbacks, refresh, delete,
and reaper races.


## 3. Add explicit LLM output contracts

The call-points are well identified, but the plan does not yet define precise
output schemas. Without schemas, implementation will drift into prompt-specific
string parsing and ad hoc recovery.

I would add a section defining strict contracts for each structured call:

- `IDENTITY`: official registrable domain, optional owned social/profile URLs,
  confidence, and failure/no-match shape.
- `QUERY_PLANNER`: JSON list of query strings, bounded count, no commentary.
- `CURATOR`: accepted items, rejected items with reason codes, duplicate mapping,
  optional tool-call request shape, and final/no-more-searches signal.
- `CATEGORY_SUMMARY`: plain text or JSON `{ "summary": "..." }`, with max length.
- `REPORT`: plain text or JSON `{ "executive_overview": "..." }`, with max length.

The plan should also say what happens when model output is malformed. Since this
project's philosophy is fail-loud, malformed structured output should fail the
current call-point and degrade through the existing category/run failure path. It
should not be silently repaired except for tightly defined mechanical parsing
steps, such as stripping a surrounding Markdown code fence if the schema parser
explicitly allows that.

Where the OpenAI-compatible endpoint supports JSON schema / structured output,
the implementation should use it. Where it does not, the parser should be strict
and tested.


## 4. Cap result volume and prompt size

The curator loop has iteration and search-count bounds, which is good. There
should also be explicit caps on the amount of data admitted into each stage.

Recommended tunables:

- `QUERY_PLANNER_MAX_QUERIES`
- `TAVILY_RESULTS_PER_SEARCH`
- `MAX_CANDIDATES_PER_CATEGORY`
- `MAX_ITEMS_PER_CATEGORY`
- `MAX_SNIPPET_CHARS`
- `REPORT_MAX_ITEMS_TOTAL`
- `REPORT_MAX_ITEM_SNIPPET_CHARS`

These are not only cost controls. They also protect:

- frontend readability;
- SQLite row growth;
- log size, because full prompts and responses are logged;
- LLM context limits;
- worst-case latency for concurrent runs.

The plan should define which items survive when caps are exceeded. A simple first
version could rank by `published_at` descending, undated last, then insertion
order, while leaving richer relevance scoring as a future improvement.


## 5. Revisit run-status semantics for zero-item categories

The current status model says a run is green only when every core category
finished green. That means a run is yellow if any core category has zero items.

For this domain, that may make yellow too common. Many valid companies will not
have podcast mentions, newsletter mentions, trade coverage, or major social posts
in the selected window. In those cases, "None found" is a legitimate completed
category state rather than a partial system failure.

I would consider changing run status to:

- green: all selected categories completed without errors/timeouts, and at least
  one item exists across the run;
- yellow: at least one item exists, but at least one category errored, timed out,
  or otherwise degraded;
- red: no items exist across the run, or every category errored;
- blue: still running.

Category-level yellow can still mean "None found". The run-level status would then
communicate system completeness instead of content abundance in every category.

If the existing semantics are intentional, the UI copy should explain that
"Partial" can mean "some requested categories returned no items", not necessarily
that the job failed or degraded.


## 6. Own-channel exclusion is underspecified

The PRD excludes the company's own website, blog, LinkedIn, and similar channels.
The plan's URL-input path excludes the registrable website domain, but that will
not catch official social/profile channels on third-party domains.

Examples:

- `linkedin.com/company/...`
- `x.com/...`
- `youtube.com/...`
- `medium.com/...`
- `substack.com/...`
- `github.com/...`

I would either expand `IDENTITY` so it can return known owned profiles/handles, or
explicitly document own-social exclusion as best-effort for the initial build.

The stronger initial version would store an owned-channel exclusion set on `Run`,
for example:

- `resolved_domain`
- `owned_profile_urls`
- `owned_social_handles`

Then the exclusion module can enforce deterministic matching before the curator
LLM sees candidates. The curator can still catch borderline cases, but the primary
own-channel filter should not depend solely on the LLM.


## 7. Specify URL and domain normalization concretely

URL identity is load-bearing for own-domain exclusion and cross-category de-dupe.
The plan should name the normalization approach or dependency.

The implementation needs deterministic handling for:

- public-suffix registrable domains;
- `www.` normalization;
- case-insensitive hosts;
- default ports;
- trailing slashes;
- fragments;
- common tracking query parameters;
- HTTP vs HTTPS canonicalization policy;
- percent-encoding edge cases;
- internationalized domain names.

I would add a small URL utility module early and test it heavily. A public suffix
library such as `tldextract` is appropriate if pinned and configured so tests do
not perform network updates.

The same module should provide:

- `detect_input_kind`;
- `parse_homepage_input`;
- `registrable_domain`;
- `canonicalize_url_for_dedupe`;
- `domain_matches`.

That keeps the URL decisions consistent across API validation, own-channel
exclusion, Tavily candidate filtering, and final de-duplication.


## 8. Clarify how undated items affect status and summaries

The plan keeps Tavily results that lack publish dates and flags them as undated in
the UI. That is a reasonable product choice, but the status impact should be
explicit.

As written, an undated item appears to count like any other item. That means a
category can become green, and a run can avoid red, based only on content whose
date is not known to be inside the requested window.

I would choose one of these policies explicitly:

- undated items are included and count normally, accepting that the time-window
  guarantee is best-effort;
- undated items are included but do not make a category green by themselves;
- undated items are included only when the query/window context strongly suggests
  recency, with that rule documented and tested.

The simplest implementation is the first option, but the UI should then label the
window as "dated or undated results from searches constrained to this window"
rather than implying every item is verified within the window.


## 9. Tighten local orchestration details

The local runner requirements are mostly good, but a few details should be made
more robust.

First, README setup installs backend dependencies but does not install frontend
dependencies. Either add `npm install` to the setup instructions or require
`start_all.sh` to fail loudly with a clear message when `node_modules` is missing.

Second, Redis readiness should not assume `redis-cli` is installed on the host.
Good alternatives:

- run `redis-cli ping` inside the Redis container;
- check readiness through a short Python snippet using the installed Redis client;
- use Docker health checks and poll container health.

Third, the fixed container name `drumbeat-redis` can conflict if two checkouts or
two app instances run at the same time. Since the design already avoids fixed
ports, it should also avoid a fixed container name. A path-derived or PID-suffixed
name is safer, and the cleanup trap can remove exactly that container.


## 10. Clarify delete semantics for in-flight runs

The API includes `DELETE /api/runs/<id>/`, revoking in-flight tasks first. Since
revocation is explicitly best-effort, the plan should say how in-flight tasks
behave after the run row is gone.

Recommended behavior:

- delete is terminal from the user's perspective;
- tasks that later wake up and cannot find the run return normally as superseded;
- missing run during task startup/final write is not logged as an application
  error;
- the task must not recreate any part of the deleted run;
- deleting a run removes categories/items by cascade in one transaction.

This is closely related to the stale-generation rule, but it deserves explicit
coverage because the run row may no longer exist, so the generation comparison
cannot be performed by reading the model object.


## 11. Add call logging safety limits

The PRD asks for full prompt and response logging, and the plan correctly keeps
that in a separate rotating file. Because prompts can include search snippets and
potentially large result sets, the plan should define operational limits.

I would add:

- per-process log directory and naming convention;
- max file size and backup count;
- redaction policy for API keys and authorization headers;
- request IDs / run IDs / category keys in every LLM log record;
- behavior when logging itself fails.

The full prompt/response requirement should not allow a logging failure to corrupt
the run. Logging failures should fail loud at startup if the log path is unusable,
but a mid-run rotation/write error needs a deliberate policy.


## 12. Separate category execution from API serialization concerns

The plan already says Category rows are created up front so the UI can render
spinners. I would add a serializer contract for run detail payloads so the frontend
does not infer too much.

Useful fields:

- `item_count` per category, computed server-side;
- `total_item_count` for the run;
- `is_terminal` or a documented `status == "blue"` rule, not both;
- normalized status labels could remain frontend-owned, but status values should
  be enum-like and stable;
- `warnings` on the run, especially for IDENTITY failure or own-channel best
  effort.

The plan currently has `Run.error` but not a clear place for non-fatal warnings.
IDENTITY failure is explicitly non-fatal, so a `warnings` JSON field or related
model would be cleaner than overloading `error`.


## 13. Make Celery chord/result-backend settings explicit

The design depends on Celery chords completing reliably and uses Redis as the
result backend. I would add the important Celery settings to the plan instead of
leaving them implicit.

Examples to decide during implementation:

- `task_track_started`;
- `task_time_limit` and `task_soft_time_limit`;
- `worker_prefetch_multiplier`;
- `task_acks_late`;
- `task_reject_on_worker_lost`;
- result expiration long enough for chords to complete;
- serialization format, likely JSON;
- worker concurrency default for local SQLite.

Some of these choices materially affect duplicate execution, reaper behavior, and
SQLite write pressure.


## 14. Improve milestone ordering

The milestone list puts "Status computation + generation fencing / refresh flow"
after the Celery orchestration milestone. I would move the fencing helper and
status computation earlier.

Suggested ordering change:

1. Models and status computation.
2. URL/domain normalization and exclusion module.
3. Generation-fenced write helper with tests proving rowcount behavior.
4. Celery orchestration using the helper.
5. Refresh/delete flows using the same helper.

Generation fencing is not a finishing layer. It is the core write primitive for
task code. Building Celery first and adding fencing later risks rewriting the
task persistence path.


## 15. Additional tests I would add

The existing testing section is good. I would add these cases explicitly:

- stale category task after refresh returns normally and does not mark red;
- stale fan-in callback after refresh does not overwrite the new run;
- stale task after delete returns normally and does not recreate rows;
- reaper racing fan-in leaves exactly one terminal writer;
- generation guard helper rolls back child inserts on zero-row guard update;
- malformed LLM JSON degrades through the intended category/run path;
- planner query cap is enforced;
- Tavily result cap and retained item cap are enforced;
- URL canonicalization catches tracking params, fragments, host case, `www.`, and
  trailing slash variants;
- own-domain matching catches subdomains and does not catch suffix tricks such as
  `example.com.evil.test`;
- undated-only category behavior matches the chosen status policy;
- frontend shows stale-data banner on poll failure and refetches on visibility
  restore;
- create modal preserves input on 400 and non-400 failures;
- `start_all.sh --reset-db` removes SQLite sidecars and the beat schedule file.


## Summary

I would build from this plan. The biggest changes I would make are:

- keep external calls outside DB transactions;
- make stale generation/deleted-run behavior explicit and non-error;
- define strict LLM schemas and malformed-output handling;
- add volume/prompt caps;
- clarify whether run status measures research completeness or category abundance;
- make URL/domain/own-channel normalization deterministic;
- harden local orchestration around frontend install, Redis readiness, and
  container naming.

These are core correctness and operability points, not polish. Addressing them
before implementation will reduce rework once Celery, SQLite, and LLM variability
start interacting.
