# Python dependency monitoring

`python-vulnerabilities` checks all registry package versions in `uv.lock`, including
development dependencies and platform alternatives, against the public OSV API.
It runs on every pull request, pushes to main, merge queue requests, manual
dispatch, and weekly on Monday at 07:23 UTC on the default branch. Schedule changes
take effect after promotion to main; dev is checked through PRs. GitHub may delay
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

Dependabot version updates are removed; dependency updates are manual. Monthly or
before a release, review Python packages and action/tool pins in a feature branch,
inspect changelogs, and run tests, package checks, and the advisory checker before
opening a PR into dev. Keep changes small enough to review and promote through
the normal dev/main process. No update is automatically merged. uv and Gitleaks
tool pins still require separate maintenance. The OSV workflow does not open PRs.
Use GitHub notification settings to receive failed scheduled-run alerts.

## GitHub configuration after review

1. Require the exact `python-vulnerabilities` check for main and dev alongside the
   existing five checks, once its successful PR run is visible.
2. Dependabot alerts and automatic security updates remain disabled by the current
   repository policy. OSV monitoring is independent of those settings.
3. Confirm the default branch contains the weekly OSV workflow and no Dependabot
   version-update configuration. Verify a scheduled or manual OSV run succeeds.
4. Require independent review for workflow, auditor, lockfile, and policy changes;
   a PR must not weaken its own checks. Existing CODEOWNERS assignment is retained.

Reference: [OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/).
