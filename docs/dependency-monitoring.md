# Python dependency monitoring

`python-vulnerabilities` checks all registry package versions in `uv.lock`, including
development dependencies and platform alternatives, against the public OSV API.
It runs on every push, pull request, merge queue request, manual dispatch, and
daily at 07:23 UTC on the default branch. Scheduled runs begin after the workflow
reaches main; dev is checked when it receives pushes and PRs. GitHub may delay
scheduled jobs. No AWS credentials, new package dependency, or package installation
is needed by the auditor.

Run locally from the repository root:

```powershell
uv run --locked python scripts/dependency_audit.py
```

This command needs internet access, separately from the offline regression suite.
Only public PyPI package names and versions are sent. The local project is excluded;
private registries, Git/URL dependencies, and other local projects stop the audit
before any query. No profile, resource ID, repository name, or file content is sent.
The runner uses Python 3.12+ standard-library code. The request has a 20-second
socket timeout, a 2 MiB response limit, and no redirects; CI has a five-minute limit.

Exit codes: 0 complete with no matches, 1 known advisory matches, 2 incomplete or
invalid audit. Missing/malformed results, service errors, unsupported sources, and
paginated results cannot produce a passing check. Pagination currently requires
manual investigation rather than silently ignoring additional matches. There are
no ignore-advisory or automatic-fix switches. Reported matches need review; a clean
scan is not a guarantee against malicious packages or undisclosed vulnerabilities.
Python, uv, Gitleaks, Actions, OS components, and build requirements not recorded in
uv.lock are outside this check.

Dependabot's native `uv` ecosystem opens weekly version-update PRs into dev.
Existing quarterly GitHub Actions updates remain unchanged. Review changelogs,
rerun tests and advisory checks, and merge through the normal dev/main process.
No update is automatically merged. uv and Gitleaks tool pins still require separate
maintenance. Use GitHub notification settings to receive failed scheduled-run alerts.

## GitHub configuration after review

1. Require the exact `python-vulnerabilities` check for main and dev alongside the
   existing five checks, once its successful PR run is visible.
2. Verify dependency graph, Dependabot alerts, and security updates are enabled
   where supported. The repository file alone does not enable these controls.
3. Promote the workflow to main to activate the daily schedule and Dependabot's
   default-branch configuration. Confirm a scheduled or manual run succeeds.
4. Require independent review for workflow, auditor, lockfile, and policy changes;
   a PR must not weaken its own checks. Existing CODEOWNERS assignment is retained.

References: [OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/),
[uv and Dependabot](https://docs.astral.sh/uv/guides/integration/dependabot/).
