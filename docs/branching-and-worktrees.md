# Main, dev, and feature branches with Git worktrees

This guide includes the original migration procedure and the ongoing developer
workflow. The initial snapshot below was recorded on October 21, 2026. For actual
adoption progress and verification, see the latest branch/worktree section in
[IMPLEMENTATION_REPORT.md](../IMPLEMENTATION_REPORT.md). Commands are for PowerShell; run each
step from the stated directory and stop when a command fails. Replace
OWNER/REPOSITORY with the intended GitHub repository. No AWS access is needed.

## 1. Understand the starting point

The local repository has one worktree, on main, and an origin/main tracking ref.
There is no local dev or feature branch. The working directory contains pending
audit fixes, tests, CI, security tooling, and documentation. These are not yet
part of the committed baseline. A new worktree would not inherit those edits.
Remote branch state and GitHub settings still need to be refreshed/verified.

The origin URL currently identifies a personal repository. Decide whether to
keep that location or transfer the repository to the intended organization
before changing repository settings. Do not create another unrelated repository
or replace origin just to introduce this branching model.

| Existing location | Assessment and adaptation |
| --- | --- |
| src/amplify_ops/ | Keep the current application/module boundaries. Branches contain the entire project. |
| src/bototoolkit/ | Preserve the compatibility package and console command. |
| tests/ | Keep the offline suite together; run it independently in each worktree. |
| pyproject.toml, uv.lock, .python-version | Version these together; create a separate environment per checkout. |
| .github/workflows/ | Both proposed workflows already run on all branches and PRs; no trigger change is needed. |
| .github/dependabot.yml | Plan to add target-branch: dev after dev exists; keep the configuration on main too. |
| .github/CODEOWNERS | Keep CI/security ownership on both main and dev; resolve the single-owner review limitation. |
| .githooks/, .gitleaks.toml, scripts/ | Retain the scanners and hooks; install the scanner in each checkout. |
| docs/, CONTRIBUTING.md | Keep this guide alongside CI/security instructions. |
| .agents/ | The trial skill is currently untracked. Decide whether it is shared project tooling before staging it. |
| .uv/, .venv/, ignored reports and editor files | Local only; new worktrees do not copy them. |

The existing ignore policy already covers environments, tool caches, private
outputs, and editor workspace files. Sibling worktree directories require no
new ignore rule. Avoid creating branches as subfolders under src or nesting a
second checkout inside this repository.

## 2. Adopt a simple branch contract

| Branch | Purpose | Starts from | PR target |
| --- | --- | --- | --- |
| main | Reviewed release history; keep as GitHub default | Existing main | Receives dev promotions and urgent fixes |
| dev | Shared integration and testing | Reviewed main baseline | main when ready to release |
| feature/short-name | One developer change | origin/dev | dev |
| codex/short-name | A feature or maintenance task handled by Codex | origin/dev | dev |
| hotfix/short-name | Urgent fix to the released code | origin/main | main, followed by main into dev |

Normal flow: feature -> dev -> main -> synchronize main back into dev.
Hotfix flow: main -> hotfix -> main -> dev.

Start with **merge commits for all PRs**. This preserves ancestry and makes
branch cleanup straightforward. In particular, never squash or rebase a dev to
main promotion or a main to dev synchronization. Keep linear-history rules off
on these two branches. GitHub's merge-commit method preserves the source commits;
its squash method creates a new commit. See [GitHub merge methods](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/about-merge-methods-on-github).

Keep main as the default so visitors see released code. Always explicitly
select dev as the base for ordinary PRs. Branch names do not create AWS
environments or authorize deployments; CI stays offline with mocked AWS calls.

## 3. Save the current work on a transition branch

Run from the existing BotoToolkit directory. First stop other editors/agents
from modifying this same directory while the migration snapshot is prepared.

```powershell
git status --short
git branch --all
git worktree list
git remote -v
git switch -c codex/branching-bootstrap
```

Creating this branch at the current commit preserves the pending edits. Review
the audit, CI, and guide changes. Stage related changes as separate commits
where practical. Use explicit paths, including reviewed new files; for example:

```powershell
git add docs/branching-and-worktrees.md
git --no-pager diff --cached --stat
git --no-pager diff --cached
uv run --locked python scripts/security_check.py --staged
git commit -m "docs: describe branch and worktree workflow"
```

This example stages only the guide. Repeat for the actual audit/CI/documentation
files until all intended changes are committed. Inspect git status for untracked
files too: staging tracked modifications alone misses the new workflow and tests.
Do not force-add ignored outputs. A local skill intentionally left untracked
will remain only in the original directory unless installed in another checkout.

Before any push, run the validation checklist in step 8, including the full
history scan. The existing pre-commit/pre-push hooks must succeed. If a scanner
is missing, install it; do not bypass the hook. Use uv 0.13.4 and Python 3.15.0
to match the current CI setup.

Only once all intended work is safely committed, refresh the remote baseline:

```powershell
git fetch origin --prune
git merge origin/main
```

Resolve conflicts and rerun checks if origin/main advanced. Preserve the
transition branch; do not reset the pending work to match the remote. If origin
already has dev, use its existing integration history instead of recreating it.

## 4. Create the worktree layout and bootstrap dev

Recommended sibling layout under the current parent directory:

```text
AWSandIT/
  BotoToolkit/                 main, existing clone and Git storage
  BotoToolkit-dev/             dev, integration verification
  BotoToolkit-bootstrap/       codex/branching-bootstrap, temporary
  BotoToolkit-feature-help/    feature/improve-help, temporary
```

Do not move or recreate the original clone. Git worktrees share repository
history and normal local Git configuration, but have separate checked-out files
and indexes. Git normally prevents checking out one branch in two worktrees.
See [Git worktree documentation](https://git-scm.com/docs/git-worktree).

From BotoToolkit, after committing the transition work:

```powershell
git switch main
git pull --ff-only origin main
git worktree add ../BotoToolkit-bootstrap codex/branching-bootstrap
git worktree add -b dev ../BotoToolkit-dev origin/main
```

Before pushing, initialize both new checkouts with the setup commands in step 5
so their pre-push hooks can find uv, dependencies, and their own scanner. The
existing baseline already includes the scanner installer and security hook.
Run the complete step 8 checks in the bootstrap checkout, which contains the
pending package helper and other CI changes. Return to BotoToolkit, then:

```powershell
git -C ../BotoToolkit-dev push -u origin dev
git -C ../BotoToolkit-bootstrap push -u origin codex/branching-bootstrap
git worktree list
```

These commands assume dev does not yet exist and main can fast-forward. If
either assumption fails, inspect the existing branch/history before proceeding.
For an existing remote dev without a local dev, use instead:

```powershell
git worktree add --track -b dev ../BotoToolkit-dev origin/dev
```

The initial dev push creates a branch at the existing reviewed baseline. If
GitHub prohibits branch creation, an administrator must create that reference
through the repository's permitted process; do not bypass the policy.

Open a GitHub PR with **base dev**, **compare codex/branching-bootstrap**. Review
and merge with a merge commit after all checks pass. This establishes the pending
audit/CI improvements on dev. Initial dev may not yet contain CODEOWNERS; arrange
explicit trusted review for this bootstrap PR. Then promote dev to main using
step 9 so both long-lived branches have CI and ownership files before routine
development. Keep dev after the promotion.

The commands above are the one-time bootstrap procedure. Do not rerun branch
creation against an existing setup; inspect git worktree list and git branch
--all first. Follow the implementation report for the current migration state.

## 5. Initialize every checkout independently

Run these commands from each new checkout after its branch contains the current
tooling. Use a fresh terminal without another checkout's environment activated.

```powershell
uv --version
uv python install 3.15.0
uv sync --locked --python 3.15.0
uv run --locked python scripts/install_security_tools.py
git config --show-origin --get core.hooksPath
uv run --locked amplify-ops --help
uv run --locked python scripts/security_check.py --history --require-history
```

Each checkout gets its own .venv and .uv/security-tools. Do not copy or share
.venv between worktrees: the editable application must point at that checkout.
If UV_PROJECT_ENVIRONMENT is set, ensure it resolves inside the current checkout,
not another branch's absolute environment path. Cache sharing is different from
sharing an environment; uv's download cache may be shared. See [uv environment
configuration](https://docs.astral.sh/uv/concepts/projects/config/).

The current clone already has core.hooksPath set to .githooks. That relative
setting is shared by its linked worktrees and uses each checkout's versioned
hooks. A separate new clone needs the onboarding hook setup. If the setting is
absent, review any existing hooks, then run once per clone:

```powershell
git config --local core.hooksPath .githooks
```

The hook scripts are already tracked executable with LF endings. Verify they run
on the first commit/push in a worktree. Hooks run from the working-tree root for
these client operations; see [Git hook behavior](https://git-scm.com/docs/githooks).
Do not set an absolute hooksPath to another branch's checkout. GitHub protection
is still required because local hooks are bypassable.

Local credentials remain in the normal local AWS profile mapping. Offline tests
need no authentication. Keep reports and private settings ignored in their
intended checkout; do not copy live output into example files.

Deployment plans and .amplify-ops/audit are especially important: the default
audit location is relative to the working directory, and a worktree does not
share that local consumed-plan record. Do not replay a plan from another
worktree or treat an empty audit directory as permission to retry. Keep any
future authorized deployment operation in one designated operator checkout and
audit location. This guide performs no deployment verification.

## 6. Configure GitHub for both long-lived branches

After bootstrap checks have appeared on GitHub, configure active rulesets for
main and dev. Feature availability depends on repository visibility and plan.
See [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
and the project's [CI setup](ci.md).

1. Require a PR, resolved review conversations, and these five checks on both
   branches: quality, tests (ubuntu-24.04), tests (windows-latest), package,
   sensitive-information. Select GitHub Actions as the check source where available.
2. Require the PR branch to be current with its base. Start without a merge
   queue; if added later, configure its merge method to preserve merge commits.
3. Block force pushes and deletion on main and dev; restrict bypass access.
   Leave linear-history requirements disabled for the chosen merge strategy.
4. Enable merge commits in repository merge settings. Initially disable squash
   and rebase merging to avoid accidental promotion mistakes.
5. Keep .github/CODEOWNERS on both branches. GitHub reads the PR base branch's
   file. @Joskingy is the current CI/security owner; confirm write access.
   Add a second trusted owner before requiring owner approval for changes
   authored by the sole owner. While working solo, require checks and PRs but
   leave mandatory independent approvals off; document that reduced review level.
   See [CODEOWNERS behavior](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).
6. Keep main as the default branch. Leave automatic head-branch deletion off
   initially; manually delete only merged feature/hotfix branches, never dev.
7. Enable supported secret push protection and restrict bypass. CI can block a
   merge after a push; it cannot prevent the initial upload. Keep the local
   pre-push scan and the project's private-identifier policy too.

These rules do not, by themselves, restrict main PRs to a dev source branch.
Enforce the target convention in review initially. An optional later dedicated
check can validate PR source/target pairs, including same-repository identity,
hotfix and synchronization exceptions. Do not grant it AWS permissions.

The bootstrap changes set the following option on the existing GitHub Actions
entry in .github/dependabot.yml. It takes effect when promoted to main:

```yaml
    target-branch: dev
```

This routes version-update PRs to dev. GitHub reads Dependabot configuration
from the default branch, so keep it on main. Security updates have separate
default-branch behavior; target-branch is not a way to reroute those. No Python
Dependabot entry is currently configured. See [Dependabot target-branch](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#target-branch).

## 7. Develop one feature per worktree

From BotoToolkit:

```powershell
git fetch origin --prune
git worktree add -b feature/improve-help ../BotoToolkit-feature-help origin/dev
cd ../BotoToolkit-feature-help
```

Run step 5, make the change, update meaningful tests/docs, and run step 8. For
Codex tasks use a branch such as codex/improve-help instead. Give each agent or
developer its own branch and worktree. Shared Git configuration and refs still
need coordination; worktrees are not separate remote repositories.

Stage explicit paths and inspect the staged patch before committing:

```powershell
git status --short
git --no-pager diff
# Stage the specific files you reviewed with git add.
git --no-pager diff --cached
git commit -m "feat: improve command help"
git push -u origin feature/improve-help
```

Create a GitHub PR with **base dev**, **compare feature/improve-help**. Include
the behavior change and actual test results. If dev advances, with a clean or
committed feature checkout:

```powershell
git fetch origin
git merge origin/dev
```

Resolve conflicts, stage resolutions, finish the merge, rerun checks, and push.
Use git merge --abort if abandoning an in-progress merge. Do not regenerate
uv.lock merely to hide a conflict; reconcile dependency intent and validate it.
Merge the PR only when reviews and checks are satisfied.

## 8. Validate before publishing and merging

Run from the checkout containing the proposed change, using the current pinned
CI toolchain. Stop at the first failing check and fix its cause.

```powershell
uv sync --locked
uv lock --check
uv run --locked pytest -q --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/check_distribution.py
uv run --locked python scripts/security_check.py --history --require-history
git diff --check
```

The scanner installation in step 5 is required for real scanner tests. Check
the pytest summary for unexpected skips. These checks cover mocked application
behavior, formatting, locked dependencies, clean package installation, and
publishable content/history. GitHub must also pass the actual Linux and Windows
jobs. A successful local Windows run does not establish Linux success.

## 9. Promote a release and synchronize the branches

Ensure dev contains only changes intended for this release. Prepare version
metadata and release notes through a feature PR into dev; update uv.lock when
project metadata requires it. Re-run the package check. Avoid unrelated dev
merges while the promotion is being reviewed.

1. Open a PR with base main and compare dev. Review the entire release diff.
2. Wait for the five required checks and applicable review. Use a merge commit;
   never squash this long-lived branch. Do not select Delete branch afterward.
3. Update the main worktree and confirm the merged commit's hosted CI passed:

   ```powershell
   cd ../BotoToolkit
   git pull --ff-only origin main
   git --no-pager log -1 --oneline
   git tag --list
   ```

4. Select the next unused version matching pyproject.toml and the release notes.
   The following uses a placeholder; substitute the reviewed version first:

   ```powershell
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

   Tag the tested main commit, never an unmerged feature. Do not move or overwrite
   an existing release tag. A tag is not package publication or AWS deployment;
   the current workflows only validate it. Create a GitHub Release manually if
   release notes are desired, without uploading private reports.

5. Synchronize main back through a temporary branch based on the latest dev.
   From BotoToolkit:

   ```powershell
   git fetch origin
   git worktree add -b codex/sync-main-to-dev ../BotoToolkit-sync origin/dev
   cd ../BotoToolkit-sync
   ```

   Initialize this checkout using step 5, then:

   ```powershell
   git merge origin/main
   ```

   Resolve any conflicts, run step 8, and push:

   ```powershell
   git push -u origin codex/sync-main-to-dev
   ```

   Open a PR with base dev and compare codex/sync-main-to-dev. Merge with a
   merge commit after checks/review. This source branch already includes dev,
   satisfying the current-base requirement without changing main. A direct
   main-to-dev PR can be blocked when dev has advanced; do not use GitHub's
   Update branch button to merge unreleased dev changes into main. If dev moves,
   merge origin/dev into the temporary synchronization branch and retest.
   Return to BotoToolkit and update the dev worktree:

   ```powershell
   cd ../BotoToolkit
   git -C ../BotoToolkit-dev pull --ff-only origin dev
   ```

   Retire the temporary synchronization worktree/branch using step 10 before
   reusing its example name for a later release.

If main and dev conflict, resolve in a temporary branch from origin/dev, merge
origin/main there, and PR that branch into dev. Then retry the dev to main
promotion. Avoid direct pushes to either protected branch and never force-reset
dev to main. Keeping the integration flow current prevents repeated promotion
conflicts. Main includes the reviewed release; dev may then resume new work.

## 10. Handle a hotfix and retire a finished worktree

For an urgent release fix, from BotoToolkit:

```powershell
git fetch origin
git worktree add -b hotfix/urgent-fix ../BotoToolkit-hotfix origin/main
```

Initialize, implement, and test there. PR hotfix/urgent-fix into main with a merge
commit, then use step 9's temporary synchronization branch to bring main into dev.
Publish a new patch tag only after the main commit
passes checks. The merge back to dev must retain the fix even if dev already has
unreleased changes. Retire the hotfix worktree using the same process as a feature.

For a feature already merged into dev, from BotoToolkit:

```powershell
git fetch origin --prune
git -C ../BotoToolkit-feature-help status --short
git -C ../BotoToolkit-feature-help status --short --ignored
git merge-base --is-ancestor feature/improve-help origin/dev
```

The ancestry check must exit 0 (inspect $LASTEXITCODE in PowerShell). Review
ignored files too: an apparently clean
checkout can still contain private reports, plans, or an audit trail. Move any
needed private material to appropriate private storage before removal; do not
relocate consumed deployment state in a way that enables replay.

After confirming the exact path and that the checkout has nothing to retain:

```powershell
git worktree remove ../BotoToolkit-feature-help
git branch -d feature/improve-help
git push origin --delete feature/improve-help
```

Delete the remote branch only if it still exists and no other developer needs
it. Git may refuse removal or branch deletion; inspect the reason instead of
adding --force or -D. If local dev is stale, update its worktree and retry the
safe deletion. Use Git's worktree commands instead of deleting folders manually.
Keep the main and dev worktrees permanently.

## Adoption completion checklist

- Pending audit/CI work is committed, reviewed, and present on main and dev.
- Main is the default; feature PRs explicitly target dev.
- Both branch rulesets enforce the five checks; reviewer availability is resolved.
- Merge commits are used for promotion/synchronization; dev cannot be deleted.
- A harmless feature has completed feature -> dev -> main -> dev on GitHub.
- Separate environments, hooks, scanner checks, and package tests work in a
  linked checkout; no private output was copied into source history.
- Dependabot's version updates target dev after its configuration reaches main.
- A sample merged feature worktree can be removed without losing local material.

The directory structure needs no application refactor for this model. Optional
follow-ups are a PR template reminding authors of the correct base, a helper
that bootstraps each checkout, and a branch-routing check. Implement those only
after the manual workflow has been exercised successfully.
