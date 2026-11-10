# Branches and worktrees

Use `main` for reviewed releases, `dev` for integration, and one feature worktree
per task. Ordinary PRs target `dev`; promotion PRs target `main`. Use merge commits
for promotion and synchronization so branch ancestry remains intact.

The [developer helper](developer-helper.md) covers `start`, `setup`, `check`, `pr`,
and `promote`. Each worktree has its own environment and scanner. Ignored private
files and deployment claims are not copied into new worktrees.

## Create or attach a branch

From a clean initialized checkout, create a new branch and worktree together:

```powershell
.\dev.ps1 start improve-help
```

This creates `feature/improve-help` from `origin/dev`. Use the exact folder printed
by the helper. For Codex work, add `--prefix codex`. Existing names are rejected.
If setup fails, keep the created worktree and rerun `dev.ps1 setup` there after
resolving the cause.

To attach an existing local branch instead:

```powershell
git worktree add ../BotoToolkit-feature-improve-help feature/improve-help
Set-Location ../BotoToolkit-feature-improve-help
.\dev.ps1 setup
```

A branch cannot be checked out in two worktrees. Switch the original checkout to
another available branch first if necessary. Inspect `git worktree list` before
creating or removing a worktree. The helper always operates on the checkout
containing the invoked `dev.ps1`.

## Keep a feature current

Commit or save pending work before merging the current integration branch:

```powershell
git fetch origin
git merge origin/dev
.\dev.ps1 check
```

Resolve conflicts, review and commit the result, then run `dev.ps1 pr`. It checks
the committed feature, pushes without force, and opens or reuses a PR into dev.
If pushing succeeds but PR creation fails, fix access and rerun the command.
Required hosted checks and review still apply. The helper never merges a PR.

## Promote and synchronize

Run `dev.ps1 promote` to open or reuse the published dev-to-main PR. Review the
entire release diff, wait for all six required checks and review, and merge using
a merge commit. Keep the `dev` branch. Refresh the main worktree with
`git pull --ff-only origin main`.

After promotion, synchronize main into dev through a temporary feature:

```powershell
.\dev.ps1 start sync-main-to-dev --prefix codex
Set-Location ../BotoToolkit-codex-sync-main-to-dev
git merge origin/main
```

Resolve conflicts, check and commit the result, then run `dev.ps1 pr`. If dev
advances, merge `origin/dev` into this temporary branch and repeat verification.
Do not update main by merging unreleased dev changes into it just to resolve a
synchronization problem. Never force-reset dev to main.

For an urgent release fix, create a `hotfix/*` worktree from `origin/main`, run
setup and checks, and open a reviewed PR into main. The helper's feature `pr`
command targets dev, so open a hotfix PR explicitly. Synchronize main into dev
afterward using the same process above.

Tag only a reviewed, tested main commit with an unused release version. Do not
move existing tags. Tag pushes do not trigger CI; verify that commit through
main CI or manual workflow dispatch first. Tags do not publish packages or deploy AWS.

## Retire a completed worktree

From another checkout, substitute the exact folder and branch you intend to retire:

```powershell
git fetch origin --prune
git -C ../BotoToolkit-feature-improve-help status --short --ignored
git merge-base --is-ancestor feature/improve-help origin/dev
```

The ancestry command must exit 0; inspect `$LASTEXITCODE` in PowerShell. Review
ignored files as well as tracked changes, and preserve any private material you
still need. Keep deployment audit claims in stable private storage; never move or
delete consumed claims to enable replay.

Only after confirming the exact folder and that it has nothing to retain:

```powershell
git worktree remove ../BotoToolkit-feature-improve-help
git branch -d feature/improve-help
```

Delete a remote feature branch only after confirming it is merged and nobody
needs it. If Git refuses removal or deletion, inspect the reason instead of
using `--force` or `-D`. Update a stale local dev worktree before retrying safe
branch deletion. Keep the main and dev worktrees; use Git's worktree commands
instead of deleting their folders manually.
