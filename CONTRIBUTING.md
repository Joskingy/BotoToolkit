# Developer onboarding

The recommended contributor workflow is a Git clone plus uv. Keep pyproject.toml,
uv.lock, and .python-version in Git; each developer creates their own .venv.
The application currently requires Python 3.15+. Git and uv are prerequisites;
GitHub CLI is needed only for the stale command's GitHub evidence. AWS CLI or
your normal credential setup is needed for live AWS use, not for offline tests.

## First clone

Once the repository has been published, replace OWNER/REPOSITORY with its
actual location. The local destination name below is just a folder name.

```powershell
git clone https://github.com/OWNER/REPOSITORY.git amplify-ops
cd amplify-ops
uv sync --locked
uv run --locked amplify-ops --help
uv run --locked python scripts/install_security_tools.py
git config --local core.hooksPath .githooks
uv run --locked python scripts/security_check.py --history
uv run --locked pytest -q --tb=short
```

uv sync creates .venv, installs locked dependencies including development tools,
and installs this project in editable mode. Source edits are immediately used
by uv run. The --locked flag rejects an outdated lockfile rather than silently
changing it. Virtual-environment activation is optional.

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

Configure/sign in to the intended local AWS profile brewmaster using your
normal authentication process. Resolve ACCOUNT_ID independently from private
operator settings; do not copy an STS response just to satisfy the assertion.
Replace the example region with the region you intend to inspect.

```powershell
uv run --locked amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 identity
uv run --locked amplify-ops --profile brewmaster --expected-account ACCOUNT_ID --region us-east-1 inventory
```

For GitHub evidence, sign in with `gh auth login --hostname github.com` and
verify the intended repository access. Do not store tokens in source or docs.
Keep live IDs, resource names, command output, plans, and reports in ignored
local storage. Start with read-only commands; deploy requires a separate
reviewed plan, explicit confirmations, and separate AWS permissions.

## Everyday work

For the proposed main/dev/feature process, migration sequence, and per-checkout
setup, see [the branch and worktree guide](docs/branching-and-worktrees.md).
The guide is an adoption plan; branches and GitHub rules are not created by it.

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
| src/bototoolkit/ | Preserved original scaffold and compatibility entry point |
| tests/ | Offline regression tests and scanner integration tests |
| scripts/ | Contributor/security tooling, separate from installed application code |
| docs/ | Detailed command usage, security, and operational guidance |
| .github/workflows/ | Repository CI workflows |
| .githooks/ | Versioned local commit/push hooks |
| .gitleaks.toml | Versioned scanner policy; keep in Git |
| reports/, private/, .local/, .amplify-ops/ | Ignored operational outputs and local state |

Recommended next organizational changes, when useful:

- Shorten README into a product overview and quick start, moving its longer
  command reference into docs. Keep CONTRIBUTING focused on development.
- Move historical implementation records into docs/history once links are
  updated. Keep ROADMAP near the root if it is actively maintained.
- If CLI dispatch grows difficult to navigate, split command groups into an
  amplify_ops/commands package while retaining a small cli entry point.
- If more providers are added, group AWS/GitHub adapters in an integrations
  package. Avoid creating many single-file subpackages before they are needed.
- Review whether bototoolkit remains a supported interface before deprecating
  its package and entry point. Preserve it until that decision is explicit.
- The current blanket *.json exclusion is intentionally conservative. If
  public schemas or fixtures become necessary, review narrowly scoped allowlists
  in both .gitignore and the scanner's private-artifact policy together.

These are proposed structural changes, not a file relocation performed during
this onboarding update. Live reports remain local; no private files are moved
into public documentation.

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
uv tool install --python 3.15 .
amplify-ops --help
```

If needed, run `uv tool update-shell` and open a new shell to make installed
commands available. A tool install creates its own isolated environment and
does not follow live source edits or consume the project's development lockfile.
After an intentional update, reinstall from the reviewed checkout with
`uv tool install --force --python 3.15 .`.

A future release process should provide a versioned wheel or a reviewed Git
tag/commit for tool installations, with release tests and provenance. No package
publication, remote installation, or release creation is performed here.

References: [uv project synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[uv tool environments](https://docs.astral.sh/uv/concepts/tools/).
