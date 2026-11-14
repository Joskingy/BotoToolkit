# Developer onboarding

The recommended contributor workflow is a Git clone plus uv. Keep pyproject.toml,
uv.lock, and .python-version in Git; each developer creates their own .venv.
The application currently requires Python 3.15+. Git and uv are prerequisites;
GitHub CLI is needed for PR automation and the stale command's GitHub evidence. AWS CLI or
your normal credential setup is needed for live AWS use, not for offline tests.

## First clone

Replace OWNER/REPOSITORY with the intended repository location. The local destination name below is just a folder name.

```powershell
git clone https://github.com/OWNER/REPOSITORY.git amplify-ops
cd amplify-ops
uv sync --locked
uv run --locked amplify-ops --help
uv run --offline --no-sync amplify-ops doctor --project .
uv run --locked python scripts/install_security_tools.py
git config --local core.hooksPath .githooks
uv run --locked python scripts/security_check.py --history
uv run --locked pytest -q --tb=short
```

uv sync creates .venv, installs locked dependencies including development tools,
and installs this project in editable mode. Source edits are immediately used
by uv run. The --locked flag rejects an outdated lockfile rather than silently
changing it. Virtual-environment activation is optional.
The [doctor command](docs/doctor.md) diagnoses the installed environment and
optional repository checks without resolving AWS credentials. It is useful
before your first live read, but does not replace tests or security scans.

The scanner installer currently supports Windows x64 and Linux x64. On Linux,
run `chmod +x .githooks/pre-commit .githooks/pre-push` before using the hooks.
Check for existing custom hooks before replacing core.hooksPath. Hook setup is
local to each clone; it is not inherited automatically from the remote.
See [the security guide](docs/security.md) for supported platforms, first-commit
executable bits, remote enforcement, and the limits of pattern scanning.

Tests use synthetic credentials and mocked AWS/GitHub responses. Scanner tests
exercise a real local Gitleaks binary and disposable repositories; install that
binary before running the suite to avoid skipping those cases. Tests do not
need AWS access or GitHub login and do not submit real deployments.

## Continuous integration

For the checks that run on pull requests, see [CI and GitHub setup](docs/ci.md).
CI tests Linux and Windows, checks lint/format and the lockfile, validates built
package installation, and scans private information. It uses no AWS credentials.
To reproduce the package job, use uv 0.13.4 and run
`uv run --locked python scripts/check_distribution.py`.

## First live read

Replace PROFILE_NAME below with your local AWS profile name.
Configure/sign in to that profile using your
normal authentication process. Resolve ACCOUNT_ID independently from private
operator settings; do not copy an STS response just to satisfy the assertion.
Replace the example region with the region you intend to inspect.

```powershell
uv run --locked amplify-ops --profile PROFILE_NAME --expected-account ACCOUNT_ID --region us-east-1 identity
uv run --locked amplify-ops --profile PROFILE_NAME --expected-account ACCOUNT_ID --region us-east-1 inventory
```

For GitHub evidence, sign in with `gh auth login --hostname github.com` and
verify the intended repository access. Do not store tokens in source or docs.
Keep live IDs, resource names, command output, plans, and reports in ignored
local storage. Start with read-only commands; deploy requires a separate
reviewed plan, explicit confirmations, and separate AWS permissions.

## Everyday work

Use `dev.ps1` for the automated path: `start NAME` creates and initializes a
feature worktree, `check` runs local checks, `pr` checks/pushes and opens a PR
into dev, and `promote` opens dev into main. See the
[developer helper guide](docs/developer-helper.md) for prerequisites, examples,
recovery, and the explicit review/commit/merge steps.

Use main for reviewed releases, dev for integration, and a separate feature/*
or codex/* branch and worktree for each task. Target dev in ordinary pull
requests; promote dev to main with a merge commit. See [the branch and worktree
guide](docs/branching-and-worktrees.md) for setup, synchronization, and cleanup.
GitHub protection and review requirements must also be configured remotely.

```powershell
uv sync --locked
uv run --locked pytest -q --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/security_check.py --history
```

When intentionally changing dependencies, use uv add/uv remove and review both
pyproject.toml and uv.lock. Do not regenerate the lockfile merely to silence a
failure. Keep documentation examples as placeholders. Personal .code-workspace
files are ignored; developers can create their own editor workspace locally.

## Folder responsibilities and recommendations

The current src layout and command-sized modules are appropriate for this CLI.
Retain them until module size or dependency boundaries justify a split.

| Location | Responsibility |
| --- | --- |
| src/amplify_ops/ | Application code: CLI, AWS/GitHub adapters, reports, domain operations |
| src/bototoolkit/ | Preserved original Python package; both CLI entry points use amplify_ops |
| tests/ | Offline regression tests and scanner integration tests |
| scripts/ | Contributor/security tooling, separate from installed application code |
| docs/ | Detailed command usage, security, and operational guidance |
| .github/workflows/ | Repository CI workflows |
| .githooks/ | Versioned local commit/push hooks |
| .gitleaks.toml | Versioned scanner policy; keep in Git |
| reports/, private/, .local/, .amplify-ops/ | Ignored operational outputs and local state |

## Why keep the Gitleaks configuration?

.gitleaks.toml is scanner configuration, not a credential file or a runtime
dependency. It extends Gitleaks' built-in secret detection with this project's
private-metadata rules, including account IDs and common resource-ID shapes.
It also defines narrow synthetic-test exceptions. Keeping it versioned makes
local hooks and CI use the same reviewable policy.

The application itself works without Gitleaks. The current publication checks
explicitly require this configuration and the installed scanner; deleting the
file would make those checks fail. Ordinary credential scanning alone would
not express this project's additional privacy requirements. Account and app IDs
are metadata rather than passwords, but this project intentionally avoids
publishing them. Never place real credentials or live IDs in scanner allowlists.

## Distribution for operators

Contributors should use the locked checkout workflow above. Operators can use
a tool installation from a trusted checkout:

```powershell
uv tool install --python 3.15.0 .
bototoolkit --help
```

If needed, run `uv tool update-shell` and open a new shell to make installed
commands available. A tool install creates its own isolated environment and
does not follow live source edits or consume the project's development lockfile.
After an intentional update, reinstall from the reviewed checkout with
`uv tool install --force --python 3.15.0 .`.

The package remains named `amplify-ops`; both `bototoolkit` and `amplify-ops`
commands are installed. To include the terminal browser from a trusted checkout,
use `uv tool install --force --python 3.15.0 '.[tui]'`.

### Versioned wheel installation

Download the wheel and SHA256SUMS from the
[v0.2.0 release](https://github.com/Joskingy/BotoToolkit/releases/tag/v0.2.0).
Follow the [user guide](docs/quick-start.md#2-install-and-check-bototoolkit) to verify the checksum.
From the download directory, install the wheel:

```powershell
uv tool install --python 3.15.0 ./amplify_ops-0.2.0-py3-none-any.whl
bototoolkit --help
bototoolkit doctor
```

For the terminal browser, use
`uv tool install --force --python 3.15.0 './amplify_ops-0.2.0-py3-none-any.whl[tui]'`.
Then run `bototoolkit tui --demo`. Tool installation resolves dependencies from
package metadata; use the locked checkout workflow when exact dependency
versions are required. Keep using `amplify-ops` if existing scripts depend on it.

Release preparation uses `uv run --locked python scripts/check_distribution.py`
to validate wheel/source installations. Build the final artifacts from the
reviewed main commit using `uv build --no-sources`; publish only after approval
and successful CI. Follow the [release tag rules](docs/branching-and-worktrees.md)
before creating a tag. Do not publish local working-tree builds as final releases.

References: [uv project synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[uv tool environments](https://docs.astral.sh/uv/concepts/tools/).
