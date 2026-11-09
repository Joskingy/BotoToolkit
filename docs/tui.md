# Offline terminal browser

The first TUI prototype lets you explore fictional Amplify apps and branches.
It uses built-in synthetic data only: no AWS calls, credentials, profile files,
GitHub calls, deployment actions, or report exports. Its dates and statuses are
fixed examples, not live monitoring. No account ID is needed.

## Start from this feature checkout

Use Python 3.15 and uv in an interactive terminal, such as Windows Terminal:
Use a terminal at least 60 columns wide and 20 rows high; 100 by 35 is more comfortable.

```powershell
uv sync --locked --extra tui
uv run --offline --no-sync amplify-ops tui --demo
```

The initial dependency installation may need internet access; the demo itself
does not. `--demo` is required. Redirected input/output is rejected with a clear
message; existing commands still provide table and JSON output for scripts.
The `tui` extra is optional for operators. Development installs include Textual
so the normal CI test command always exercises the interface.

## Try the prototype

1. Use Up/Down in the table to select an app/branch and read its details below.
2. Press `/`, type an app, branch, region or deployment status, then press Enter
   to return to the filtered table. Search is case-insensitive.
3. Search for `partial`, `empty`, and `documentation` to see unknown deployment
   data, an app with no branches, and a branch with no deployments respectively.
4. Press Esc to clear the filter. Tab/Shift+Tab move between controls; the detail
   panel scrolls when the terminal is small.
5. Press Ctrl+R to restore the fixed examples. This does not refresh from AWS.
6. Press Ctrl+Q to quit, including while typing in the search field.

The banner always identifies this as an offline demo. App identifiers use
synthetic `APP_ID_DEMO_*` labels. No real resource identifiers belong in examples.

## Scope and next gate

The interface reuses the existing App, Branch and Deployment report models.
It does not accept report files or arbitrary external data. The ordinary CLI
loads the UI dependency only when launching the demo.

Live read-only browsing is a later milestone. Before enabling it, add scan/page/
time budgets, cancellation checkpoints, worker isolation, no overlapping refresh,
and fresh identity verification with explicit profile/account/region options.
Keep partial and stale results visible. Investigation and comparison come later;
deployment execution requires a separate safety review.

## Verification

```powershell
uv run --locked pytest tests/test_tui.py
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/check_distribution.py
uv run --locked python scripts/security_check.py --history
```

Headless interface tests exercise keyboard navigation, search/no matches, reset,
partial/empty states, resizing, literal resource names and the offline boundary.
They use the existing network-blocking test fixtures and forbid AWS sessions.
No new CI workflow or required check is needed.
