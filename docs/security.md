# GitHub integration and safe publishing

Documentation is intended to be publishable. Use ACCOUNT_ID, APP_ID, API_ID,
OWNER/REPOSITORY, and REVIEWED_PLAN_ID placeholders. Resolve them locally before
running toolkit commands. Keep operational reports, plans, raw logs, screenshots,
customer/repository names, resource URLs, and local configuration out of commits.
Ignored `private/` and `.local/` directories can hold operator notes. Ignoring a
file does not encrypt it or remove copies that have already been committed.

## GitHub read integration

The toolkit uses installed `gh` credentials for github.com and GET requests only.
It validates OWNER/REPOSITORY and verifies the mapping against the Amplify app.
Branch and explicitly open PR lists use pagination, a pinned REST API version,
and JSON projections that omit PR bodies, user records, and arbitrary messages.
Fork heads are distinct from same-repository branches. Deleted fork repositories
are supported; malformed or duplicate branch evidence fails closed as unknown.

Requests are noninteractive, and inherited debug/terminal-output flags are
removed from the subprocess environment. Credentials retain normal gh resolution:
GH_TOKEN/GITHUB_TOKEN environment variables take precedence over stored gh login.
The toolkit never prints tokens, raw stderr, or server response errors. It does
not silently change users or retry rate limits. Check the intended gh account
locally with `gh auth status --hostname github.com`; do not paste its output.

| Error code | Local action |
| --- | --- |
| GitHubCliMissing | Install GitHub CLI and make it available on PATH. |
| GitHubAuthenticationRequired | Use `gh auth login --hostname github.com`; check whether an environment token overrides the stored login. |
| GitHubAccessDenied | Verify repository Contents read and Pull requests read access, organization SSO, and applicable access policies. |
| GitHubRepositoryUnavailable | Check spelling and access. A 404 can hide a private repository; it does not prove deletion. |
| GitHubRateLimited | Wait for the applicable reset/retry interval and rerun; automatic retries are deliberately absent. |
| GitHubTimeout / GitHubUnavailable | Check connectivity and gh installation, then rerun. |
| GitHubInvalidResponse / GitHubPageLimit / GitHubResponseLimit | Treat evidence as incomplete; review scope or response behavior before relying on it. |

The limits are 20 pages per endpoint, 100 rows per page, and a 20-second shared
process/pipe deadline. Stdout is bounded to 2 MiB and stderr to 64 KiB while being
read concurrently; overflow stops the process with a fixed error. These
are sequential observations, not an atomic repository snapshot. AWS execution
still requires an explicit local profile and the independent STS gate.
No GitHub or AWS login is required by the publication scanner.

## Local checks before the first commit and push

Run from the repository root after installing Python and uv:

```powershell
uv sync --locked
uv run --locked python scripts/install_security_tools.py
uv run --locked python scripts/security_check.py --history
git config --local core.hooksPath .githooks
```

On Linux, also run `chmod +x .githooks/pre-commit .githooks/pre-push`. When
staging the first commit, preserve the executable bits for other clones with
`git add --chmod=+x .githooks/pre-commit .githooks/pre-push`. New clones must
install the scanner and configure the hook path locally; Git does not copy
repository-local configuration when cloning. Review any existing hook path
before replacing it.

The installer downloads Gitleaks 8.24.3 into ignored `.uv/security-tools`, verifies
the archive against a pinned SHA-256 digest, and extracts only the executable.
Windows x64 and Linux x64 are configured. It is a deliberately pinned tested
version, not a claim to be the newest release. Review version/checksum updates
together and rerun the canaries and regression suite before accepting them.

The pre-commit hook scans the **complete staged index**, so fixing only the
working copy cannot hide a staged leak. The pre-push hook scans publishable
working files plus all locally reachable Git history and HEAD. A secret deleted
in a later commit still fails. The first working-tree scan supports a repository
with no commits. CI requires a commit and full history; shallow clones fail.
History scans also apply private-path, file-mode, and size restrictions to every
reachable commit tree, including deleted or renamed artifacts. Reusing the same
file contents under a private path cannot bypass that check. `--require-history`
implies history scanning even when `--history` is omitted. Tree checks add work
as distinct historical snapshots grow; timeouts fail the scan rather than skip it.
The scripts support Python 3.12+; the application still requires Python 3.15+.

The scanner extends Gitleaks credential rules with private metadata rules for
12-digit account IDs, common Amplify and AppSync identifier shapes, concrete
resource CLI arguments, and personal home paths. Only two synthetic account
values are allowed, restricted to tests and the rule configuration. The short
synthetic app fixtures remain usable. Documentation and tests are otherwise
scanned. Narrow exact-word exceptions avoid treating ordinary technical prose
as an Amplify ID. Inline `gitleaks:allow` comments and repository ignore-finding
files cannot suppress these scans. Every run first proves token/account/app/API
detection using generated, nonfunctional canaries.

The working-tree scanner uses Git's publishable-file list, including untracked
files but excluding ignored untracked reports/caches. Force-tracked ignored
files are still inspected. Private directories, JSON/JSONL reports, logs, env
files, and key artifacts are rejected even when force-staged. Symlinks,
submodules, conflicts, and files over 10 MiB require a separate review and fail
the snapshot scan. Findings print escaped filenames, line numbers, and rule IDs
only. Matching values, source lines, authors, messages, and scanner raw output
are withheld. No scan artifacts or PR comments are uploaded.

Publication is now restricted to UTF-8 text. Word/Office files, PDFs, archives,
images, executables, non-UTF-8 bytes, and binary control characters are rejected,
not skipped. Renaming a ZIP to `.txt` does not make it publishable. This policy
applies to working files, the complete staged index, and every reachable historical
blob, including deleted files. Git history is read with text diffs so `.gitattributes`
cannot suppress text findings. Private folder/file checks are case-insensitive,
including `Private`, `REPORTS`, `.AWS`, `.ENV`, and `Credentials`; distribution
path checks apply the same case normalization.

Keep generated Word guides and other binaries in ignored `reports/` and maintain
reviewable Markdown sources in `docs/`. There is no bypass switch or binary
exception list. Adding publishable binary assets requires a separate reviewed
policy and bounded content-inspection implementation. Content checks do not
make arbitrary encoded text safe or detect every private fact.

Exit codes: 0 passed, 1 findings, 2 incomplete/tool failure. All nonzero codes
block the hooks and fail CI. A missing scanner never silently passes. Local
hooks are clone-specific and can be bypassed, so server enforcement is also
needed. Pattern scanning cannot recognize every app ID, arbitrary password,
private repository name, image, or encoded/encrypted secret. Review remains
necessary; account/app identifiers are private metadata here even though they
are not authentication credentials.

## GitHub workflow and enforcement

`.github/workflows/sensitive-information.yml` runs on pushes to main, all pull
requests, merge_group, and manual dispatch. It checks out full history, installs the
checksum-verified scanner, executes detection canaries, and scans files/history.
The workflow uses a commit-pinned checkout action, `contents: read`, no persisted
checkout credentials, no application secrets, no AWS credentials, and no
pull_request_target event. It runs for all file changes, including docs-only PRs.
Gitleaks CLI needs no organization action-license secret in this setup.

Verify these settings in the intended repository:

1. Let **Sensitive information / sensitive-information** run once successfully.
2. In repository Settings, create an active branch ruleset for main (and dev if
   it is a shared integration branch). Require a pull request and the exact
   **sensitive-information** status check, using GitHub Actions as the expected
   source where available. Require up-to-date branches or the merge queue.
3. Require review, dismiss stale approvals on new commits, restrict bypasses,
   and prevent force pushes/deletions. Apply protections to administrators too
   where supported. Do not assume a workflow file alone enforces merges.
4. CODEOWNERS now assigns `.github/`, `.gitleaks.toml`, `.githooks/`, `scripts/`,
   and related verification/dependency files to `@Joskingy`. Verify write access
   and require owner review. These controls are code
   and a PR could weaken its own scanner. Organization-enforced required
   workflows from a protected repository provide stronger separation where
   available. A PR author cannot approve their own PR; arrange an independent
   trusted reviewer before enforcing approval for owner-authored changes.
5. Enable secret scanning and **push protection** in repository security settings
   where your repository/plan supports them. Restrict bypasses. Provider-token
   protection does not generally treat AWS account/app IDs as secrets. Configure
   custom patterns and their push protection where available if those metadata
   rules must also be enforced before any remote upload.
6. Verify with nonfunctional synthetic canaries in a disposable branch: the local
   hook must reject the commit/push; a remote PR test must fail the required check
   and prevent merging. Never test using a real credential.

A push workflow runs **after GitHub receives the push**. It cannot undo that
upload or prevent PR creation. Required checks block merging; local pre-push
hooks and GitHub push protection provide earlier rejection. Feature availability
depends on repository visibility and GitHub plan. Remote runs and settings must
be verified separately. See [CI and GitHub setup](ci.md) for all five required
check names, toolchain details, owner-review setup, and verification steps.

If a real credential ever reaches Git history, revoke/rotate it and remove it
from history before publication. Deleting it from the current file is insufficient.
No history rewrite, token rotation, remote creation, or push is performed by the
scanner. Do not add a blanket allowlist to make a failing scan green.

## References

- [GitHub CLI credential and debug environment](https://cli.github.com/manual/gh_help_environment)
- [GitHub REST errors, rate limits, and private-repository 404s](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api)
- [Required checks and protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/about-push-protection)
- [Pinned Gitleaks release](https://github.com/gitleaks/gitleaks/releases/tag/v8.24.3)
