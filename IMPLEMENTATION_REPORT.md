# amplify-ops implementation and testing report

Completed core roadmap milestones 1–7 on October 16, 2026 (America/Mexico_City).
Generated AWS timestamps are UTC and therefore show October 17 for later checks.
This public report omits the local workspace path and live identifiers.
Commands below are sanitized reproductions; placeholders must be resolved locally.

## Outcome and command coverage

| Milestone | Commands | Implemented behavior |
| --- | --- | --- |
| 1. Identity/inventory | identity, inventory | Explicit local profile, STS expected-account gate, selected regions, paginated apps/branches/jobs, latest deployment by start time, empty resources, table/JSON/files, partial results |
| 2. Deployment investigation | investigate | Latest failed or explicit job, step evidence, optional bounded log signatures and line numbers, no raw logs/URLs |
| 3. Configuration comparison | compare | dev/main or selected branches, environment inheritance/overrides, equal/missing/changed fields, shared app context, values fully withheld |
| 4. AppSync expiration | api-keys | Selected/discovered GraphQL APIs, key fingerprints, UTC expiry/status, unknown/operator-supplied app associations, empty/error summaries |
| 5. Costs | costs | Explicit date period, verified linked-account service/currency totals, Decimal calculations, AWS estimated flags, optional tag-attributed estimates, explicit allocation limitations |
| 6. Stale environments | stale | Explicit validated repository mapping, AWS branch/job activity, GitHub branch/open-PR evidence, protected branches, conservative candidates, unknown/partial evidence |
| 7. Controlled deployments | deploy-plan, deploy | Read-only completed-job RETRY plan, digest/expiry, explicit confirmations, fresh preflight, separate write permission/client, audit claim, single submission attempt |

All commands except deploy are read-only. **No live deployment, deletion,
credential rotation, IAM change, infrastructure change, or AWS configuration
change was performed.** StartJob was executed only against Stubber/mocked
clients. No Docker, Terraform, database, web UI, or scheduled automation was added.

## All project changes

### Project structure/tooling

- `pyproject.toml`: project distribution named amplify-ops, Python >=3.15,
  amplify-ops console entry point, Boto3/Typer/Rich runtime dependencies,
  pytest/Ruff development dependencies, src package layout, Ruff settings,
  pytest discovery, uv build packaging for both new and original namespaces.
  The description now includes controlled job retries.
- `uv.lock`: resolved/locked dependency environment. No additional runtime
  dependencies were needed for the final milestones; GitHub uses installed gh.
- `.python-version`: retains the 3.15 series.
- `.gitignore`: virtual environments, uv/test/lint caches, credentials/env/key
  artifacts, generated JSON reports, and `.amplify-ops/` local audit storage.
- Original `src/bototoolkit` scaffold, bototoolkit entry point, and
  BotoToolkit.code-workspace were preserved. Existing unrelated files were not
  removed. No commits or remote pushes were created. The repository initially
  contained untracked scaffold files; files remain available for review.

### Source modules

| File | Responsibility |
| --- | --- |
| src/amplify_ops/__init__.py | Package marker |
| src/amplify_ops/aws.py | One explicit Boto3 session; STS gate; clients, safe SDK error translation, bounded retry/timeouts, pagination; one-attempt write client |
| src/amplify_ops/models.py | Allowlisted dataclass schemas; completeness/errors; reports, expiry/cost/stale rows, plans/receipts |
| src/amplify_ops/cli.py | Nine commands, input validation, profile/account/region options, output files, diagnostic streams, exit codes, explicit deployment confirmations |
| src/amplify_ops/presentation.py | Table renderers and dataclass-only JSON serialization |
| src/amplify_ops/inventory.py | App/branch/job inventory, timestamp conversion, repository URL sanitization, deterministic latest-job selection |
| src/amplify_ops/investigation.py | Failed-job selection and safe step/log evidence |
| src/amplify_ops/logs.py | Opt-in HTTPS log download, endpoint/redirect restrictions, byte/time/count limits, fixed signatures |
| src/amplify_ops/comparison.py | In-memory value comparison, app env inheritance, branch overrides, redacted relations/origins |
| src/amplify_ops/appsync.py | Paginated GraphQL API/key expiry and safe key fingerprints |
| src/amplify_ops/costs.py | Linked-account queries, Decimal aggregation, currencies, tag estimates, partial component handling |
| src/amplify_ops/github.py | Read-only gh adapter, pagination/projection/limits, safe availability errors |
| src/amplify_ops/stale.py | Repository mapping validation and conservative stale branch evidence/classification |
| src/amplify_ops/deployments.py | Reviewed RETRY plans, validation/fresh preflight, production guard, local audit/replay protection, explicit submission |

### Tests and documentation

- `tests/conftest.py`: fake-credential SDK clients, Stubber queues, network/SDK
  transport guards, targeted GitHub subprocess guard, extra service fixtures.
- `tests/test_cli.py`: output streams, files, required options, identity failures.
- `tests/test_inventory.py`: identity gating, pagination, empties, latest jobs,
  resource/regional failures, partial results, credential stop behavior.
- `tests/test_investigation.py`: job selection, metadata/log evidence,
  sensitive-field exclusion, log endpoint/redirect/size/time limits, and live
  response shape with missing timestamps.
- `tests/test_comparison.py`: equality/drift, inherited versus overridden values,
  missing/empty/unknown state, values withheld, partial reads, CLI validation.
- `tests/test_reporting.py`: AppSync pagination/key redaction/expiry/mapping;
  CE pagination, exact decimals/currencies, tag-value redaction, unknown costs;
  identity and invalid-input gating across the final reporting commands.
- `tests/test_stale_github.py`: GitHub pagination, fork PR separation,
  availability failures, protected branches, activity/PR safeguards, unknown
  evidence, and repository mismatch.
- `tests/test_deployments.py`: read-only plans, production guards, active-job
  rejection, fresh target/commit checks, modification/expiry, confirmations,
  exact mocked StartJob, no SDK write retries, local replay/audit handling,
  unknown outcomes, and jobs appearing after plan creation.
- `AGENTS.md`: project conventions, explicit brewmaster identity requirements,
  redaction constraints, completed roadmap scope, and no live deployment tests.
- `README.md`: setup/authentication, milestones 1–3 details and IAM example,
  troubleshooting, prior verification records, links to the final commands.
- `docs/remaining-commands.md`: exact usage, data/attribution semantics, limits,
  production/audit behavior, added read actions, separate write policy, sources.
- `ROADMAP.md`: all seven core milestones marked implemented within their stated
  scope; optional extensions explicitly separated.
- `IMPLEMENTATION_REPORT.md`: this complete change/test record.

## Important design decisions and remaining limits

- Local AWS execution still requires an explicit profile. Every executed AWS
  command used brewmaster with independently supplied expected account
  ACCOUNT_ID and selected region us-east-1. Clients never silently switch
  profiles/default credentials. SDK reads use at most three total attempts,
  5-second connect and 20-second read timeouts; writes use one total attempt.
- JSON stdout contains only reports; identity and diagnostics use stderr. Raw
  SDK responses, service error messages, environment-variable values, basic-auth
  contents, log text, signed URLs, and API-key IDs are not exported.
- Latest inventory/failed-job selection scans all job pages and compares start
  times, with deterministic numeric-ID tie breaking. No undocumented order is
  assumed. Unknown reads never become empty/equal/successful conclusions.
- Report observations are over time, not atomic snapshots. Full history reads
  can take time. All backend resources are not discovered by Hosting inventory.
- AppSync fingerprints are diagnostic references, not usable API keys or
  guaranteed unique operational IDs. API/app mappings are unknown unless
  explicitly asserted; no fabricated backend association is reported.
- Cost output is account/service reporting or tag-based estimation. Direct
  resource/app allocation is unsupported; shared, untagged, and unrelated spend
  are not artificially split. No tag filter was assumed during live testing.
- GitHub live evidence is incomplete because gh needs sign-in. The complete
  GitHub path was tested with mocked pages; it was not claimed to pass live.
- Stale reporting covers Hosting branches and association presence, not every
  backend resource's usage. Protected branches never become cleanup candidates.
  Review candidates require AWS age and complete GitHub evidence; no cleanup
  action exists.
- Deployment scope is completed-job RETRY only. New releases/uploads/StartDeployment,
  automatic rollback, and configuration mutation are not implemented. Current
  configuration/backend state can affect retries; an old job is not a guaranteed
  rollback. Preflight is not a transactional lock.
- Plan digests detect edits, not external authorization/signatures. Local audit
  claims are exclusive and persisted before writes, but not distributed
  idempotency or tamper-proof storage. Unknown outcomes require AWS inspection.
- CI assumed-role authentication remains documentation only, as explicitly
  deferred by the original request. Broader backend discovery, concurrency,
  distributed audit, and new deployment types are optional follow-on scope.
- Verification used the available Python **3.15.0rc2** interpreter. The project
  requires >=3.15; stable Python 3.15+ has not been tested in this environment.

## Step-by-step testing actually performed

### 1. Inspect and verify dependencies/API behavior

Read applicable AGENTS.md, repository files/status, AWS SDK and billing skill
instructions, current official Boto3/AppSync/CE/Amplify docs, IAM references, and
GitHub REST docs. Inspected installed SDK shapes/paginator support with literal
fake credentials. Confirmed Amplify and AppSync paginators exist; the installed
CE client lacks a shipped GetCostAndUsage paginator, so its documented token is
handled by the SDK paginator engine. Checked the current clock before live CE.

Dependency setup was performed with uv; the existing locked environment was
retained. Restricted Windows cache/temp paths were selected:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv/cache'
New-Item -ItemType Directory -Force .uv/test-temp | Out-Null
$env:TEMP = Join-Path $PWD '.uv/test-temp'
$env:TMP = $env:TEMP
```

### 2. Targeted tests and corrections

```powershell
uv run --locked pytest -q tests/test_reporting.py tests/test_stale_github.py tests/test_deployments.py --tb=short
```

Result after correcting test fixture API/index assumptions: **39 passed**.
An additional active-job-after-plan regression was then added. The full-suite
network guard initially intercepted Windows platform subprocess checks; it was
narrowed to the GitHub adapter instead of globally replacing subprocess.run.
Earlier milestones also exposed and fixed real missing step timestamps in a
live GetJob response and incorrect initial client-context-manager assumptions.
These initial failures are not represented as successful runs.

### 3. Full mocked regression suite

```powershell
uv run --locked pytest -q --tb=short
```

Final executed result: **108 passed in 47.84 seconds**. All AWS responses used
Stubber or explicit mocks with literal fake credentials; SDK transport/socket
connections and unmocked GitHub adapter calls were blocked. No real StartJob
write occurred. Collected module counts were independently checked:

| Test module | Collected cases |
| --- | ---: |
| test_cli.py | 12 |
| test_comparison.py | 15 |
| test_deployments.py | 15 |
| test_inventory.py | 9 |
| test_investigation.py | 32 |
| test_reporting.py | 17 |
| test_stale_github.py | 8 |

### 4. Lint, format, lockfile, CLI and document checks

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check --offline
uv run --locked amplify-ops --help
uv run --locked amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 deploy --help
git diff --check
```

All final lint/format/lockfile checks succeeded; CLI help displayed all nine
commands. Deploy help confirmed the required plan and plan-ID confirmation
options without submitting anything. Earlier command-specific help for
investigate/compare was exercised.
The original bototoolkit entry point was run successfully in prior milestone
verification. Parsed all JSON IAM examples in README and remaining command
documentation; they were valid JSON. Parsed all four new live report files and
verified their completeness/row/error metadata. Verified generated reports and
local audit storage are gitignored. `git diff --check` found no tracked diff
whitespace issues; it does not validate untracked file contents.

### 5. Prior live verification (sanitized)

Identity, inventory, investigation, comparison, AppSync expiration, account-cost
reporting, and read-only deployment planning were verified against the explicitly
selected local profile. Live identifiers, repository names, cost data, expiry
dates, fingerprints, and report contents are intentionally not published.
GitHub evidence was incomplete because local gh sign-in was required; mocked
GitHub paths passed. Deploy execution used mocks only. Keep operational results
in ignored local reports and create a fresh plan before an intentional deployment.

## GitHub integration and publishing safeguards

See [docs/security.md](docs/security.md) for changes, controls, setup, limitations,
and the additional step-by-step verification record. No repository has been
published and no remote protection settings have been applied.

The follow-up adds fixed GitHub authentication/access/rate-limit diagnostics,
explicit API headers and open-PR filtering, strict response checks, private-doc
placeholders, synthetic fixtures, a secret/metadata scan workflow, verified local
scanner tooling, and active commit/push hooks. Final regression verification:
137 tests passed; lint, format, lockfile, actionlint, and publishable-file scans
passed. Both Git hooks ran successfully, and the actual pre-push hook rejected
a temporary synthetic leak. The security guide records the full sequence and
the distinction between local rejection, required merge checks, and GitHub
server-side push protection. No commit, upload, or AWS call occurred in this update.

## Developer onboarding and editor workspace privacy

Added *.code-workspace to .gitignore; the existing workspace file was untracked
and remains available locally. Added CONTRIBUTING.md with first-clone steps,
locked uv usage, security-hook setup, offline tests, live-read prerequisites,
folder responsibilities, Gitleaks policy explanation, and operator installation
options. README links to that guide and explains editable development versus
isolated tool installation. No source modules were moved or runtime behavior
changed. Folder restructuring remains a documented recommendation.

Verification for this update: git check-ignore confirmed the workspace is
excluded; the full suite passed (137 tests); Ruff lint/format, the offline
lockfile check, CLI help, and the publishable-file security scan passed. A
custom identifier rule initially matched an ordinary word in this report;
the sentence was rephrased and the scan rerun successfully. No AWS calls,
operator tool installation, remote clone, commit, or upload were performed.

## Deep test audit (October 17, 2026)

See [docs/test-audit.md](docs/test-audit.md) for proof of the retained legacy
interfaces, defect reproductions, changes, exact checks, and remaining limits.
The audit preserves meaningful tests and fixes incomplete log reads, unknown key
identity, precision/invalid-cost handling, production mapping, malformed plans,
and historical artifact checks. It adds missing CLI and installer coverage,
corrects an inaccurate expiry-test name, and removes no unproven legacy code.

Final audit validation: **185 passed, no skips** (137-case baseline); Ruff lint
and format, offline lockfile validation, wheel/source builds and archive
inspection, both console smoke checks, real Gitleaks/history checks, and diff
whitespace checks passed. There is no local audit blocker. Live services,
remote CI, stable Python, and real Linux execution were not exercised. No
commit, tag, push, or infrastructure change was made during this audit.

## Project-local GitHub Actions Templates skill (October 21, 2026)

Installed only `github-actions-templates` from `wshobson/agents`, pinned to
revision `0874a27b17a22e2b7c2e2bcd725768e0803cad06`, using the Codex skill
installer with an explicit project destination. The installed directory is
`.agents/skills/github-actions-templates/` and contains only `SKILL.md`.
No global skill installation, dependency, hook, or workflow was changed.

Reviewed the upstream file before installation and verified its local name and
single-file contents afterward. Installed file SHA-256:
`fc3c06ddb2423804be275defbb8a2c35f1564ba28aaeb07dcf01ec9c4cc8f023`.
Invoke with `$github-actions-templates` in a subsequent project turn. Its generic
examples must be adapted to this project's uv/Python version, existing security
controls, and authorization requirements before use.

Verification: `uv run --locked pytest -q --tb=short` passed all 185 tests in
103.59 seconds; `uv run --locked ruff check .` passed;
`uv run --locked ruff format --check .` passed (38 files already formatted).
`git diff --check` passed before and after this installation record. No AWS
calls, deployment, commit, or push was performed.

## CI improvements (October 21, 2026)

Implemented the requested CI review recommendations using the project-local
GitHub Actions Templates skill, adapted to this repository's uv/Python and
privacy requirements. Existing uncommitted audit changes were preserved.

### Changes

- Added `.github/workflows/ci.yml`: locked dependency synchronization and lock
  checking, one Ruff lint/format job, independent Linux/Windows test jobs with
  `fail-fast: false`, and a package installation job. Both test runners install
  and verify Gitleaks before pytest so an absent scanner cannot produce a green
  workflow by skipping its integration tests.
- Application CI pins stable Python 3.15.0, uv 0.13.4, checkout v7.0.1 at
  `3d3c42e5aac5ba805825da76410c181273ba90b1`, and setup-uv v10.3.0 at
  `1c37ad07a6a961277cf70c0d37d6f313000f5884`. Verified both action tags against
  their official GitHub repository commits. uv package caching uses uv.lock.
- Updated the sensitive-information workflow to the same checkout SHA and an
  explicit merge-queue event type. Both workflows run for every file change on
  push, PR, merge queue, and manual dispatch. Only superseded runs of the same
  PR/workflow are cancelled; push, manual, and queue runs remain independent.
  Existing history scanning, checksum checks, canaries, read-only permissions,
  and disabled credential persistence remain in place.
- Added `.github/dependabot.yml` for weekly GitHub Actions updates, with at most
  five open update PRs. No auto-merge is configured. Embedded Python/uv/Gitleaks
  pins and Gitleaks checksums remain deliberate maintenance tasks.
- Added `.github/CODEOWNERS`, assigning CI/security tooling and policy, the
  scanner/package tests, test fixtures, and dependency/Python metadata to the
  user-selected owner `@Joskingy`. Enforcement requires a GitHub ruleset.
- Added `scripts/check_distribution.py`: PEP 517 builds through the declared
  backend, wheel/source archive inspection for private/generated paths and both
  namespaces, hash-verified locked runtime dependency installation, and separate
  clean environments for the wheel and a wheel rebuilt from source. Isolated
  imports must resolve inside those environments; both console commands run.
- Added ten archive regressions in `tests/test_distribution.py` covering both
  archive formats, retained compatibility namespace, and refusal of private or
  escaping paths. No previous test or assertion was removed.
- Added `docs/ci.md` with exact check names, architecture, local reproduction,
  dependency maintenance, and GitHub administration/verification steps. Updated
  README.md, CONTRIBUTING.md, docs/security.md, and ROADMAP.md with the new CI
  behavior and ownership/enforcement status. No application runtime dependency,
  package version, lockfile, AWS operation, or deployment behavior changed.

### Verification steps and results

Local execution used Windows x64, checksum-verified uv 0.13.4 and stable Python
3.15.0. Tools and Python were installed under ignored `.uv/` storage. Set
UV_PROJECT_ENVIRONMENT to a separate `.uv/ci-venv`, UV_PYTHON to the installed
stable interpreter, UV_CACHE_DIR to `.uv/cache`, and TEMP/TMP to `.uv/test-temp`;
put the local uv tool first on PATH. This preserved the developer's `.venv` and
global uv command. No authentication credentials were used by the checks.

1. `uv sync --locked` and `uv run --locked python --version`: passed; existing
   21-package environment installed, interpreter reported Python 3.15.0.
2. `uv run --locked python scripts/install_security_tools.py`: passed, installing
   checksum-verified Gitleaks 8.24.3. The checkout scan exposed a technical-word
   false positive in the new package helper; wording/variable names were changed
   without weakening rules or adding exclusions. The final scan passed.
3. `uv run --locked pytest -q --tb=short`: **195 passed in 62.59 seconds, no
   skips**. This includes the ten new archive cases and all 185 earlier cases;
   AWS/GitHub calls in the suite remained mocked.
4. `uv run --locked python scripts/check_distribution.py`: passed for the wheel
   and source-derived wheel, both clean environments, namespace/path inspection,
   and both command entry points. The final run used `--force-pep517` to honor the
   declared build-backend range instead of uv's newer fast build path. An initial
   offline attempt correctly failed because hashed wheels were not cached; the
   required locked wheels were then downloaded and the check completed.
5. `uv lock --check --offline`: passed, 21 packages; uv.lock was unchanged.
6. `uv run --locked ruff check .`: passed. `uv run --locked ruff format --check .`:
   passed, 41 files already formatted.
7. Checksum-verified actionlint 1.7.12 with `-shellcheck= -pyflakes=` validated both
   workflow files: passed. Embedded shell/Python analyzers were disabled; workflow
   commands contain no embedded scripts, and Python helpers passed Ruff/tests.
8. `uv run --locked python scripts/security_check.py --history --require-history`:
   passed, including canaries, working files, and reachable history. Final
   documentation was included in the last scan. `git diff --check`: passed.

### GitHub configuration and remaining limits

No local implementation blocker remains. Git remote `origin` exists, but no
workflow was pushed or triggered and remote settings were not changed or
verified. Actual hosted Linux/Windows execution remains to be verified after
publishing. Configure/verify the five required status checks, current-branch or
merge-queue policy, owner review, stale-approval dismissal, bypass/force-push
restrictions, allowed actions/runners, Dependabot, and supported push-protection
settings described in docs/ci.md. Confirm the owner's write access. An author
cannot approve their own PR: a second trusted code owner is needed for
owner-authored changes if mandatory owner approval is enabled. Stronger scanner
separation requires an organization-enforced workflow where available.

No AWS calls, live deployments, commit, tag, push, or package publication was
performed for this request. Prior history records above describe their own
earlier verification contexts; this section records the current CI work.

## Branch and worktree adoption guide (October 21, 2026)

### Review and documentation changes

Reviewed the current directory, source/test boundaries, package metadata,
ignore rules, local branch/worktree state, remote configuration, executable
hooks, scanner paths, both CI workflows, Dependabot, CODEOWNERS, and deployment
audit storage. The current checkout remains on main with pending audit and CI
changes. Only main and the locally known origin/main ref were observed; no
remote refresh or GitHub settings audit was performed.

Added docs/branching-and-worktrees.md with a ten-step adoption guide: preserve
uncommitted work on a transition branch, bootstrap dev through review, create
sibling worktrees, initialize isolated environments/scanners, configure GitHub,
develop feature branches, validate changes, promote/tag releases, synchronize
hotfixes, and retire merged worktrees. It recommends merge commits, retaining
main as the default branch, and explicit dev targets for normal PRs. It identifies
the personal-repository versus organization choice and the sole-owner review
constraint without copying private repository or AWS identifiers into the guide.

The guide also records proposed Dependabot target-branch routing, existing CI
compatibility, relative hook configuration, and the risk of replaying deployment
plans from another checkout with a separate audit directory. Linked it from
CONTRIBUTING.md and recorded adoption as planned in ROADMAP.md. No application,
test, dependency, hook, scanner-policy, or workflow behavior was changed for this
request. Earlier pending changes were preserved.

### Verification for this request

1. Read-only inspection used git status --short, git branch --all, git worktree
   list, git remote -v, git config --get core.hooksPath, git ls-files --stage
   .githooks, and targeted file reads. One actual worktree was found; hooks are
   executable and the configured path is relative. Private report contents were
   not opened. Cross-checked Git worktree/hook behavior, GitHub merge/ruleset/
   CODEOWNERS/Dependabot behavior, and uv environment isolation against the
   official documentation linked in the guide.
2. With uv 0.13.4, Python 3.15.0, and the existing isolated .uv/ci-venv environment,
   ran uv run --locked pytest -q --tb=short: **195 passed in 106.05 seconds**, no
   skips. Cache and temporary output stayed under ignored .uv storage.
3. Ran uv run --locked ruff check .: passed. Ran uv run --locked ruff format
   --check .: passed, **42 files already formatted**.
4. Rehearsed two feature/dev/main promotion and synchronization cycles in a
   disposable synthetic repository under .uv/test-temp. Verified branch
   ancestry, shared relative hooksPath with a marker hook running in the linked
   checkout, an annotated fixture tag, and safe worktree/branch removal. Ran
   the actual current security scanner and canaries with --history
   --require-history in a linked checkout whose .git is a file: passed. The
   restricted session initially prevented Git's shell hook from starting;
   the same harmless fixture hook and rehearsal passed outside that sandbox.
   This was a local Git rehearsal, not a GitHub ruleset/PR enforcement test.
5. Ran uv run --locked python scripts/security_check.py --history
   --require-history: passed for publishable working files, reachable history,
   and scanner canaries. Ran git diff --check: passed; existing line-ending
   normalization warnings do not indicate whitespace errors.

Review also identified a strict-check interaction: syncing directly from main
to an advanced dev can fail the current-base rule. The guide therefore uses a
temporary branch from dev that merges main, then targets dev in a PR, preserving
main while satisfying that rule. Hosted enforcement still needs verification.

### Adoption still to perform

No branches, tags, commits, remotes, or worktrees in the actual project were
changed; only disposable fixture Git state was created. No GitHub or AWS write
was attempted. Committing/publishing the existing work, deciding repository
ownership, creating dev and real worktrees, configuring reviewers/rulesets,
routing Dependabot, and verifying hosted PR/release cycles remain adoption
steps. The plan does not claim those steps have already happened.

## Branch and worktree implementation (October 21, 2026)

### Preservation and local layout

Saved the original pending diff and all eleven untracked files in ignored
.uv/branching-backup before switching branches. Preserved all 29 publishable
changed/new files in commit 80d54ab on codex/branching-bootstrap, including the
project-local skill, audit fixes, regression tests, scanner hardening, CI, and
guide. Private outputs, local environments, editor files, and deployment state
were left in their original checkout. The original root remains the main
worktree; sibling BotoToolkit-dev and BotoToolkit-bootstrap directories check
out dev and codex/branching-bootstrap respectively. Each new worktree has its
own .venv and installed checksum-verified scanner. A shared download cache and
Python installation do not share editable package environments.

A follow-up commit routes Dependabot version updates to dev and updates the
contributor/branch guide to the adopted strategy. The existing origin and main
default were retained. No repository transfer, AWS request, deployment, release
tag, environment deletion, or private-report publication was performed.

### GitHub configuration and promotion

Published dev from the existing main baseline and published the bootstrap
branch. Opened the bootstrap PR with base dev. Its commits preserve the prior
work and introduce the integration strategy. Promotion proceeds through a
merge-commit PR from dev to main and a temporary synchronization branch from
dev that incorporates main. GitHub PR history records the resulting merge
commits; no direct push to the protected branches is used for these changes.

Created an active ruleset matching main and dev with no bypass actors. It
requires PRs, resolved conversations, current-base testing, and quality,
tests (ubuntu-24.04), tests (windows-latest), package, and sensitive-information
checks from the verified GitHub Actions integration. Force pushes and branch
deletion are blocked. Repository settings allow merge commits only, disable
squash/rebase merges, and leave automatic head-branch deletion off. The ruleset
was read back and confirmed active on dev. Main stays the default branch.

The current sole owner remains the CI/security CODEOWNER. Independent approval
and mandatory owner approval are deliberately off under the guide's solo
maintainer policy: add a second trusted reviewer before requiring those gates.
Secret scanning and push protection were already enabled and were preserved.
GitHub's private metadata/custom-pattern coverage still needs separate review;
the local and CI scanners remain necessary. Dependabot security updates were
reported disabled; that is separate from the configured weekly action-version
updates targeting dev. No cloud credentials or deployment environment is needed.

The GitHub connector could read repository metadata but returned integration
403 errors for branch and PR creation. Standard Git authentication successfully
published both branches. For missing connector operations, GitHub CLI used that
existing credential only in process memory, without printing, saving, or asking
for tokens. GitHub CLI's persistent login was not changed.

### Exact checks and results

1. Ran uv run --locked pytest -q --tb=short in the original checkout before
   splitting: **195 passed in 118.56 seconds**, no skips. Ruff lint and formatting
   passed; formatting reported 42 files. uv lock --check --offline passed with
   21 packages. No dependency or Python requirement was changed.
2. Ran uv run --locked python scripts/check_distribution.py: passed wheel and
   source-derived wheel builds, archive checks, clean hash-locked installations,
   isolated imports, and both entry points. The first sandboxed online attempt
   could not resolve PyPI DNS; rerunning with UV_OFFLINE=true used cached build
   dependencies and passed without changing the declared build backend.
3. In each actual linked worktree, ran uv sync --locked --offline, installed the
   scanner with scripts/install_security_tools.py, and ran security_check.py
   --history --require-history. All passed. Assertions verified sys.prefix was
   that checkout's .venv and both package imports resolved under its own src.
4. In BotoToolkit-bootstrap, ran uv run --locked pytest -q --tb=short:
   **195 passed in 79.06 seconds**, no skips. uv run --locked ruff check . and
   uv run --locked ruff format --check . passed (42 files). Package installation
   checks and uv lock --check --offline passed again in the linked checkout.
5. actionlint 1.7.12 with -shellcheck= -pyflakes= passed both workflows. Security
   scans included working files, scanner canaries, and all reachable history.
   The real pre-commit and pre-push hooks ran successfully for the commits and
   pushes. git diff --check passed; normalization warnings were informational.
6. Hosted push CI for the bootstrap code completed quality, Linux tests, Windows
   tests, package checks, and sensitive-information scanning successfully. PR
   and promotion commits are additionally gated by the same enforced checks.
   The GitHub PR/check history provides the exact hosted commit/run results.

This record describes the setup and verified checks before final PR promotion.
The resulting commit and PR identifiers are reported with task completion.
Remaining administrator choices are the second reviewer/mandatory approvals,
custom private-metadata push rules where supported, and whether to enable
Dependabot security updates in addition to scheduled action-version updates.

## Quarterly Dependabot schedule

Changed .github/dependabot.yml from weekly to quarterly version-update checks
at the user's request. GitHub Actions updates continue to target dev with a
five-open-PR limit. Updated docs/ci.md and ROADMAP.md to describe the current
schedule. GitHub documents quarterly runs on the first day of January, April,
July, and October. The configuration takes effect after reaching the default
branch; this request did not commit, push, or change remote settings.

Verification:

1. Confirmed quarterly is supported in GitHub's Dependabot options reference:
   https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#schedule
2. Inspected the diff: the sole Dependabot configuration change is interval.
3. Ran uv run --locked ruff check .: passed.
4. Ran uv run --locked ruff format --check .: passed, 42 files formatted.
5. Initial uv run --locked pytest -q --tb=short: 46 passed, 149 setup errors
   caused by an inherited unavailable AWS profile and inaccessible existing
   temporary directories. No test assertions or application code were changed.
6. Reran uv run --locked pytest -q --tb=short --basetemp <isolated-temp>/pytest,
   with process-local AWS_PROFILE/AWS_DEFAULT_PROFILE removed for mocked tests,
   UV_CACHE_DIR=.uv/cache, and TEMP/TMP set to a new ignored .uv directory:
   195 passed in 79.42 seconds, no skips. One non-failing pytest-cache write
   warning remains due to the existing cache directory. No live AWS calls ran.
7. Ran git diff --check: passed.

### Branch reconciliation verification

The pending changes were copied to a feature worktree based on origin/dev; the
original main working files were retained. On that branch, uv lock --check,
uv run --locked pytest -q --tb=short (195 passed in 85.94 seconds),
uv run --locked ruff check ., uv run --locked ruff format --check .,
uv run --locked python scripts/check_distribution.py, and git diff --check
passed. The checksum-verified scanner and its history/canary checks also passed.

## Developer workflow automation — October 22, 2026

### Implemented changes

Implemented on codex/developer-workflow in an isolated sibling worktree. The
existing main and dev checkouts remain clean. No application dependency, AWS
behavior, package interface, CI workflow, scanner policy, or GitHub setting was
changed.

- Added dev.ps1, a PowerShell launcher using the pinned local toolchain when
  available, with a normal installed-uv fallback and preserved exit codes.
- Added scripts/dev.py. start fetches origin/dev, validates names and existing
  refs/paths, creates a sibling worktree, and initializes it. setup installs
  locked dependencies and the checksum-verified scanner, preserves custom
  hooks, enables the versioned hooks when appropriate, and scans history.
- check runs scanner verification, lockfile validation, pytest, Ruff lint and
  formatting, clean distribution installation, and whitespace checks. Each
  worktree owns its environment and check scratch directory. Failures stop
  later steps; checks never silently reformat source or rewrite the lockfile.
- pr requires a clean, committed feature/* or codex/* branch containing current
  dev, runs checks, verifies the branch did not change during checks, and pushes
  without force before opening/reusing a PR into dev. Fetch/push repositories
  must agree. promote opens/reuses published dev into main and verifies main's
  ancestry, leaving release verification to the required hosted checks.
- Added 28 regression cases in tests/test_dev_workflow.py. These use real
  disposable Git histories/remotes and mocked GitHub calls, not live services.
  Coverage includes correct worktree bases, isolation, preserved files/hooks,
  setup recovery, name/ref collisions, dirty/incorrect branches, outdated dev,
  failed checks, concurrent branch changes, PR reuse/routing, push destinations,
  promotion ancestry, and CLI failure codes.
- Added docs/developer-helper.md and linked it from CONTRIBUTING.md and the
  branch/worktree guide. Updated ROADMAP.md. Documentation explains startup,
  manual review/commit/merge steps, recovery, portability, and rollout.

### Step-by-step verification and results

1. Ran .\dev.ps1 setup from the actual linked feature checkout. It created that
   checkout's .venv, installed all 21 locked packages, installed checksum-verified
   Gitleaks 8.24.3, and passed the file/history scan and scanner canaries.
2. Ran the focused developer-workflow tests. The first invocation could not use
   the existing shared Windows pytest temporary directory due to its filesystem
   permissions. Rerunning with an isolated temporary directory exposed two real
   bugs: Git's normalized hook configuration keys and remote-ref matching.
   Fixed both, preserving the failing regression cases. The helper now gives
   child check processes their own .uv/check-temp directory. The corrected
   focused suite passed 26 tests in 17.95 seconds; two additional hook/CLI
   regression cases were subsequently included in the full suite below.
3. Ran .\dev.ps1 check with uv 0.13.4 and Python 3.15.0. UV_CACHE_DIR selected the
   existing ignored shared download cache; UV_OFFLINE=true used already cached
   dependencies. The helper executed these exact checks successfully:

   ```text
   uv sync --locked
   uv run --locked python scripts/security_check.py --history --require-history
   uv lock --check
   uv run --locked pytest -q --tb=short
   uv run --locked ruff check .
   uv run --locked ruff format --check .
   uv run --locked python scripts/check_distribution.py
   git diff --check
   ```

   Results: **223 tests passed in 84.40 seconds**, no skips; lint passed;
   formatting passed for 45 files; the lockfile resolved 21 packages. Wheel and
   source-derived wheel builds, archive checks, clean installations, isolated
   imports, and both console entry points passed. Scanner canaries and all
   reachable history passed. The helper returned exit code 0.
4. Ran .\dev.ps1 --help successfully. Ran the launcher through PowerShell with
   start INVALID and verified exit code 1, the actionable naming error, and no
   worktree creation. Checked sys.prefix and both application imports to confirm
   they resolve to this feature checkout's environment and src directory.
5. Confirmed git status --short is empty in the original main and dev checkouts.
   Checked gh auth status --hostname github.com without exposing its output:
   it returned 1, so persistent GitHub CLI authentication remains incomplete.
6. After recording results, reran the history scan and git diff --check before
   saving the reviewed feature commit. Removed a trailing blank line reported
   by the whitespace check; both checks passed. The pre-commit hook also
   verified the staged content successfully.

### Branch reconciliation verification

Merged origin/dev into the developer-workflow feature branch without conflicts.
Ran .\dev.ps1 check with cached dependencies: scanner/history and canaries,
lockfile, 223 pytest cases (107.07 seconds), Ruff lint/format, package builds
and clean installations, and git diff --check passed. actionlint 1.7.12 also
passed the updated workflows. No AWS calls or PR merges were performed.

### Synchronization after the quarterly schedule PR

Merged updated origin/dev into the developer-workflow branch. Resolved the
implementation report conflict by retaining the quarterly schedule and developer
workflow sections. Ran .\dev.ps1 check with cached dependencies: security and
full history scans, lockfile, 223 pytest cases (94.68 seconds), Ruff lint and
format, clean distribution installation, and git diff --check passed. No AWS
calls or pull request merges were performed.

### Remaining rollout and limits

The helper is prepared locally; no real feature push, PR creation, merge, tag,
branch deletion, or GitHub administration was performed for this change. Run
gh auth login --hostname github.com --web once, then use the implementation
feature checkout's dev.ps1 pr command to publish it for review. Merge that PR
into dev before using start to create new features containing the helper.
Promote through the existing protected dev-to-main process when ready.

No new GitHub secrets, workflow permissions, or rules are required. The existing
hosted Linux/Windows jobs must validate the new commit before merge; this local
Windows run does not establish Linux success. GitHub PR calls were mocked in
tests, while pushes/worktrees were exercised against disposable local remotes.
Custom hooks require manual reconciliation; fork/Enterprise PR workflows are
outside this first helper. Existing reviewer and Dependabot administrator
choices from the prior report remain unchanged. No live AWS call was made.

## Synchronize the promotion back into dev

Created an isolated branch from origin/dev and merged origin/main to preserve
the promotion merge ancestry. The merge had no content conflicts. The original
main worktree's four uncommitted files were retained and a local patch was saved;
a comparison confirmed the patch remained unchanged.

In the synchronization checkout, ran .\dev.ps1 setup and .\dev.ps1 check
with the pinned toolchain and cached dependencies. The checksum-verified scanner
and history/canary checks passed; uv lock --check passed; uv run --locked pytest
-q --tb=short passed 223 tests in 107.59 seconds without skips; uv run --locked
ruff check . and uv run --locked ruff format --check . passed (45 files); and
uv run --locked python scripts/check_distribution.py and git diff --check passed.
No AWS operations were performed. GitHub checks must pass on the synchronization
PR before merging.
