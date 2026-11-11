# Terminal browser

Install the optional TUI extra and open an interactive terminal. A terminal at
least 60 columns wide and 20 rows high works best.

```powershell
uv sync --locked --extra tui
uv run --offline --no-sync amplify-ops tui --demo
```

The demo uses built-in synthetic apps, branches, and deployment statuses
without credentials or network access. Press Ctrl+R to reset the sample data.

## Live Amplify inventory

Replace `ACCOUNT_ID` with your independently verified account ID and `REGION`
with the AWS region to scan. The local `brewmaster` profile needs read access
to list Amplify apps, branches, and jobs.

```powershell
uv run --no-sync amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region REGION tui --live
```

The browser verifies the account with STS and performs one read-only scan in the
selected region. The banner shows the verified account, region, scan start
time, and whether the inventory is complete. Reopen the browser to refresh.

The scan starts at most 100 Amplify page requests, including empty pages, and
stops starting new ones after 30 seconds. STS runs before the scan. An in-flight
request can finish after the deadline under the SDK's timeout and retry settings.
Quitting stops further pages. A partial scan retains collected rows and leaves
the latest deployment unknown where job history is incomplete. Ctrl+Q exits with
code 3 for partial inventory or 1 for a failed scan.

## Navigation

- Use Up/Down to select a row and see its details.
- Press `/` to search apps, branches, regions, or statuses. Press Enter to
  return to the table and Esc to clear the filter.
- Use Tab and Shift+Tab to change panels. Press Ctrl+Q to quit.
- Use the CLI's table or JSON output for scripts.
