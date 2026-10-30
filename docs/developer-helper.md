# Developer workflow helper

Use `dev.ps1` from PowerShell to create feature worktrees, check your work, and
open GitHub pull requests. The implementation lives in `scripts/dev.py`; it is
contributor tooling and is not an installed amplify-ops command.

## Prerequisites and first use

Install Git, uv **0.13.4**, and GitHub CLI. The helper uses Python **3.15.0** to
match CI; uv can download it if needed. On this project's existing Windows
clone, the launcher also recognizes the pinned tools under the main checkout's
ignored `.uv` directory. Each worktree still gets its own `.venv` and scanner.
The scanner installer supports Windows x64 and Linux x64.

Sign in to GitHub once using the normal browser flow:

```powershell
gh auth login --hostname github.com --web
```

Git must also be able to fetch/push `origin` using your normal HTTPS credential
manager or SSH setup. No tokens belong in scripts, remote URLs, or documentation.
PR commands support a single github.com repository as both the fetch and push
destination, in standard HTTPS or SSH form. Fork workflows and GitHub Enterprise
require a separate adaptation.

After cloning, or to repair an existing checkout:

```powershell
.\dev.ps1 setup
```

This synchronizes locked dependencies, enables the versioned Git hooks if there
are no custom hooks to reconcile, installs the checksum-verified scanner when
missing, and scans publishable files plus reachable Git history. Existing custom
hooks are preserved and reported for manual reconciliation. Setup can be rerun.
It needs network access for missing Python/packages/scanner downloads.

The helper must first be merged into `dev` before `start` can create worktrees
that contain it. Update the checkout you launch from after the helper is merged;
until then, try `setup` and `check` in the implementation feature worktree.

## 1. Create a feature

From a clean checkout containing the helper:

```powershell
.\dev.ps1 start improve-help
```

The helper fetches origin, creates `feature/improve-help` from the latest
`origin/dev`, and initializes a sibling directory named
`BotoToolkit-feature-improve-help` when the original clone is named BotoToolkit.
It prints the exact path and the `Set-Location` command to enter that folder.
Run that command, then open that folder in your editor.

For a Codex task, use `start improve-help --prefix codex`. Names use lowercase
letters, digits, and separating hyphens, with at most 60 characters. Existing
branches/folders are rejected. If initialization fails, the created worktree is
retained; fix the reported cause and run `setup` inside it. Ignored private files
and environments are never copied from another checkout.

The launcher always operates on the checkout containing that launcher. Calling
another checkout's `dev.ps1` does not operate on your current directory.

## 2. Develop and check

Edit source, tests, and documentation in the new feature folder, then run:

```powershell
.\dev.ps1 check
```

The command stops at the first failure and runs these steps:

1. Initialize this checkout and verify the scanner against its canaries; scan
   files and reachable history.
2. Check that the lockfile matches project metadata.
3. Run the full pytest suite, including real scanner and disposable Git tests.
4. Run Ruff lint and formatting checks.
5. Build wheel/source archives and verify clean installation and entry points.
6. Check the working diff for whitespace errors.

Checks use this checkout's `.venv`; child process scratch files use its ignored
`.uv/check-temp` directory. An activated environment from another worktree is
not reused. Checks do not contact AWS. Setup/package downloads may need the
network; the application tests use mocked AWS and GitHub responses.

## 3. Review, commit, and open the feature PR

Review your changes and stage only the intended files. For example, if you
changed the helper guide:

```powershell
git --no-pager diff
git add docs/developer-helper.md
git --no-pager diff --cached
git commit -m "docs: improve developer helper guide"
.\dev.ps1 pr --title "Improve developer helper guide"
```

Replace the example paths/message/title with your actual change. The helper
does not stage files or create commits. `pr` requires a clean `feature/*` or
`codex/*` branch with committed work ahead of dev. It fetches origin, requires
the latest dev to be included, runs all checks again, pushes the feature branch
without force, and opens a PR with **base dev**. It detects branch changes
during checks before pushing. An already open PR for that branch/base is reused.

Use `--draft` for a draft PR or `--body-file PATH` for a reviewed description
file. Body paths are relative to your terminal directory unless absolute.
The default description uses the branch name and a check summary; it does not
copy command output, private reports, or commit bodies into the PR.

If dev advances, commit/save pending work, then:

```powershell
git fetch origin
git merge origin/dev
```

Resolve any conflicts and finish the merge before rerunning `pr`. If the push
succeeds but GitHub PR creation fails, fix authentication/service availability
and rerun `pr`; the branch remains intact. Wait for the required hosted checks
and reviews, then merge on GitHub using a merge commit.

## 4. Promote dev to main

After feature PRs are merged into dev and the release is ready:

```powershell
.\dev.ps1 promote --title "Promote dev to main"
```

This fetches the remote refs and opens or reuses a **dev -> main** PR. It uses
the published dev branch, not unpushed local work, and includes every dev commit
ahead of main. Main must already be an ancestor of dev; otherwise synchronize
main back into dev first. The command does not claim to test a different local
checkout: the required GitHub checks validate the actual promotion PR.

Review and merge on GitHub. Keep dev. Follow the
[branch guide](branching-and-worktrees.md#9-promote-a-release-and-synchronize-the-branches)
for release tags, main-to-dev synchronization, and retiring completed worktrees.
The synchronization branch can use `start sync-main-to-dev --prefix codex`,
then `git merge origin/main` and `pr` from its worktree.

## Portability and boundaries

On Linux, or when PowerShell script execution is restricted, invoke the same
helper directly with the pinned uv installed:

```text
uv run --no-project --python 3.15.0 scripts/dev.py --help
uv run --no-project --python 3.15.0 scripts/dev.py check
```

Replace `check` with any other subcommand. No machine-wide execution-policy
change is required. Git/uv/gh failures return a nonzero exit code; later steps
do not run. The helper never merges PRs, force-pushes, deletes worktrees/branches,
creates release tags, changes GitHub rules, or performs AWS operations. Existing
GitHub branch protection and hosted Linux/Windows checks remain authoritative.

References: [Git worktrees](https://git-scm.com/docs/git-worktree),
[GitHub PR creation](https://cli.github.com/manual/gh_pr_create),
[GitHub PR lookup](https://cli.github.com/manual/gh_pr_list).
