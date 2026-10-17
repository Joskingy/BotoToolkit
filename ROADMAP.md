# amplify-ops roadmap

Core milestones 1–7 are implemented. Inventory/report commands and deploy-plan
are read-only; deploy is an explicit, separately permissioned RETRY write path.
See IMPLEMENTATION_REPORT.md for all changes and step-by-step verification,
including the incomplete GitHub live check and the absence of live writes.
Maintain the explicit identity gate, field allowlists, stderr/stdout separation,
and mocked verification as these features are designed incrementally.

## 2. Failed deployment investigation — implemented

`investigate --app-id ... --branch ...` selects the latest failed job by paginated
metadata; `--job-id` selects an exact job without listing. Reports show step
status/timing evidence and optional `--inspect-logs` signature findings.
Only `GetJob` was added to the SDK read surface. Output includes no raw log text,
free-form status reasons, or signed URLs. Bounded HTTPS log GETs export only
fixed categories/suggestions and line numbers. Limits and errors preserve
metadata with partial-result semantics. See README for exact limits and IAM.

Stubber regressions exercise selection, identity gating, safe output, and
unavailable reads. Mocked HTTP tests exercise URL rejection, redirects,
download limits, signature recognition, and timeouts. A live read-only run investigated
historical failed dev job 2 and found BUILD failure and TypeScript/command-failure
signatures. Later milestones were not built as part of this increment.

## 3. dev/main configuration comparison — implemented

`compare --app-id ... --source dev --target main` reads one app and two branches
after verifying identity. Environment comparisons resolve app defaults plus
branch overrides and distinguish equality, origin differences, missing values,
empty overrides, and unread configuration. Allowlisted branch settings are
compared as stored; app-wide settings are shared context, not assumed effective
settings. Raw values, hashes, lengths, and basic-auth contents are never exported.

GetApp and GetBranch are the only new SDK read operations. Table and JSON reports
use the existing file/stream/partial-result conventions. Tests cover equal,
missing, inherited, and changed values; failed reads, auth gating, and redaction.
Live dev/main comparison completed with three differences in stage, framework
presence, and backend. Repository build files/runtime secrets remain outside
scope. See README for the exact allowlist, semantics, and IAM permissions.

## 4. AppSync API-key expiration reporting — implemented

`api-keys` paginates GraphQL APIs/keys in selected regions or reads explicit
API IDs. It reports UTC expiry, expired/expiring/valid/unknown status, and opaque
SHA-256 key fingerprints. Raw key IDs are credentials and never exported.
API summaries distinguish empty key lists from unread lists. App associations
are unknown or explicitly operator-supplied; no backend discovery is fabricated.
Live read verification succeeded and identified one key in the warning window.
Legacy/malformed metadata yields partial output. No rotation is implemented.

## 5. Cost reporting — implemented

`costs` requires explicit inclusive/exclusive dates and queries the verified
linked account across billing regions. Service/currency totals use Decimal,
UnblendedCost, and AWS estimated flags; credits/refunds are excluded. Optional
operator-selected tag filters yield tag-attributed estimates and an outside-tag
remainder. Direct resource allocation is unsupported, and shared versus
unattributed/unrelated costs cannot be separated; no percentages are invented.
The SDK paginator engine handles CE's documented token because no CE paginator
ships with the installed SDK. September 2026 live account reporting succeeded.

## 6. Stale environment reports using AWS and GitHub evidence — implemented

`stale` verifies an explicit OWNER/REPO mapping against the app repository,
combines branch/job activity with paginated GitHub branches/open same-repository
PRs, and reports timestamps/evidence/confidence. main/dev and production stages
are protected. Only old feature branches absent from completely read GitHub
evidence, without active jobs/open PRs, become medium-confidence review candidates.
Backend association presence is noted; individual backend resource usage is
not assessed. GitHub failures/limits produce unknown evidence and partial reports.
AWS live reads worked; GitHub live evidence needs local gh sign-in. Mocked
GitHub happy/failure paths passed. No cleanup commands were added.

## 7. Controlled deployment commands — implemented for completed-job retries

`deploy-plan` performs read-only preflight for a selected completed job and writes
a reviewable, checksummed plan expiring after 15 minutes. `deploy` requires its
exact plan ID, matching verified account/region, production confirmation where
applicable, fresh target/commit checks, no active jobs, and a persisted exclusive
local audit claim. Only StartJob(RETRY) is supported, through a separate client
with one total attempt and a separate write policy. It does not roll back or
silently retry unknown outcomes. Local replay protection is not distributed
idempotency. Plan creation was verified live; all writes were mocked only.
New branch-head releases, uploads, deletion, and config mutation are outside
this controlled-retry scope.

## Optional extensions outside the completed core roadmap

The original request explicitly deferred CI authentication; it remains design
documentation only. Schema evolution, bounded concurrency, isolated-account
integration testing, full backend resource discovery, and additional deployment
actions are optional follow-on work, not silently enabled by these commands.

## Publishing safeguards and GitHub follow-up — implemented locally

GitHub reads now expose fixed actionable errors, explicit API/open-PR requests,
and stricter malformed/duplicate evidence handling. Public documentation uses
placeholders; tests use synthetic identities. A credential/private-metadata
workflow and local commit/push hooks scan publishable files and Git history.
See docs/security.md for setup, verified tests, and the repository settings to
enable once a remote exists. Remote enforcement is not yet configured.
