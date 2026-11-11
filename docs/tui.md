# Terminal browser

Install the optional TUI extra and open an interactive terminal. A terminal at
least 60 columns wide and 20 rows high works best.

```powershell
uv sync --locked --extra tui
uv run --offline --no-sync amplify-ops tui --demo
```

The demo uses built-in synthetic apps, branches, and deployment statuses
without credentials or network access. Press Ctrl+R to reset the sample data.

## Live reports

Replace `ACCOUNT_ID` with your independently verified account ID and `REGION`
with the AWS region to scan. Use the local `brewmaster` profile and grant the
read permissions for the reports you use.

```powershell
uv run --no-sync amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region REGION tui --live
```

The browser starts with Amplify. Use the view picker above the search box to
load another report. Search filters the collected rows and their details locally.

- **Unattached EBS volumes** are ordered by size. Details show the owner,
  creation time, and latest completed snapshot found by the check. An
  incomplete snapshot check shows `unknown`.
- **EC2 inventory** shows instance state and health. Details include owner,
  environment, and attached volume IDs.
- **CloudWatch alarms** are ordered by state. Press Enter on an alarm to load up
  to 20 recent state updates in its details.
- **Recent CloudTrail changes** shows up to 100 management write events from
  the past 24 hours. Search by resource ID, event, or actor.
- **Resource Explorer** lists indexed resources, with a separate counts view
  by service and region. Enable both by appending `--view-arn VIEW_ARN` to the
  command. Use an existing view in the verified account and selected region.
  Coverage depends on the view and its index.

Each selection or alarm-history request verifies the account with STS, then
starts at most 100 AWS calls. This includes paginator pages and follow-up reads.
The scan stops starting new calls after 30 seconds. An in-flight call can finish
later under the SDK timeout and retry settings. The banner shows the verified
account, region, start time, and completion status. Partial results retain the
rows collected so far. The view picker is available again after the scan ends.

Use Up/Down to move through rows, `/` to search, and Esc to clear the filter.
Tab and Shift+Tab move between controls. Ctrl+Q quits and cancels further
requests. It exits with code 3 for a partial or interrupted scan and 1 for a
failed scan.
