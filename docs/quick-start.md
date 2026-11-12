# BotoToolkit user guide

Version 0.2.0 (unreleased). Use BotoToolkit to inspect AWS resources,
deployments, alarms, recent changes, and costs. Run `bototoolkit`; the existing
`amplify-ops` command remains compatible with the same options and behavior.
The examples use PowerShell.

## 1. Check the requirements

| You need | When you need it |
| --- | --- |
| Git and access to the BotoToolkit repository | To get a checkout |
| uv and Python 3.15 or newer | To install and run BotoToolkit. uv can install the project's pinned stable Python 3.15.0. |
| A configured local AWS profile, the expected account ID, and an AWS region | To run live reports. Ask your AWS administrator for read access to the services you plan to inspect. |
| AWS CLI v2 | If your approved sign-in uses the AWS CLI, including IAM Identity Center |
| An interactive terminal | To use the optional terminal browser. Use at least 60 columns by 20 rows. |
| GitHub CLI with access to the app's source repository | To include GitHub evidence in the stale-environment report |

Use the official installation instructions for [uv](https://docs.astral.sh/uv/getting-started/installation/)
and [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

## 2. Install and check BotoToolkit

Open PowerShell and clone the BotoToolkit repository. If you already
have a checkout, open PowerShell in that folder and continue with `uv sync`.

```powershell
git clone https://github.com/Joskingy/BotoToolkit.git
Set-Location BotoToolkit
```

These checkout instructions follow the default branch. Version 0.2.0 is not
published yet; its new command alias and profile support require the release
changes. When a versioned release is available, use its reviewed tag for a
repeatable installation.

Install the locked dependencies and check the installation. uv creates the local
environment automatically; you do not need to activate it.

```powershell
uv sync --locked --no-dev
uv run --no-sync bototoolkit --help
uv run --offline --no-sync bototoolkit doctor --project .
```

You should see the command list and a setup checklist. Start with any failed
check. This diagnostic runs locally and can be used before AWS sign-in. See the
[doctor guide](doctor.md).

Run these `uv run` commands from the checkout folder. For a standalone command
that works from other folders, see [standalone installation](../CONTRIBUTING.md#distribution-for-operators).
The package is still named `amplify-ops`; do not install a similarly named
registry package as a substitute.

## 3. Configure and verify AWS access

Choose your own local AWS profile name and use your organization's approved
sign-in method. BotoToolkit accepts any explicitly selected profile; no particular
name is required. In PowerShell, enter the profile you intend to use.

```powershell
$AwsProfile = Read-Host 'Local AWS profile name'
```

If your organization uses IAM Identity Center, configure the profile if it does
not already exist, then sign in. Skip configuration for an existing profile.

```powershell
aws configure sso --profile $AwsProfile
aws sso login --profile $AwsProfile
```

Use the start URL and IAM Identity Center region supplied by your administrator,
then select the intended account and role. If you use another credential provider,
follow its sign-in process instead. Keep the same `$AwsProfile` value for the
commands below. [AWS IAM Identity Center setup](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)

Get the expected AWS account ID independently from your administrator or private
settings. Choose the region where your workload runs. Save those choices in
PowerShell variables and verify the target.

```powershell
$AccountId = Read-Host 'Expected AWS account ID'
$Region = Read-Host 'AWS region to inspect'
$AwsArgs = @('--profile', $AwsProfile,
  '--expected-account', $AccountId, '--region', $Region)

uv run --no-sync bototoolkit @AwsArgs identity
```

Check that the printed account and caller ARN match the account and role you
intend to use. If verification fails, stop and correct the profile or confirm
the expected account with your administrator. The examples below reuse
`@AwsArgs` in the same PowerShell session. In a new session, set it again.

## 4. Run your first report

Start with Amplify inventory to see apps, branches, and their latest deployments
in the selected region. Run the first line to view a table. Use the other lines
when you want to save a private JSON copy.

```powershell
uv run --no-sync bototoolkit @AwsArgs inventory

New-Item -ItemType Directory -Force reports | Out-Null
$ReportPath = 'reports/inventory-' + (Get-Date -Format yyyyMMdd-HHmmss) + '.json'
uv run --no-sync bototoolkit @AwsArgs inventory --format json --output $ReportPath
```

An empty complete report means the scan returned zero matching resources.
A partial report can still contain rows. Treat unread data as unknown. Keep
reports and audit files in private local storage.

## 5. Try the terminal browser

Install the optional terminal interface. The offline demo shows a single
synthetic Amplify view. Quit with **Ctrl+Q** and open a live session to try the
AWS view picker.

```powershell
uv sync --locked --no-dev --extra tui
uv run --offline --no-sync bototoolkit tui --demo
uv run --no-sync bototoolkit @AwsArgs tui --live
```

The live session opens on Amplify. Click the highlighted **AWS view** selector
or press **F2** to switch reports. Use **/** to search and **Up/Down** to see row
details. The live browser uses one selected region. See the
[terminal browser guide](tui.md) for alarm history, Resource Explorer setup, and
scan limits.

## 6. Choose a report for your task

### Investigate Amplify

Read the app ID and branch names from your inventory. For a deployment failure,
start with `investigate`. For differences between two branches, use
`compare` with their actual names.

```powershell
$AppId = Read-Host 'Amplify APP_ID'
$Branch = Read-Host 'Amplify branch name'
uv run --no-sync bototoolkit @AwsArgs investigate --app-id $AppId --branch $Branch
uv run --no-sync bototoolkit @AwsArgs compare --app-id $AppId --source dev --target main
```

Investigation defaults to the latest failed job. Use `--job-id JOB_ID` to
inspect a specific job or `--inspect-logs` to collect bounded error categories
and line numbers. Comparison shows configuration differences while withholding
values. [Amplify investigation reference](../README.md#failed-deployment-investigation-milestone-2)

### Inspect resources, alerts, and changes

Run the command that answers your question.

| Question | PowerShell command |
| --- | --- |
| What state are my EC2 instances in, and how healthy are they? | `uv run --no-sync bototoolkit @AwsArgs ec2 inventory` |
| Which unattached EBS volumes should owners review? | `uv run --no-sync bototoolkit @AwsArgs ebs candidates` |
| Which CloudWatch alarms are in ALARM? | `uv run --no-sync bototoolkit @AwsArgs cloudwatch alarms --state ALARM` |
| Which management changes were recorded in the past 24 hours? | `uv run --no-sync bototoolkit @AwsArgs cloudtrail changes --hours 24 --limit 100` |
| Which AppSync API keys are expiring soon? | `uv run --no-sync bototoolkit @AwsArgs api-keys --warn-days 30` |

For Resource Explorer, use an existing view in the verified account and
selected region. The list shows indexed resources. The summary counts them by
service and region.

```powershell
$ViewArn = Read-Host 'Existing Resource Explorer view ARN'
uv run --no-sync bototoolkit @AwsArgs resources list --view-arn $ViewArn
uv run --no-sync bototoolkit @AwsArgs resources summary --view-arn $ViewArn
```

See the [EC2, CloudWatch, and CloudTrail reference](../README.md#ec2-cloudwatch-and-cloudtrail)
and the [Resource Explorer and EBS reference](../README.md#resource-inventory-and-ebs-cleanup-review)
for filters, coverage, and permissions.

### Review costs and stale environments

Use `costs` to see account spending by service. Provide a start date and an
exclusive end date no later than today's UTC date. The command uses the
`us-east-1` Cost Explorer endpoint and reports across billing regions. AWS
charges for Cost Explorer API requests. [AWS Cost Explorer API pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/)

```powershell
$StartDate = Read-Host 'Start date (YYYY-MM-DD)'
$EndDate = Read-Host 'Exclusive end date (YYYY-MM-DD)'
$CostArgs = @('--profile', $AwsProfile,
  '--expected-account', $AccountId, '--region', 'us-east-1')
uv run --no-sync bototoolkit @CostArgs costs --start $StartDate --end $EndDate
```

Use `stale` to review older Amplify environments. Sign in to GitHub CLI with
access to the app's source repository for GitHub evidence. Run the earlier
Amplify step to set `$AppId`.

```powershell
$AppRepo = Read-Host 'GitHub OWNER/REPOSITORY for the Amplify app'
uv run --no-sync bototoolkit @AwsArgs stale --app-id $AppId --repository $AppRepo --older-than 90
```

See the [cost reporting](remaining-commands.md#cost-reporting) and
[stale-environment evidence](remaining-commands.md#stale-environment-evidence)
references for how to interpret the results.

## 7. Plan a deployment retry

`deploy-plan` reads AWS and produces a local plan for retrying a completed
Amplify job. Use the app and branch from step 6 and create the reports folder
before saving the plan.

```powershell
$JobId = Read-Host 'Completed numeric JOB_ID'
New-Item -ItemType Directory -Force reports | Out-Null
$PlanPath = 'reports/retry-' + (Get-Date -Format yyyyMMdd-HHmmss) + '.json'
uv run --no-sync bototoolkit @AwsArgs deploy-plan --app-id $AppId --branch $Branch --job-id $JobId --output $PlanPath
```

Review the target, source job, production flag, expiry, and plan ID.
`deploy` is the command that writes to AWS. It requires approval, separate
StartJob permission, an unexpired reviewed plan, and a local audit claim.
Follow the [controlled retry procedure](remaining-commands.md#controlled-deployment-retries)
for confirmations and handling uncertain submissions.

## 8. Get help

| What you see | What to do |
| --- | --- |
| Missing or expired credentials | Renew the session for your selected profile using its approved sign-in method and rerun `identity`. |
| Account mismatch | Confirm the intended account and check the local profile mapping. |
| Access denied or partial results | Ask your administrator to review the read permissions for that command. Start with the [Amplify IAM reference](../README.md#required-iam-read-permissions) or the service reference above. |
| Unknown option or missing argument | Run `uv run --no-sync bototoolkit COMMAND --help`, replacing `COMMAND` with the command you’re using. |

See the [release notes and limits](../README.md#020-unreleased) for supported
Python and platform validation, inventory coverage, and live scan limits.

Exit code 0 means the operation completed. Codes 1 and 2 indicate a failure or
invalid input. Code 3 indicates a partial result or an uncertain submission.
If a write may have occurred, inspect AWS job history before taking further action.

For development, security hooks, and worktrees, see [CONTRIBUTING](../CONTRIBUTING.md).
