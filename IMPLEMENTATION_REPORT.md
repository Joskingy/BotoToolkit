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
