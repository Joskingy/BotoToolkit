# amplify-ops

A Python CLI for verified AWS identity, Amplify **Hosting** inventory,
deployment investigation, redacted configuration comparison, AppSync expiration,
costs, stale-environment evidence, and explicitly reviewed deployment retries.
Milestone 1 lists apps, branches, and deployment job summaries across explicitly
selected regions. It does not discover every supporting backend resource.
Milestone 2 adds job/step investigation and optional bounded log inspection.
Milestone 3 compares dev/main (or another pair) using AWS configuration only.
Milestones 4–7 add `api-keys`, `costs`, `stale`, `deploy-plan`, and `deploy`.
All commands except **deploy** are read-only. Deploy submits an explicitly
reviewed RETRY; no live writes were performed during implementation.

The complete change report and step-by-step testing record are in
[IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md).
See [remaining command details](docs/remaining-commands.md) for AppSync, costs,
stale evidence, deployment confirmation/audit behavior, and added IAM policies.

## Setup

Install Python 3.15 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
The repository pins the 3.15 series in `.python-version`; commit `uv.lock`.

```powershell
uv sync --locked
uv run --locked amplify-ops --help
```

For contributors, cloning the repository and running these uv commands is the
recommended starting point. uv creates the local environment and installs the
project in editable mode. No manual virtual-environment activation is required.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete first-clone checklist,
security-hook setup, tests, and folder responsibilities.

For operators who only need the CLI, a versioned tool installation is a useful
future distribution path. From a trusted checkout, `uv tool install --python 3.15 .`
installs the command in a separate environment; then use `amplify-ops --help`.
This resolves dependencies from package metadata, not this checkout's uv.lock.
Use the locked checkout workflow when exact development dependency versions
matter. No public package or GitHub release is available yet; do not assume a
similarly named package on a registry is this project.

The original `src/bototoolkit` scaffold and `bototoolkit` entry point are preserved;
the project distribution and new command are named `amplify-ops`.

## Authentication and local profile mapping

This workspace uses local profile **brewmaster**. Configure/sign in to that profile
through your normal AWS CLI or IAM Identity Center workflow. Never paste credentials
into source code, CLI options, reports, issues, or chat.

Every invocation requires `--profile`, `--expected-account`, and `--region`.
ACCOUNT_ID, APP_ID, API_ID, and OWNER/REPOSITORY are placeholders. Resolve
them locally before running any command; never commit the resolved values. Use the intended account ID as an independent assertion; do not
derive it from STS merely to make the assertion pass.

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 identity
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 inventory --format table
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 inventory --format json --output inventory.json
```

To scan more than one explicitly selected region, repeat the global option
**before** the command (substitute regions you intend to scan):

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 --region us-west-2 inventory --format json
```

One Boto3 session is created with `profile_name` explicitly set. All clients
come from that session. STS `GetCallerIdentity` runs in the first selected region;
the account must match before any Amplify client is created. There is no
application fallback to default credentials or another profile. Boto3 resolves
the chosen profile's configured credential provider (for example SSO or a
profile-configured role). Configured endpoint URL overrides are ignored.

Identity and selected regions go to stderr. Inventory JSON alone goes to stdout,
so it can be piped to other tools. `identity` also prints the account and ARN on
stdout for interactive use. SDK debug/wire logging is never enabled.

### Future CI mode (not implemented)

A later explicitly selected `--auth-mode assumed-role` could use CI OIDC or a
workload identity to assume a configured role without requiring a local profile.
It must reject ambiguous profile/role combinations, keep expected-account and
region arguments mandatory, and pass through the same STS identity gate before
inventory. It must never be selected implicitly when a local profile fails.
Milestone 1 has no CI authentication mode or role-assumption command.

## Inventory semantics

- All apps, branches, and jobs use Boto3 paginators. Each region reuses one
  Amplify client. Scans are sequential; there is no account/region auto-discovery.
- Latest deployment means the job with the greatest **startTime**, across all
  pages and job types. Numeric job ID breaks equal-time ties deterministically.
  Commit time, completion time, response order, and branch `activeJobId` do not
  decide recency. Running and pending jobs are included.
- Job times are ISO 8601 in UTC. JSON includes start and optional end time;
  the table displays start time. Stage is AWS's configured stage; branch names
  such as `main`, `dev`, and `feature/*` do not override it.
- Empty app lists succeed. An app without branches has `branches: []` and
  `branches_complete: true`. A branch with no jobs has `latest_deployment: null`
  and `deployments_complete: true`.
- Regional/resource errors retain prior successful pages, allow other resources
  and regions to continue, set `complete: false`, and populate contextual errors.
  Failed branch reads leave `branches_complete: false`. Failed job reads leave
  `deployments_complete: false` and `latest_deployment: null`, even if earlier
  job pages succeeded: the actual latest job may be on an unread page.
- Credential/token failures stop further calls immediately. No report is emitted
  for an authentication failure, including one occurring during inventory.
- Standard SDK retries allow at most 3 total attempts per request, with 5-second
  connection and 20-second read timeouts. Credential-provider behavior (such as
  configured SSO/credential processes) is managed by the selected profile.
- Scans are observations over time, not atomic snapshots. Resource changes
  during pagination can cause omissions/duplicates. Full job history can take
  time and incur many read requests on long-lived branches.

### Report schema and files

JSON schema version 1 contains `identity` (account ID, caller ARN), `regions`,
`generated_at`, `scope`, `complete`, `apps`, and `errors`. Each app contains
region, app ID, name, repository URL, default domain, branches, and branch-read
completeness. Each branch contains name, configured stage, job-read completeness,
and an optional latest deployment (job ID, status, start/end times).

Only these dataclass fields are exported. Environment variables, basic auth,
build specs, commit messages, tags, signed artifact/source URLs, and raw SDK
responses are excluded. Repository URLs have userinfo, query strings, and
fragments removed. Unrecognized URL formats are redacted. Names and repository
paths remain descriptive metadata; treat reports as account information.

`--output PATH` writes the same JSON report in either display format, including
partial scans. Parent directories must exist. Existing files are **not**
overwritten; choose a new name. Generated JSON reports are gitignored. JSON
stdout remains available if the file cannot be written, but the command fails.

Exit codes: `0` complete/success; `1` identity/authentication or output-file
failure; `2` invalid/missing CLI arguments; `3` incomplete inventory/investigation/comparison.

## Redacted dev/main configuration comparison (milestone 3)

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 compare --app-id APP_ID --source dev --target main
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 compare --app-id APP_ID --source dev --target main --format json --output comparison.json
```

`--source` defaults to `dev` and `--target` to `main`. Choose any two distinct
branch names, including `feature/*` branches. One region is required for this
command. STS verification precedes a single GetApp read and two GetBranch reads
through one reused Amplify client; no inventory, GitHub, or write operations
are needed. Values remain in process memory while being compared and are never
included in stdout, stderr, or report files. No hashes, value lengths, encoded
credential strings, or raw AWS objects are exported.

The report contains three sections:

- `environment`: the union of observed app and branch environment-variable keys.
  A branch override takes precedence over its app default. Origins show `app`
  (inherited), `branch`, `absent`, or `unknown`. Empty strings are present values
  and can override nonempty defaults. Equal values with different origins are
  reported as equal **and** an origin difference, since removing/changing the
  app default could affect those branches differently.
- `branch`: the allowlisted settings compared exactly as stored by AWS. No
  inheritance is inferred for build specifications or basic auth. Omitted fields
  are absent; false booleans and empty strings/lists are present. Dictionary
  comparison ignores key ordering; list ordering and string whitespace matter.
- `shared_app`: app-wide configuration shared by the selected branches. Present
  fields are marked `shared`, not evidence that the branches' effective settings
  are identical. These rows expose field presence only and count no differences.

Each JSON entry has only section, key name, source/target presence state and
origin, comparison result, and `origin_differs`. Results are `equal`, `different`,
`missing_source`, `missing_target`, `absent_both`, `shared`, or `unavailable`.
The table omits `absent_both` rows for readability; JSON retains them. Dynamic
environment key names remain visible as metadata; their values are withheld.

`differences_found` counts entries with unequal/missing values or differing
origins, once per entry. `has_differences` is true if any known difference exists,
false only for a complete report without differences, and null when incomplete
without known differences. Read failures preserve other evidence and exit `3`.
Unread configuration is **unknown**, not absent: an unread branch may override a
known app default, and unknown app defaults may supply keys absent from a read
branch. Keys occurring only in unread resources cannot be listed. Authentication
failure stops subsequent reads and emits no report. Complete comparisons exit
`0` even with differences; differences do not imply incorrect configuration.

### Comparison field allowlist and limits

Branch fields: `stage`, `framework`, `enableAutoBuild`, `enableNotification`,
`enableBasicAuth`, `basicAuthCredentials`, `enablePerformanceMode`,
`enableSkewProtection`, `ttl`, `buildSpec`, `customDomains`,
`enablePullRequestPreview`, `pullRequestEnvironmentName`, `backendEnvironmentArn`,
`backend`, and `computeRoleArn`.

Shared app fields: `platform`, `iamServiceRoleArn`, `computeRoleArn`, `buildSpec`,
`customRules`, `customHeaders`, `enableBranchAutoBuild`, `enableBranchAutoDeletion`,
`enableBasicAuth`, `basicAuthCredentials`, `enableAutoBranchCreation`,
`autoBranchCreationPatterns`, `autoBranchCreationConfig`, `cacheConfig`, and
`jobConfig`. Compound settings are treated as one opaque value and not expanded.

The comparison excludes job IDs/counts, timestamps, descriptions, tags, app/branch
names as configuration values, and unlisted future AWS fields. It does not read
repository `amplify.yml`, build scripts, backend secrets, or automatically
injected runtime variables. Repository build settings can override console
settings, so this report does not establish complete build-time equivalence.
Reads are sequential observations rather than an atomic snapshot. Basic-auth
credential contents and all other settings remain redacted even when different.

## Failed deployment investigation (milestone 2)

Select one region, an app ID, and a branch. By default, `investigate` paginates
the complete branch job history and selects the latest job with status `FAILED`
by start time (numeric job ID breaks ties). Cancelled jobs are not treated as
failed. A failed history page prevents selection and produces a partial report;
it never guesses from the successfully read pages.

```powershell
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 investigate --app-id APP_ID --branch dev
uv run amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 investigate --app-id APP_ID --branch dev --job-id 2 --inspect-logs --format json --output investigation.json
```

`--job-id` bypasses history listing and investigates that exact job, including
successful/running jobs. Branches such as `feature/preview` are supported.
Repeated distinct regions are rejected before authentication for this command.
Every investigation passes through the same explicit-profile STS gate as inventory.

The report includes the selected job's status/start/end times, step statuses
and available timestamps, observations, and optional log findings. Missing step
timestamps are `null` in JSON and `-` in the table: the live service can omit
them on cancelled/unstarted steps despite SDK model requirements. Step names
are restricted to known phase names (otherwise `OTHER`). Free-form status
reasons/context, commit messages, artifacts, screenshots, and all URLs are
withheld. `status_reason_available` indicates only whether AWS supplied a reason.

No failed jobs is a complete, successful report with `job: null`. A successful
investigation of a failed deployment also exits `0`: this code describes the
read operation, not deployment health. Check the job's `status`. Missing/denied
job details, failed log reads, or inspection limits produce `complete: false`
and exit `3`, retaining available step evidence. Credential failures stop calls
and emit no report. Table and JSON output, stderr diagnostics, and exclusive
JSON output files follow the inventory conventions.

### Optional log inspection and output safety

Logs are fetched **only** with `--inspect-logs`, and only for failed steps.
The downloader uses the signed log URL obtained from the verified profile's
`GetJob` response. It makes HTTPS GET requests without forwarding AWS credential
headers. Supported hosts are standard AWS S3 and CloudFront endpoints; other
hosts, non-HTTPS URLs, userinfo, custom ports, fragments, redirects, and compressed
responses are rejected. Signed URLs are never exported or persisted.

A body ending before its declared Content-Length is an incomplete read and
produces a partial investigation; a successful HTTP status alone is insufficient.

Limits are fixed: at most four failed-step log attempts, 256 KiB inspected per
log (plus at most one sentinel byte downloaded to detect truncation), 20 findings
per log, 5-second socket timeouts, and a 15-second elapsed deadline checked
between response-body reads. The latter is not a hard process-level timeout
during connection/header handling. No HTTP retries, raw log files, or additional
dependencies are used. Limits or unavailable logs are visible in report errors.

The tool does not attempt to redact arbitrary log text with secret-pattern
replacement. It exports **only fixed categories, fixed suggestions, and line
numbers**. This also excludes secrets with unknown formats. Recognized clues
include dependency conflicts, missing modules/commands, TypeScript errors, Node
heap exhaustion, permission errors, build configuration errors, and command
failures. No matches means no recognized signature in the inspected bytes;
it does not establish that a build was healthy. Signatures are clues that can
have false positives, not a verified root-cause diagnosis. Raw excerpts and
source paths are deliberately absent from this milestone's output.

## Required IAM read permissions

The implemented Amplify read actions are listed below. Added AppSync/Cost
Explorer reads and the **separate** opt-in StartJob write policy are documented
in [remaining command permissions](docs/remaining-commands.md#exact-added-iam-actions-and-separate-write-policy).
No write permissions are included in this Amplify read example.

| Action | Resource scope |
| --- | --- |
| `amplify:ListApps` | `*` (listing across apps) |
| `amplify:ListBranches` | Selected app ARNs |
| `amplify:ListJobs` | Branch ARNs under selected apps |
| `amplify:GetJob` | Job ARNs under selected branches (investigation only) |
| `amplify:GetApp` | Selected app ARNs (comparison only) |
| `amplify:GetBranch` | Selected branch ARNs (comparison only) |

The following is a template read policy; resolve ACCOUNT_ID locally. It grants
these six actions only; deploying or enumerating backend resources needs
separate permissions. Expand scopes only for regions/accounts you intend to scan.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "amplify:ListApps",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "amplify:ListBranches",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/*"
    },
    {
      "Effect": "Allow",
      "Action": "amplify:ListJobs",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/*/branches/*"
    },
    {
      "Effect": "Allow",
      "Action": "amplify:GetJob",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/*/branches/*/jobs/*"
    },
    {
      "Effect": "Allow",
      "Action": "amplify:GetApp",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/*"
    },
    {
      "Effect": "Allow",
      "Action": "amplify:GetBranch",
      "Resource": "arn:aws:amplify:us-east-1:ACCOUNT_ID:apps/*/branches/*"
    }
  ]
}
```

`sts:GetCallerIdentity` is also called, but AWS documents that this operation
requires no IAM grant. The profile's credential acquisition can require its
own permissions, such as an existing role trust/assume-role setup; this tool
does not configure that setup. No `GetApp`, `GetBranch`, `GetJob`, AppSync,
CloudFormation, GitHub, or Cost Explorer permission is used by milestone 1.
Milestone 2 adds only `amplify:GetJob`. With `--job-id`, no ListJobs call is
needed; default latest-failed selection also needs `amplify:ListJobs`. Optional
log GETs use the URL's authorization, so the CLI does not request direct
`s3:GetObject` permissions. If AWS denies the URL, it reports an unavailable log
instead of requesting a broader permission set or printing the response body.
Milestone 3 adds only `amplify:GetApp` and `amplify:GetBranch`; a comparison-only
role needs these two service actions, not the List* or GetJob actions above.

## Troubleshooting

- `ProfileNotFound`: confirm `brewmaster` exists in your local AWS config or
  credentials mapping and that you run as the intended OS user.
- Expired credentials/SSO: refresh the selected profile through your normal
  sign-in workflow, then repeat `identity`. There is no automatic profile switch.
- Account mismatch: stop and confirm the profile's target account and the
  independently intended account ID before running again.
- `access_denied` or `UnauthorizedException`: identity may be valid but the
  selected resources lack read permissions. Inspect `errors` and completeness
  flags; a null deployment from a failed read is not proof of no deployments.
- `connection` or `service` errors: check network, endpoint reachability, region,
  and AWS service health. STS connectivity errors block identity verification;
  Amplify connectivity errors produce incomplete scans.
- Output failure: ensure the parent directory exists and choose a new filename.
- `NotFoundException` on investigation: confirm the app, branch, region, and job
  ID. `LogHTTP403` can indicate an expired/unavailable signed log; rerun to obtain
  a fresh URL. `UnsupportedLogURL` means the URL is outside the permitted endpoint
  formats. Neither error includes the original URL or AWS response body.
- uv cache/temp access errors in restricted Windows sessions: point cache and
  test temp storage into a writable workspace as shown below.

## Development and verification

See [CI and GitHub setup](docs/ci.md) for the Linux/Windows checks, clean package
installation validation, pinned toolchain, and required repository settings.

```powershell
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

For a restricted Windows sandbox:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv/cache'
New-Item -ItemType Directory -Force .uv/test-temp | Out-Null
$env:TEMP = Join-Path $PWD '.uv/test-temp'
$env:TMP = $env:TEMP
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests use botocore Stubber with literal fake credentials and a guard that fails
on SDK transport calls. They need no AWS account or real credentials. They cover
identity gating, pagination, latest-job selection, empty resources, partial
reads, authentication failures, CLI streams, JSON allowlisting, and output files.
Live read checks are separate and require the explicit local profile mapping.

See [ROADMAP.md](ROADMAP.md) for completed core milestone status and explicit
limits. Optional CI authentication and broader resource/deployment actions remain
outside this implementation.

## Official references checked during implementation

- [Boto3 Amplify operations and paginators](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify.html)
- [ListJobs metadata and timestamps](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify/client/list_jobs.html)
- [GetJob steps, status reasons, and log URLs](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify/client/get_job.html)
- [GetApp configuration fields](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify/client/get_app.html)
- [GetBranch configuration fields](https://docs.aws.amazon.com/boto3/latest/reference/services/amplify/client/get_branch.html)
- [Environment-variable defaults and branch overrides](https://docs.aws.amazon.com/amplify/latest/userguide/setting-env-vars.html)
- [Console and repository build settings](https://docs.aws.amazon.com/amplify/latest/userguide/build-settings.html)
- [STS GetCallerIdentity behavior](https://docs.aws.amazon.com/boto3/latest/reference/services/sts/client/get_caller_identity.html)
- [Boto3 configuration](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html)
- [Amplify IAM actions and resource types](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amplify.html)


## Safe publishing and GitHub integration

See [the security guide](docs/security.md) for local commit/push checks, the
required GitHub scan, repository protection setup, and GitHub troubleshooting.
Keep live reports, plans, logs, identifiers, and local settings outside Git.
The [implementation report](IMPLEMENTATION_REPORT.md) retains sanitized testing
evidence; it deliberately omits account/resource identities and private results.
