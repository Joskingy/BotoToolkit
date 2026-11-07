# amplify-ops roadmap

## Doctor review status — 7 November 2026

Core milestones 1–7 remain complete. This feature is based on synchronized dev
after PR #19. Security changes and the Dependabot removal/weekly OSV schedule
have already been promoted; earlier pending-promotion entries below are history.

Doctor and stronger test isolation are prepared for a PR into dev without merging.
The initial doctor scope excludes scanner, hook, GitHub-login, and service IAM
checks. Shared deployment coordination and broader diagnostics remain optional
follow-ups. Plain and colored CLI error assertions now cover the CI
terminal difference; the expanded offline suite passes 457 tests. Offline checks and mocked online behavior are validated separately
from hosted Linux/Windows CI and live AWS verification.

## Completed worktree cleanup — 6 November 2026

Four merged worktrees were retired after full local backup and hash verification.
The five requested main/dev/doctor/PR worktrees remain untouched. PR #16 is merged;
PR #17 is updated against the new dev and will merge after fresh required checks.
Core milestones 1–7 remain complete. Promotion to main is separate from this
cleanup; local dev/doctor updates are deferred to preserve the requested state.

## CI noise reduction prepared 6 November 2026

Removed Dependabot version-update configuration. All six required PR checks,
both test platforms, and secret scanning remain. Push-triggered verification is
limited to main; OSV monitoring runs weekly on Monday at 07:23 UTC, plus PRs,
main pushes, merge queue requests, and manual runs. Dependencies are reviewed
manually monthly or before releases. These changes await review and promotion
to main; core milestones 1–7 remain complete. Historical entries below describe
the configuration at their original implementation dates.

## Audit security remediation prepared 6 November 2026

Implemented text-only publication enforcement across working files, index, and
reachable history; case-insensitive private paths; bounded GitHub CLI capture;
and Python dependency advisory monitoring with weekly uv update PRs. Core
milestones 1–7 remain complete. See docs/project-audit.md for A1–A4 remediation
and docs/dependency-monitoring.md for activation and required-check configuration.
Original worktree edits are preserved. Review/merge and GitHub configuration remain
pending; IAM changes, doctor, cleanup, and expanded AWS writes are not included.

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

## Deep test audit — completed locally

Read-only module/caller and test-coverage audits found no safe legacy removal.
The original compatibility command remains supported. New regressions expose and
fix incomplete log bodies, missing key identity, exact cost arithmetic and invalid
amount handling, production-branch mapping, plan-file validation, and historical
private-artifact scanning. See docs/test-audit.md for evidence, checks, and limits.

## Project-local CI skill trial — installed

Installed GitHub Actions Templates under
`.agents/skills/github-actions-templates/` for use in this project. The skill is
available on a subsequent turn; no workflow was generated or enabled. Source
revision and installation verification are recorded in IMPLEMENTATION_REPORT.md.

## CI improvements — implemented locally

Application CI now checks the lockfile, lint/format, the full Linux/Windows test
matrix with a required working scanner, and clean wheel/source installation.
Both workflows use verified SHA pins and PR-only cancellation. Quarterly action
updates and user-selected ownership of CI/security controls are configured in
repository files. See docs/ci.md for exact required checks and GitHub settings
that need administrator configuration or verification. Remote enforcement and
actual hosted Linux/Windows execution remain to be verified after pushing.

## Branch and worktree adoption — planned

Reviewed the current directory, Git state, hooks, CI, and local-state behavior.
The step-by-step guide in docs/branching-and-worktrees.md covers preserving the
pending changes, creating main/dev/feature worktrees, GitHub rules, release
promotion, hotfix synchronization, and cleanup. No branch, remote, or repository
setting was changed. Adoption and hosted enforcement remain future work.

## Branch and worktree adoption — configured with protected PR promotion

The pending audit, CI, skill, and guide changes are preserved in a bootstrap
commit. The original checkout is on main; sibling dev and bootstrap worktrees
have separate Python environments and checksum-verified scanners. Dependabot
version updates are routed to dev in the bootstrap branch. Active GitHub rules
require pull requests and all six checks on main and dev, block force pushes
and deletion, and permit merge commits only. Independent approval remains
optional until another trusted reviewer is available. Promotion uses those
protected pull requests; see IMPLEMENTATION_REPORT.md and GitHub PR history.


## Developer workflow automation — implemented locally

Added dev.ps1 and scripts/dev.py with start, setup, check, pr, and promote
commands. Features start from fetched origin/dev in isolated sibling worktrees.
The helper initializes locked environments/hooks/scanners, runs local checks,
and opens explicit feature-to-dev or dev-to-main PRs. Meaningful regression
tests use disposable Git repositories and mocked GitHub calls. Review, commits,
merges, tags, and cleanup remain explicit. Merge the helper into dev before
using start for new features; see docs/developer-helper.md and the latest
verification record in IMPLEMENTATION_REPORT.md.

## Security release and branch synchronization — 6 November 2026

PR #10 promoted the security fixes and dependency monitoring into main with a
merge commit after all six required checks passed. The python-vulnerabilities
check is required on main and dev. Core milestones 1–7 remain complete.
The follow-up synchronization branch includes the promotion commit and is
prepared for a PR into dev. Pending main/doctor work and historical worktrees
remain preserved; synchronization merge approval is still outstanding.

## Doctor and follow-up test audit - implemented locally

Added offline setup diagnostics for Python, installed package metadata, explicit
local AWS profile/selection checks, and optional offline repository lockfile and
dependency validation. Online mode opts in to the existing STS account gate
only. Table and versioned JSON reports export fixed findings and suggested fixes,
without identities, paths, credentials, or raw errors. All command help now works
without AWS settings; live commands retain their explicit option gates.

The audit reproduced and fixed inherited AWS/Git configuration affecting tests,
strengthened network isolation, and retained active compatibility and security
coverage. No legacy removal was justified. See docs/doctor.md and the latest
IMPLEMENTATION_REPORT.md section for behavior, evidence, exact checks, and
remaining rollout limits.
