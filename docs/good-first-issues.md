# Good First Issues

New to Sentigent? These issues are great starting points. Each is scoped, has clear acceptance criteria, and includes file pointers to get you oriented.

---

## #GFI-1: Add `--json` output flag to `sentigent practices` CLI

**Files:** `sentigent/cli.py`, `sentigent/practices/`

**Context:** The `sentigent practices` command currently only outputs human-readable tables. Many integrations (CI/CD, dashboards, automated reports) need structured JSON output for parsing.

**Acceptance Criteria:**

- [ ] Add `--json` flag to the `practices` subcommand
- [ ] When `--json` is passed, output compact JSON (one object per line or full array)
- [ ] JSON schema includes: `name`, `enabled`, `rules` (array of rule names), `last_checked_at`, `violations_count`
- [ ] Test coverage in `tests/test_cli.py`
- [ ] Update README example showing `sentigent practices --json | jq`

**Notes:**
- Use `pydantic` models' `.model_dump_json()` for serialization
- Consider pretty-printing with `json.dumps(..., indent=2)` when a `--pretty` flag is added later
- This unblocks CI automation

---

## #GFI-2: Add dark/light theme toggle to Console dashboard

**Files:** `sentigent/dashboard/frontend/src/`, `sentigent/dashboard/frontend/tailwind.config.ts`

**Context:** The dashboard currently ships in light mode. Users running the dashboard at night or in dark environments report eye strain. A simple dark/light toggle would improve UX.

**Acceptance Criteria:**

- [ ] Add a theme toggle button (sun/moon icon) in the navbar
- [ ] Persist theme preference to browser `localStorage` as `sentigent-theme` (value: `"light"` or `"dark"`)
- [ ] Use Tailwind's `dark:` utilities for dark mode styles
- [ ] Restore user's last theme preference on page reload
- [ ] Test in both Firefox and Chrome

**Notes:**
- Tailwind v3 has built-in dark mode support via `mode: 'class'` in `tailwind.config.ts`
- Use `prefers-color-scheme` media query as fallback if no localStorage preference exists
- No backend changes needed

---

## #GFI-3: Fix stale function name `_get_practices_store()` → `get_practices_store()`

**Files:** `sentigent/dashboard/server.py`, `sentigent/practices/store.py`

**Context:** The function `_get_practices_store()` is marked private with `_` but is imported and used in the API. This is inconsistent with Python conventions and confuses contributors.

**Acceptance Criteria:**

- [ ] Rename `_get_practices_store()` to `get_practices_store()` in `sentigent/practices/store.py`
- [ ] Update all call sites in `sentigent/dashboard/server.py`
- [ ] Update any test imports in `tests/test_practices.py`
- [ ] No behavior change; this is a naming-only refactor
- [ ] Tests still pass: `pytest tests/test_practices.py -v`

**Notes:**
- Straightforward find-replace refactor
- Good first issue to practice the PR workflow
- Improves API clarity for the next contributor

---

## #GFI-4: Add launchd/cron reconcile schedule check to `sentigent doctor`

**Files:** `sentigent/cli.py`, `sentigent/doctor.py` (or equivalent)

**Context:** The `sentigent doctor` command checks environment, dependencies, and local setup. It should also verify that the user has scheduled Sentigent's reconciliation loop (via launchd on macOS or cron on Linux) so it runs automatically.

**Acceptance Criteria:**

- [ ] Add a check for launchd agents on macOS: look for `~/Library/LaunchAgents/com.sentigent.*.plist`
- [ ] Add a check for cron jobs on Linux: grep `crontab -l | grep sentigent`
- [ ] Report status: ✓ Found, ⚠ Not found (with instructions to set up)
- [ ] Include example launchd plist and cron entries in output
- [ ] Test on both macOS and Linux (or mock the calls in tests)

**Notes:**
- This is a quality-of-life improvement for production deployments
- Users often forget to schedule reconciliation; `doctor` should catch this
- No behavior change; diagnostic only

---

## #GFI-5: Add acceptance test for enforcement API 404 path

**Files:** `tests/test_practices_api.py`, `sentigent/dashboard/server.py`

**Context:** The practices enforcement endpoint (`/api/practices/enforce`) should return 404 when a practice doesn't exist. Currently, this edge case is untested.

**Acceptance Criteria:**

- [ ] Add a test that POSTs to `/api/practices/enforce` with a non-existent practice name
- [ ] Verify the response is 404 with error message: `{"error": "Practice not found: <name>"}`
- [ ] Add similar test for `GET /api/practices/<name>` → 404
- [ ] Run `pytest tests/test_practices_api.py::test_enforce_not_found -v`
- [ ] All tests pass

**Notes:**
- Straightforward parametrized test
- Good way to learn the test suite and API structure
- Improves coverage of error cases

---

## #GFI-6: Fix bare `except` in ablation study arm evaluation

**Files:** `sentigent/eval/ablation/arms.py`

**Context:** The `run_arm_a3()` function has a bare `except:` clause that swallows all exceptions, making debugging hard. Python style best practices require catching specific exceptions.

**Acceptance Criteria:**

- [ ] Replace bare `except:` with specific exceptions (e.g., `except (ValueError, RuntimeError) as e:`)
- [ ] Add logging to the exception handler: `logger.warning(f"Arm A3 failed: {e}")`
- [ ] Preserve the original exception context (use `raise ... from e` if re-raising)
- [ ] Add a test case that triggers the exception path
- [ ] Run `ruff check sentigent/eval/` → no errors

**Notes:**
- Bare excepts hide bugs; this is a code quality improvement
- Look for context clues in the function to determine which exceptions are catchable
- Good intro to Python exception handling practices

---

## #GFI-7: Fix Escalations `formatAge()` NaN when `ended_at` is missing

**Files:** `sentigent/dashboard/frontend/src/pages/Escalations.tsx`

**Context:** The Escalations page displays escalation age using `formatAge()`. When an escalation has no `ended_at` value, the function returns `NaN`, which displays incorrectly in the UI.

**Acceptance Criteria:**

- [ ] Update `formatAge()` to handle `null` or `undefined` `ended_at`
- [ ] Display "Still escalating" or "In progress" instead of `NaN`
- [ ] Add a fallback to calculate age from current time if `ended_at` is missing
- [ ] Test in the dashboard: create an open escalation and verify the display
- [ ] Add unit test: `tests/frontend/test_formatAge.spec.tsx`

**Notes:**
- Likely a simple null-check and conditional
- Good way to learn React/TypeScript in the dashboard codebase
- Improves UX for ongoing escalations

---

## #GFI-8: Add dashboard frontend isError state handling to panels

**Files:** `sentigent/dashboard/frontend/src/components/`, `sentigent/dashboard/frontend/src/pages/`

**Context:** Most dashboard panels load data asynchronously but only show loading and success states. When API calls fail, the panel shows nothing or crashes silently. Panels need an error state UI.

**Acceptance Criteria:**

- [ ] Add `isError` state to at least 3 panels (e.g., SignalsPanel, RoutingPanel, PracticesPanel)
- [ ] Display error message to user: `"Failed to load data. <error message>"`
- [ ] Include a retry button that triggers a refetch
- [ ] Use React Query's built-in `isError` and `error` from `useQuery()`
- [ ] Test error handling: mock an API failure and verify the UI renders correctly

**Notes:**
- Straightforward React Query pattern
- Improves robustness of the dashboard
- Affects multiple files; good for learning the codebase structure
- Can be broken into subtasks per panel if needed

---

## #GFI-9: Routing reconcile `days` filter doesn't reject negative values

**Files:** `sentigent/dashboard/server.py` (`reconcile_routing` handler, `RoutingReconcileRequest.days`)

**Context:** `POST /api/routing/reconcile` computes `since = time.time() - body.days * 86400` behind a bare `if body.days:` truthy check. That check passes for any negative value, so a request like `{"days": -5}` flips `since` into the *future* and silently reconciles against zero events instead of raising or falling back to "all history". The equivalent MCP tool (`sentigent_reconcile_routes` in `sentigent/mcp_server.py`) already guards this correctly with `since = (time.time() - days * 86400) if days > 0 else 0.0` — the dashboard handler should mirror that guard instead of duplicating the bug.

**Acceptance Criteria:**

- [ ] Update the `days` handling in `reconcile_routing` (server.py) so negative or zero `days` is rejected or ignored (treated as "all history"), matching the MCP tool's `days > 0` guard
- [ ] Add a test in `tests/test_dashboard_routing_api.py` that posts `{"dry_run": true, "days": -5}` (and `0`) against the existing `fake_logs`/`store_with_two_seeds` fixtures and asserts the events are still found (same result as omitting `days`), proving the pre-fix behavior (0 events found) is gone
- [ ] `tests/test_dashboard_routing_api.py::test_reconcile_days_filter_can_exclude_all_events` still passes unchanged

**Notes:**
- Small, localized fix — one conditional in one handler
- Low impact: localhost-only API, no auth/security implication
- Good first issue for learning the Console's FastAPI routing layer and its mirrored-MCP-tool convention

---

## How to Start

1. **Pick an issue** that interests you
2. **Comment** on the issue (once filed) saying "I'd like to work on this"
3. **Read** the related files and tests to understand the code
4. **Follow** the CONTRIBUTING.md guide for setup, testing, and PR submission
5. **Ask questions** if anything is unclear—we're here to help!

## Questions?

- Read `docs/DECISIONS.md` for architectural context
- Check `docs/LOOP.md` if unsure about the judgment loop
- Join discussions or open an issue with the `question` label

---

**Last updated:** 2026-07-08
