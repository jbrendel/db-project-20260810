# Codex code review 1

Date: 2026-08-08.

Scope reviewed:

- Backend implementation under `research/` and `drumbeat/`.
- Frontend implementation under `frontend/src/`.
- Local orchestration scripts: `start_all.sh`, `run_tests.sh`.
- Test suites and project setup files.

Review focus requested: consistency, following the plan, security, and quality.


## Summary

The implementation broadly follows the plan in the important architecture paths.
The code has generation-fenced writes, explicit supersession handling, a short
fan-in transaction after `REPORT`, post-dedup report input, conditional reaper
generation bumps, on-commit task dispatch, strict LLM schemas, and a frontend that
polls with stale-data banners.

The main problems are narrower but still important:

- the default test gate fails because `tldextract` writes to the user home cache;
- external URLs are rendered as links without scheme validation;
- a few API inputs are silently coerced instead of failing loud;
- LLM logs omit tool-call response content;
- README setup has a wrong frontend install command;
- one frontend line exceeds the 94-character convention.


## Findings

### 1. High: `tldextract` writes to the user home cache

`research/urls_util.py` configures:

```python
_extract = tldextract.TLDExtract(suffix_list_urls=())
```

This disables public-suffix network fetching, but it does not disable or redirect
the cache. With `tldextract 5.3.1`, the default cache directory is under the user
home directory. In this workspace, that path is read-only, so the default test gate
fails before many tests can run.

Observed failure:

```text
OSError: [Errno 30] Read-only file system:
/home/jbrendel/.cache/python-tldextract/... .tldextract.json.lock
```

This violates the plan's requirement that URL/domain handling be offline and
deterministic. It is also operationally fragile: a local app should not require a
writable home cache just to validate a URL.

Recommended fix:

- Configure `TLDExtract` with a cache directory under a known writable location,
  such as `/tmp/drumbeat-tldextract-cache` or a project-local ignored cache path.
- Or disable caching if supported cleanly by the library version.
- Keep `suffix_list_urls=()` so tests remain offline.
- Add a regression test or test environment assertion that URL utilities do not
  write under the user's home directory.

Affected files:

- `research/urls_util.py`
- `run_tests.sh` / test environment, if choosing to set `XDG_CACHE_HOME`


### 2. High: external URLs are rendered without scheme validation

`research/tavily.py` accepts the external search result URL directly:

```python
url = r["url"]
```

That URL then persists as `ContentItem.url` and the frontend renders it directly:

```jsx
<a href={item.url} target="_blank" rel="noopener noreferrer">
```

If Tavily or a later integration returns a `javascript:`, `data:`, `file:`, or
other non-http URL, the app can render an unsafe clickable link. React escapes
text, but it does not make arbitrary `href` schemes safe.

Recommended fix:

- Add a URL validator that accepts only `http://` and `https://` URLs with a valid
  hostname.
- Apply it in `tavily_search()` before returning items.
- Apply it again before persisting `ContentItem`, or make the persistence layer
  assert items are already validated.
- Add defense-in-depth in `ContentItemRow`: if an item URL is not safe, render the
  title as text rather than as a link.
- Add tests for `javascript:alert(1)`, `data:text/html,...`, protocol-relative
  URLs, and valid `https://` URLs.

Affected files:

- `research/tavily.py`
- `research/tasks.py`
- `frontend/src/components/ContentItemRow.jsx`


### 3. Medium: `borderline_options` values are not boolean-validated

`RunCreateSerializer.validate()` reads:

```python
borderline = attrs.get("borderline_options") or {}
selected = selected_category_keys(borderline)
```

`selected_category_keys()` then treats any truthy value as enabled:

```python
if ticked:
    keys.append(key)
```

That means API input such as `{"reddit": "false"}` enables Reddit, because the
string `"false"` is truthy. This is inconsistent with checkbox semantics and the
fail-loud API philosophy.

Recommended fix:

- Validate `borderline_options` is a dict.
- Validate every value is exactly a boolean.
- Return a 400 field error for non-boolean values.
- Keep unknown keys as 400, as already implemented.

Affected files:

- `research/serializers.py`
- `research/categories.py`
- `research/tests/test_api.py`


### 4. Medium: run-list pagination silently falls back on invalid input

`RunListCreateView.get()` currently does this:

```python
try:
    limit = min(int(request.query_params.get("limit", default)), 200)
    offset = int(request.query_params.get("offset", 0))
except ValueError:
    limit, offset = default, 0
```

Bad API input should return a meaningful 400, not silently change behavior. The
current code also does not clearly reject negative `limit` or `offset` values.

Recommended fix:

- Parse `limit` and `offset` explicitly.
- Reject non-integers with a 400 envelope.
- Reject negative offsets and non-positive limits.
- Continue to cap large limits at 200 if desired, but document that behavior.

Affected files:

- `research/views.py`
- `research/tests/test_api.py`


### 5. Low/Medium: LLM logs omit tool-call response content

`call_llm()` returns both `content` and `tool_calls`:

```python
result = {
    "content": choice.content or "",
    "tool_calls": [tc.model_dump() for tc in (choice.tool_calls or [])],
    "usage": resp.usage.model_dump() if resp.usage else None,
}
```

But the log payload only writes:

```python
"response": result["content"],
```

For curator turns, tool calls are part of the model response and are needed for
debugging and auditability. The plan says full prompt and full response are logged.

Recommended fix:

- Include `tool_calls` in the LLM log JSON.
- Consider logging `response` as an object with `content` and `tool_calls`, rather
  than a string.
- Keep API key redaction by omission.

Affected files:

- `research/llm.py`
- `research/tests/test_llm.py`


### 6. Low: README frontend setup command is wrong

The README says:

```bash
# 3. Install frontend dependencies (in the frontend directory).
npm install
```

As written, a user following the code block from the repo root runs `npm install`
in the wrong directory. The actual package is under `frontend/`.

Recommended fix:

```bash
(cd frontend && npm install)
```

or:

```bash
cd frontend
npm install
cd ..
```

Affected file:

- `README.md`


### 7. Low: one line exceeds the 94-character convention

The project convention says all code and Markdown lines should be at most 94
characters. One code line currently exceeds that limit:

```text
frontend/src/components/RunView.jsx:50
```

Recommended fix:

- Wrap the stale-loading banner over multiple lines.

Affected file:

- `frontend/src/components/RunView.jsx`


## Additional Notes

### Good alignment with the plan

These areas are implemented consistently with the design:

- generation-fenced write helper and `SupersededGeneration`;
- stale task after refresh/delete is treated as normal supersession;
- category task boundary catches real errors and records red category status;
- fan-in callback computes dedup outside a transaction, calls `REPORT` outside a
  transaction, and writes terminal state in a short fenced transaction;
- report prompt is built from post-dedup kept items;
- reaper uses a conditional still-blue/stale generation bump;
- refresh/create dispatch work via `transaction.on_commit`;
- frontend polling has stale-data banners and a corrected async backoff path;
- frontend build succeeds.

### Security posture

For a local-only, unauthenticated app, the broad security posture is acceptable:

- API binds behind Django/Vite local dev servers;
- `ALLOWED_HOSTS` is limited to localhost/127.0.0.1;
- external links use `rel="noopener noreferrer"`;
- no `dangerouslySetInnerHTML` or direct HTML injection was found.

The unsafe-link issue above is the security item I would fix first.

### Artifacts

The working tree is clean according to `git status --short`. Runtime artifacts
such as `db.sqlite3`, `logs/`, `.venv/`, `node_modules/`, and Vite `dist/` are
ignored by git and are not tracked.


## Verification

Default full test gate:

```bash
./run_tests.sh
```

Result:

- backend failed: 22 failures, all caused by `tldextract` attempting to write to
  the read-only user home cache;
- frontend passed: 24 tests passed.

Backend with writable cache:

```bash
XDG_CACHE_HOME=/tmp/drumbeat-test-cache ./.venv/bin/pytest -q
```

Result:

```text
115 passed
```

Frontend production build:

```bash
npm run build
```

Result:

- Vite build passed;
- shell emitted pyenv rehash warnings, but the build completed successfully.


## Priority Fix List

I would fix in this order:

1. Make `tldextract` cache behavior deterministic and writable/offline.
2. Reject or de-link unsafe external URL schemes.
3. Validate `borderline_options` values as booleans.
4. Return 400 for malformed run-list pagination.
5. Log LLM tool-call response payloads.
6. Fix README frontend install command.
7. Wrap the one long frontend line.
