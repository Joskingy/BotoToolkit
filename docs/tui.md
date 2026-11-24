# Browse

From a source checkout, install the browse extra and launch the demo in an
interactive terminal. Allow at least 60 columns by 20 rows. For the published
wheel, follow [the user guide](quick-start.md#5-try-the-terminal-browser).

```powershell
uv sync --locked --extra browse
uv run --offline --no-sync bototoolkit browse --demo
```

The demo includes sample Amplify deployments, CloudWatch alarms, and EC2
instances. Press **F2** to select a view or **Ctrl+R** to reset it.
The demo uses synthetic data and runs without credentials or network access.

## Live reports

Replace `ACCOUNT_ID` with your independently verified account ID and `REGION`
with the AWS region to scan. Replace `PROFILE_NAME` with your profile and grant the
read permissions for the reports you use.

```powershell
uv run --no-sync bototoolkit --profile PROFILE_NAME --expected-account ACCOUNT_ID --region REGION browse --live
```

The browser starts with Amplify. Press F2 or click the highlighted selector
beside **AWS view** above the search box. Use Up/Down and Enter to select a
view, or Esc to close the menu. Inventory views start a scan when selected.
Cost Explorer waits for F5. Search filters the displayed rows locally.

- **Unattached EBS volumes** are ordered by size. Details show the owner,
  creation time, and latest completed snapshot found by the check. An
  incomplete snapshot check shows `unknown`.
- **EC2 inventory** summarizes instances with impaired or passing checks,
  stopped instances, and unknown health. Impaired instances appear first,
  with the failed check and owner visible in the table. A running instance
  counts as passed when both its system and instance checks passed. Select a
  row for the full instance name
  and ID, both check results, environment, and attached volume IDs. A partial
  scan marks its totals as incomplete. Search filters rows locally and leaves
  the health counts based on the retrieved scan.
- **CloudWatch alarms** shows counts by state and the number with actions
  disabled. The counts describe the retrieved scan. Search changes only the
  number of displayed alarms. A partial scan labels the counts as incomplete.
  Alarms in ALARM appear first. Select a row to see its type, action setting,
  and last state update in UTC with its age at scan time. In live mode, press
  **Enter** on an alarm to load up to 20 recent state updates.
- **Recent CloudTrail changes** shows up to 100 management write events from
  the past 24 hours. Search by resource ID, event, or actor.
- **Resource Explorer** lists indexed resources, with a separate counts view
  by service and region. Enable both by appending `--view-arn VIEW_ARN` to the
  command. Use an existing view in the verified account and selected region.
  Coverage depends on the view and its index.
- **Cost Explorer** shows unblended costs by service for
  the last 30 completed UTC days across all billing regions of the verified
  account. Dates, currency, and AWS estimate flags are shown. Credits and
  refunds are excluded, and billing data can lag. Enable Cost Explorer and
  grant `ce:GetCostAndUsage` for live queries. Selecting the view shows a link
  to the free AWS console. Check the account in the browser, which uses its own
  AWS sign-in. Only **F5** queries the `us-east-1` endpoint and incurs API
  charges. Returning to the view shows the cached results and original scan
  time. The cache is kept in memory until you quit.
  [AWS API pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/)

Each new scan or alarm-history request verifies the account with STS. After
verification, the collector can start up to 100 service calls, or 10 for Cost
Explorer. Each page and follow-up read uses one call. SDK retries for a call
already in progress can make additional network attempts. The collector stops
starting new calls after 30 seconds. An in-flight call can finish later. The banner shows the verified
account, scope, start time, and completion status. Partial results retain the
rows collected so far. Cost Explorer withholds amounts when pagination is
incomplete. The view picker is available again after the scan ends.

Use Up/Down to move through rows, `/` to search, and Esc to clear the filter.
Tab and Shift+Tab move between controls. Ctrl+Q quits and cancels further
requests. It exits with code 3 for a partial or interrupted scan and 1 for a
failed scan.
