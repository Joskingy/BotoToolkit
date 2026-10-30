# Continuous integration and GitHub setup

The workflows validate source, scanner policy, and package installation without
AWS access or application secrets. They run on every push, pull request, merge
queue request, and manual dispatch. Documentation-only changes are included.

## Jobs and toolchain

| Check name | Runner | Checks |
| --- | --- | --- |
| sensitive-information | ubuntu-24.04 | Full reachable Git history, publishable files, private artifact policy, scanner canaries |
| quality | ubuntu-24.04 | Lockfile consistency, Ruff lint and formatting |
| tests (ubuntu-24.04) | ubuntu-24.04 | Offline AWS/GitHub regressions and real scanner integration |
| tests (windows-latest) | windows-latest | The same regression suite on Windows |
| package | ubuntu-24.04 | Wheel/source builds, archive inspection, clean installations, both console commands |

Application CI pins uv 0.13.4 and stable Python 3.15.0. The project retains its
Python >=3.15 requirement and existing lockfile. CI installs with `uv sync
--locked`; it cannot silently refresh dependencies. The security-only workflow
uses the runner's Python 3.12+ and standard-library scripts independently.

Checkout and setup-uv use verified full commit SHAs. Checkout does not persist
credentials. Token permissions are limited to `contents: read`. uv's package
cache is enabled and keyed using uv.lock. No AWS credential setup, live service
test, deployment, report upload, or package publication is configured.

Each test runner installs checksum-verified Gitleaks, then runs its detection
canaries and checkout scan before pytest. A missing or broken scanner fails that
step, preventing a green CI run that skipped the scanner integration tests.
The matrix uses `fail-fast: false` so both platform results remain visible.

`scripts/check_distribution.py` builds through PEP 517 using the declared build
backend, inspects archives for both package namespaces and private/generated
paths, then tests two fresh environments: the wheel and a wheel rebuilt from the
source archive. Runtime dependencies are exported from uv.lock and installed with
hash verification. Local package installs use `--no-deps`. Import checks use
isolated Python and verify package locations inside the fresh environment;
both `amplify-ops --help` and `bototoolkit` must exit successfully. Temporary
environments are removed afterward. Initial execution may download locked wheels
and the build backend; no live AWS calls are involved.

Only newer runs of the same pull request cancel older runs of that workflow.
Concurrency groups include workflow and event identity. Push, manual, and merge
queue runs use independent run IDs and do not cancel PR checks or each other.

## Configure or verify in GitHub

These settings require repository administration and are not activated by local
files alone. Remote execution and enforcement have not been verified locally.

1. Push the reviewed files to OWNER/REPOSITORY. Enable GitHub Actions and ensure
   organization policies allow the pinned checkout/setup-uv actions and hosted
   Linux/Windows runners. Let all five checks run successfully on a pull request.
2. Create an active branch ruleset for main and any shared integration branch.
   Require pull requests and the five exact check names from the table, selecting
   GitHub Actions as their expected source where supported. Require current
   branches or use the merge queue. Both workflows include `merge_group`.
3. Require code-owner review and dismiss stale approvals after new commits.
   `.github/CODEOWNERS` assigns CI, scanner policy, hooks, tooling, scanner/package
   tests, dependency metadata, and Python selection to `@Joskingy`, as requested.
   Confirm that this account has write permission. CODEOWNERS itself is owned
   through `/.github/`. Restrict bypasses and protect against force pushes and
   branch deletion where supported.
4. If the author is also the sole owner, arrange another trusted reviewer before
   making owner approval mandatory for their changes; an author cannot approve
   their own pull request. Add an actual trusted user/team to CODEOWNERS when
   that reviewer is identified. Do not enable an unenforceable review process.
5. For stronger protection against a PR weakening its own scanner, use an
   organization-enforced required workflow from a separately protected repository
   where available. A local workflow and CODEOWNERS depend on enforced review.
6. Enable GitHub Secret Protection/push protection where supported, and restrict
   bypasses. Custom private account/app-ID patterns need separate configuration
   where available. A push-triggered workflow runs after upload; required checks
   prevent merging, not the initial upload or PR creation.
7. Enable Dependabot version updates and review its quarterly GitHub Actions PRs.
   Keep full SHA pins. Embedded uv/Python/Gitleaks version pins require deliberate
   maintenance; Gitleaks changes also require verified Windows/Linux checksums
   and review of the scanner/test version references. No automatic merges are set.
8. Verify enforcement with disposable PRs and nonfunctional canaries: a broken
   assertion must fail tests, an invalid package must fail the package job, and a
   synthetic secret must fail the security check and prevent merging. Exercise
   the merge queue if enabled. Never use real credentials for this test.

Repository visibility and GitHub plan affect feature availability. No deployment
environment, cloud secrets, OIDC role, or package-registry credential is required
for these CI checks.

## Reproduce locally

Use uv 0.13.4 and Python 3.15.0 to match CI. Run from the repository root:

```text
uv sync --locked
uv lock --check
uv run --locked python scripts/install_security_tools.py
uv run --locked python scripts/security_check.py --history --require-history
uv run --locked pytest -q --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/check_distribution.py
```

The package helper's PEP 517 build requires a uv version supporting
`--force-pep517`. Restricted Windows sessions can use the cache/temp settings in
README.md. A separate `UV_PROJECT_ENVIRONMENT` lets verification avoid changing
the developer's active `.venv`.

References: [uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/),
[required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks),
[code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners),
[workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
