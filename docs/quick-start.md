# BotoToolkit quick start

Version 0.1.0. PowerShell guide for the committed AWS commands and developer
helper. Optional local setup diagnostics are covered in the [doctor guide](doctor.md).
Reporting and planning read AWS; only `deploy` writes AWS.
Keep reports private even though secret values are redacted.

## 1 Prepare a checkout

Prerequisites: Git, uv 0.13.4, AWS CLI, and the locally configured `brewmaster`
profile. The helper uses Python 3.15.0; uv can install it. GitHub CLI is needed
only for GitHub evidence and pull requests. Scanner setup supports Windows/Linux x64.

Replace OWNER/REPOSITORY with the trusted toolkit repository, then run:

```powershell
git clone https://github.com/OWNER/REPOSITORY.git BotoToolkit
Set-Location BotoToolkit
.\dev.ps1 setup
uv run --locked amplify-ops --help
```

Setup installs locked dependencies, configures security hooks when no custom hooks
conflict, and scans files/history. It may download tools. If an existing checkout
lacks `dev.ps1`, it predates the helper: preserve its changes before updating it.
Do not clone over an existing folder or discard pending edits.

## 2 Verify the AWS target

Sign in using the existing profile's approved login method. Only for an already
configured IAM Identity Center profile, use `aws sso login --profile brewmaster`.
Obtain the expected account independently from your administrator or private settings.

```powershell
$AccountId = Read-Host 'Expected ACCOUNT_ID'
$Region = Read-Host 'AWS region'
$AwsArgs = @('--profile', 'brewmaster',
  '--expected-account', $AccountId, '--region', $Region)
uv run --locked amplify-ops @AwsArgs identity
```

Stop if verification fails. Do not change the expected account merely to match
the response. Every AWS command below passes the explicit profile/account/region
options through `@AwsArgs` before the command name. Variables last for this session.

## 3 Inventory and investigate

```powershell
New-Item -ItemType Directory -Force reports | Out-Null
uv run --locked amplify-ops @AwsArgs inventory
uv run --locked amplify-ops @AwsArgs inventory `
  --format json --output reports/inventory.json
$AppId = Read-Host 'APP_ID from your private inventory'
$Branch = Read-Host 'Amplify branch name'
uv run --locked amplify-ops @AwsArgs investigate `
  --app-id $AppId --branch $Branch
```

Investigation selects the latest failed job. Add `--job-id JOB_ID` to inspect a
specific numeric job. Add `--inspect-logs` only when needed: it downloads bounded
failed-step logs and outputs categories and line numbers, not log text. Findings
are clues, not a confirmed root cause. Use a new filename for each report;
existing output files are never overwritten.

## 4 Compare and review other reports

Compare two existing Amplify branches; values are withheld:

```powershell
uv run --locked amplify-ops @AwsArgs compare `
  --app-id $AppId --source dev --target main
uv run --locked amplify-ops @AwsArgs api-keys --warn-days 30
```

API keys are reported by fingerprint and expiry. Add `--api-id API_ID` to select
an API; this command does not rotate keys. Configuration differences and expiring
keys do not themselves cause a nonzero exit code.

Cost Explorer uses us-east-1 but reports the verified account across billing regions:

```powershell
$CostArgs = @('--profile', 'brewmaster',
  '--expected-account', $AccountId, '--region', 'us-east-1')
uv run --locked amplify-ops @CostArgs costs `
  --start 2026-10-01 --end 2026-11-01
```

Choose your period; start is inclusive, end exclusive and no later than today UTC.
Credits/refunds are excluded. These are account totals, not per-app allocation;
Cost Explorer reads may incur charges.

For conservative stale-environment evidence, use the app's actual source repository:

```powershell
gh auth login --hostname github.com --web
uv run --locked amplify-ops @AwsArgs stale `
  --app-id $AppId --repository OWNER/REPOSITORY --older-than 90
```

Missing GitHub access means unknown evidence. Candidates require human review;
nothing is deleted. This mapping is the app repository, which may differ from
the toolkit repository.

## 5 Plan an optional retry

Use a completed job and a unique plan filename. This step reads AWS only:

```powershell
$JobId = Read-Host 'Completed numeric JOB_ID'
$PlanPath = 'reports/retry-' + (Get-Date -Format yyyyMMdd-HHmmss) + '.json'
uv run --locked amplify-ops @AwsArgs deploy-plan `
  --app-id $AppId --branch $Branch --job-id $JobId --output $PlanPath
Get-Content -LiteralPath $PlanPath
```

Review account, region, app, branch, source job/commit, production flag, plan ID,
and expiry. The plan expires after 15 minutes. A retry can use current build/backend
configuration; it is not a rollback.

The next command WRITES AWS. Run it only with approval and separately granted
StartJob permission through the approved local profile mapping. Choose a stable
private audit folder and reuse it across worktrees; never switch folders to bypass
a consumed claim. Do not execute the same plan from multiple machines.

```powershell
$AuditDir = Read-Host 'Stable private audit folder absolute path'
$PlanId = Read-Host 'Exact plan ID after review'
uv run --locked amplify-ops @AwsArgs deploy `
  --plan $PlanPath --confirm-plan $PlanId --audit-dir $AuditDir
```

For a production target, explicitly add `--confirm-production BRANCH_NAME` using
the reviewed branch. Afterwards, inspect the returned job with `investigate
--app-id $AppId --branch $Branch --job-id JOB_ID` and the same global options.
If submission is uncertain, inspect AWS job history before any further action.
Never retry automatically, remove a claim, or regenerate a plan simply to bypass it.

## 6 Develop a feature

From a clean checkout with the helper and remote dev available:

```powershell
.\dev.ps1 start improve-help
Set-Location ..\BotoToolkit-feature-improve-help
# Edit source and tests in this new folder.
.\dev.ps1 check
git --no-pager diff
git add PATH_TO_CHANGED_FILE
git --no-pager diff --cached
git commit -m "feat: describe the change"
.\dev.ps1 pr --title "Describe the change"
```

Use the folder printed by `start` if your clone has another name. Repeat `git add`
only for intended files. `check` runs setup/security, lock, tests, lint/format,
package checks, and whitespace checks. `pr` reruns checks, pushes, and opens/reuses
a PR into dev; Git and GitHub CLI authentication must be configured.

If dev advanced, run `git fetch origin`, then `git merge origin/dev` in the feature
worktree, resolve conflicts, commit, and rerun checks. After the feature PR is
reviewed and merged into dev, run `.\dev.ps1 promote` from a clean helper checkout
to open dev-to-main review. Neither command merges. Use reviewed merge commits;
then synchronize main back into dev through a PR before the next promotion.

## 7 Interpret failures

| Exit | Meaning | Next action |
| --- | --- | --- |
| 0 | Complete operation | Review findings; complete does not mean healthy. |
| 1 | Authentication, blocked retry, or file failure | Fix the stated cause; inspect AWS first if a submission may have occurred. |
| 2 | Invalid or missing arguments | Check command help and resolved local inputs. |
| 3 | Partial report or uncertain submission | Treat unread evidence as unknown; investigate before acting. |

Use `uv run --locked amplify-ops @AwsArgs COMMAND --help` for command options.
Keep `reports/`, audit files, profile data, IDs, and raw terminal output out of Git.
Before publication run `uv run --locked python scripts/security_check.py --history`.
