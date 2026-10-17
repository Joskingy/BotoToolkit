# AppSync, costs, stale environments, and controlled retries

These commands reuse explicit profile/account/region arguments and STS gating.
This workspace uses profile `brewmaster`; resolve ACCOUNT_ID and resource
placeholders from private local settings. Examples are templates, not live targets.
Global arguments precede the subcommand. JSON stdout is a single report;
identity/diagnostics go to stderr. Output files must not already exist.

Reporting envelopes contain identity, report type, generated UTC time, selected
regions, schema version 1, completeness, typed allowlisted rows, observations,
and contextual errors. A complete report exits 0; incomplete reports exit 3;
auth/output/deployment refusal exits 1; invalid arguments exit 2. A native shell
wrapper can map a child command's nonzero status to its own nonzero exit status.

## AppSync key expiration

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 api-keys --warn-days 30 --format json --output api-keys.json
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 api-keys --api-id API_ID --app-id APP_ID
```

Without API IDs, discover all GraphQL APIs in explicitly selected regions.
Repeat `--api-id` and/or the global `--region` to scope multiple APIs/regions.
An app association requires explicit API IDs and is labelled `operator_supplied`;
otherwise it is `unknown`. This is not proof that an API belongs to that app.

The raw `ListApiKeys.id` is credential material. Reports use its SHA-256 digest's
first 16 hex digits as a non-operational fingerprint. Fingerprints are not
usable API keys, guaranteed globally unique IDs, or inputs to mutation commands.
No key ARN, description, credential, or raw response is exported. Keys are
classified expired (at/before now), expiring (within the inclusive warning
window), valid, or unknown. Expiry is UTC epoch seconds for modern keys. Legacy
da1 metadata and missing/invalid expiry become unknown/incomplete. Empty APIs
retain a successful summary with zero keys; read errors retain incomplete API
summaries. No key creation, extension, rotation, or deletion is implemented.

## Cost reporting

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 costs --start 2026-09-01 --end 2026-10-01 --format json --output costs.json
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 costs --start 2026-09-01 --end 2026-10-01 --tag-key App --tag-value APP_ID
```

The command checks the clock before querying. Start is inclusive; end is
exclusive and cannot be later than the current UTC date. The CLI requires the
Cost Explorer endpoint region us-east-1, but billing scope is the verified
LINKED_ACCOUNT across **all** billing regions, including shared/global services.
Metrics use monthly UnblendedCost, exclude Credit and Refund record types,
retain AWS Estimated flags, and sum with Decimal separately for each currency
and service. The requested date window remains explicit in every row. Cost
Explorer requests can incur query charges; page count/retries determine reads.

Account totals are **not per-app costs**. With both tag options, a second query
estimates tag-attributed spend; tag values are withheld from output. The
outside-tag-scope remainder combines unrelated, untagged, and shared charges.
This implementation does not directly allocate resource costs or invent a
split between those categories. Tags require appropriate cost-allocation setup,
can lag, and may not cover historical/backend spend. Zero tagged spend is not
proof of no app cost. No proportional shared-cost estimates are manufactured.
Amounts may include adjustments; separate reads are not an atomic snapshot.
Denied/incomplete account or tag reads produce null totals for that component,
not invented zeros. The report is not an invoice and does not include credits
or refunds in its metric totals.

## Stale environment evidence

Requires the installed GitHub CLI (`gh`) and its existing GitHub.com login.
For private repositories, grant Contents read and Pull requests read access.
Sign in through `gh auth login --hostname github.com`; do not pass tokens to
this toolkit or paste them into reports. The toolkit never runs auth/token
commands or requests access keys/tokens. See [GitHub troubleshooting](security.md)
for fixed diagnostic codes and credential-provider behavior.

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 stale --app-id APP_ID --repository OWNER/REPOSITORY --older-than 90 --format json --output stale.json
```

The supplied repository must match the app's GitHub URL (case-insensitive,
optional `.git` suffix). The adapter makes only `gh api --method GET` calls to
github.com, lists branches and open PRs in pages of 100, and projects only
branch/head-repository metadata. At most 20 pages per endpoint, 20 seconds per
process call, and 2 MiB projected stdout per page are accepted. A limit, denied
read, missing login, or invalid response marks GitHub evidence unknown and the
report incomplete; it never means the branch was deleted. Fork PR heads with
the same branch name do not count as PRs for this repository's branch. Raw gh
stderr, PR bodies, tokens, and credential diagnostics are not exported.

AWS activity is the latest branch creation/update or job start/end time across
complete paginated job metadata; active jobs prevent candidates. Names main/dev
and any AWS PRODUCTION stage are protected, regardless of age. An old feature/*
branch can be a **medium-confidence review candidate** only when absent from a
complete GitHub branch list and without open same-repository PRs/active jobs.
Old existing branches remain unproven; missing AWS activity evidence is unknown.
Recent settings changes count as activity. Timestamps and fixed evidence explain
the classification. The report notes backend/resource association presence but
does not discover all backend resources or establish that they are unused.
There are no cleanup/delete commands.

## Controlled deployment retries

Supported write action: `StartJob(jobType=RETRY)` for an explicitly selected
completed job. New branch-head releases, uploads, StartDeployment, resource
deletion, config updates, and key rotation are not implemented.

First produce a **read-only** plan:

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 deploy-plan --app-id APP_ID --branch dev --job-id 2 --format json --output retry-plan.json
```

Review the plan file's account, region, app, branch, source job/commit, stage,
production flag, expiry, and plan ID. It expires in 15 minutes. Its digest
detects ordinary edits; it is not a signature from an external approval system.
Preflight requires terminal source-job status, known branch metadata, and no
active jobs across branch history. Production is detected from name main,
configured PRODUCTION stage, or the app's production-branch mapping.

Only when you deliberately authorize a real retry and have the separate write
permission, use the exact reviewed plan ID (the example contains a placeholder):

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 deploy --plan retry-plan.json --confirm-plan REVIEWED_PLAN_ID
```

For a production plan, also supply `--confirm-production BRANCH_NAME`. Missing
or wrong confirmations cannot submit. Execution verifies the account, exact
region, plan digest/expiry, fresh branch stage/update time/source commit, current
production classification, and no active jobs. Drift requires a new reviewed
plan. Reads are not a transactional lock: another actor can still act after
preflight. The RETRY API identifies the existing job; a retry can use current
configuration/backend state and is not a guaranteed rollback to old resources.

The audit directory defaults to `.amplify-ops/audit` and can be set explicitly
with `--audit-dir`. Execution creates an exclusive per-plan JSONL file, writes
and fsyncs submission intent, then sends **one total SDK attempt**. Submitted
job IDs/status and known/uncertain failures are appended. If intent cannot be
persisted or the claim already exists, no write is attempted. Unknown network
outcomes consume the local plan: inspect AWS job history before any further
action. Do not delete claims to force a retry. An audit failure after submission
is reported as incomplete and may still mean AWS accepted the job.

Local claims are not distributed idempotency or tamper-proof audit storage;
changing audit directories/machines can bypass local replay detection. IAM and
human authorization remain essential. No automatic retry, polling, rollback,
or cleanup occurs. Use `investigate --job-id NEW_JOB_ID` to inspect progress.
Output-file failure after submission does not undo the job; the audit/console
receipt remains important. No live deploy was executed during implementation.

## Exact added IAM actions and separate write policy

The original six Amplify read actions remain documented in README. Added reads:

| Command | Added actions | Scope |
| --- | --- | --- |
| api-keys discovery | appsync:ListGraphqlApis | * |
| api-keys | appsync:ListApiKeys | * (no resource type listed by service authorization reference) |
| costs | ce:GetCostAndUsage | * for the default billing view used here |
| stale | none beyond GetApp, ListBranches, ListJobs | Selected Amplify resources; GitHub auth is separate |
| deploy-plan | none beyond GetApp, GetBranch, GetJob, ListJobs | Selected app/branch/job |

Example **additional read-only** policy; do not add writes to it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["appsync:ListGraphqlApis", "appsync:ListApiKeys"],
      "Resource": "*",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}
    },
    {
      "Effect": "Allow",
      "Action": "ce:GetCostAndUsage",
      "Resource": "*"
    }
  ]
}
```

Explicit `--api-id` avoids ListGraphqlApis. Billing access/Cost Explorer setup
must already exist; the tool does not enable it or change IAM. Billing-view
delegation can impose additional access requirements; no custom billing-view
selection is implemented. Profile authentication retains its own existing
requirements. API-key metadata reads are sensitive even though reports redact keys.

Example **separate opt-in write permission**, narrowly scoped to the selected
branch's jobs; it is never installed or attached by this toolkit:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "amplify:StartJob",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/APP_ID/branches/dev/jobs/*"
    }
  ]
}
```

StartJob authorization is scoped to job ARNs in the service reference. This
policy grants no StartDeployment, StopJob, delete, IAM, or configuration writes.
Use a deliberately authorized local brewmaster mapping with that permission
only when a real retry is intended. Do not expand the read policy implicitly.

## Official references checked

- [AppSync ListApiKeys](https://docs.aws.amazon.com/boto3/latest/reference/services/appsync/client/list_api_keys.html)
- [AppSync ListGraphqlApis](https://docs.aws.amazon.com/boto3/latest/reference/services/appsync/client/list_graphql_apis.html)
- [Cost Explorer GetCostAndUsage](https://docs.aws.amazon.com/boto3/latest/reference/services/ce/client/get_cost_and_usage.html)
- [Amplify StartJob](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify/client/start_job.html)
- [GitHub branch reads](https://docs.github.com/en/rest/branches/branches)
- [GitHub PR reads](https://docs.github.com/en/rest/pulls/pulls)
- [AppSync IAM](https://docs.aws.amazon.com/service-authorization/latest/reference/list_appsync.html)
- [Cost Explorer IAM](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ce.html)
- [Amplify IAM](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amplify.html)
