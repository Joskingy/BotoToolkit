# Project audit and improvement plan

Reviewed 5 November 2026. Package version: 0.1.0.

## Remediation prepared 6 November 2026

The security-hardening PR implements A1–A4: text-only publication checks for
working/index/history content, case-insensitive private paths, OSV monitoring and
weekly uv updates, and bounded GitHub subprocess output. A1 uses rejection of
binary files rather than claiming to scan Word archives. Historical text diffs
also prevent Git attributes from hiding text secrets. Regression evidence and
exact checks are in the implementation report. These changes await review/merge.

A5 worktree cleanup remains separate: original uncommitted files are preserved
unchanged. IAM review, hosted rule enforcement, broader coverage measurement,
doctor, and other optional features remain follow-up work. The original findings
and verification below describe the audit baseline, not the remediation result.

## Assessment and scope

The toolkit has a sound foundation for supervised AWS reporting: explicit account
verification, a separated AWS boundary, allowlisted output models, conservative
partial results, and mocked tests. Deployment retries have meaningful safeguards
but still depend on operator permissions and local state. Prioritize publication
controls and onboarding before adding more AWS writes.

No credential exposure was detected in the publishable checkout or reachable Git
history by the configured scanner. This is not evidence that the AWS account has
never been compromised. CloudTrail, IAM effective permissions, security alerts,
ignored private files, and previously deleted remote refs were not investigated.

The main worktree is at `c86b0c6`, 11 commits behind the locally recorded
`origin/main` at `c0edb5d`. The application source and lockfile match that newer
revision. The newer developer helper, its tests, and CI were also reviewed from
the dev worktree at `5a0fc1e`; its only content difference from recorded main is
the implementation report. No branches were updated. Four existing modified files
were preserved; this request adds documentation and appends to the existing reports.

GitHub metadata confirms a public repository with main as default and merge
commits enabled, with squash/rebase disabled. Current ruleset enforcement, required
reviews, secret alerts, and push protection were not verified by this audit.

## Findings

| ID | Priority | Evidence and consequence | Recommended action |
| --- | --- | --- | --- |
| A1 | Medium | `scripts/security_check.py:124` invokes Gitleaks without archive scanning. A synthetic account marker is detected in plain text but missed inside a valid compressed Word document. The path policy permits `.docx`. Binary documentation can pass without its text being examined. | Block unreviewed binary/archive publication, or implement bounded OOXML extraction and scanning of text, properties, comments, and relationships. Include history, staged content, malformed files, and limits on expanded content. Do not assume adding an archive flag alone covers Git binary history. |
| A2 | Medium | `scripts/security_check.py:38` compares private path components case-sensitively. The probe rejects `private/note.md` but accepts `Private/note.md`. The suffix policy still rejects JSON; this finding concerns other files and private directories on Windows. | Normalize case for the private-path policy and distribution checks. Test mixed-case paths in working files, index, and deleted history. Content scanning still applies, but does not identify arbitrary private notes. |
| A3 | Medium | `.github/dependabot.yml` updates only GitHub Actions. CI has no Python advisory/dependency-review job. The lockfile makes installs reproducible but does not detect newly disclosed vulnerabilities. | Add Python dependency updates and an advisory check against the locked dependencies on PRs and a schedule. Use reviewed pins and fail visibly if advisory lookup is unavailable. |
| A4 | Low | `src/amplify_ops/github.py:45` checks its 2 MiB stdout limit after `subprocess.run(capture_output=True)` has buffered output. There is a 20-second timeout, but this is not a hard memory limit. | Bound stdout and stderr during capture, terminate at the limit, and test oversized streams. Normal projected GitHub responses make this a hardening issue, not a demonstrated remote exploit. |
| A5 | Low | Main lacks the already-merged developer helper; security and roadmap documents retain historical statements that remote setup is pending. The same package version spans different contributor workflows. | Preserve pending edits, synchronize worktrees through the existing branch process, and distinguish historical records from current setup instructions. Add a release changelog and version diagnostic. |

A1 and A2 were reproduced without real identifiers or credentials. No production
code or security policy was changed as part of this audit; fixes require their own
reviewable change and regression tests. The Word deliverable is kept in ignored
`reports/`, and its extracted text and metadata are scanned separately.

## Controls worth preserving

- `AwsAccess.connect` creates one explicitly selected profile session and blocks
  inventory when STS fails or the account differs. Configured service endpoint
  overrides are ignored. SDK reads have bounded retries and timeouts.
- Reports use dataclasses; comparison values, API keys, raw logs, signed URLs,
  service messages, and commit messages are withheld. Report metadata still
  identifies the account and resources and must remain private.
- Log inspection is opt-in, HTTPS-only, host-allowlisted, redirect-rejecting, and
  bounded by bytes, count, findings, and time. Incomplete bodies produce errors.
- Retry plans expire after 15 minutes, require exact confirmation and fresh
  preflight, and claim local audit state before the single StartJob attempt.
  Production targets require additional confirmation. There is no automatic retry.
- Tests use synthetic credentials and Stubber, block normal SDK/socket network
  paths, and cover identity denial, redaction, pagination, unknown evidence,
  replay refusal, and uncertain submission. No code or tests were proven obsolete.
- CI uses SHA-pinned actions, read-only token permissions, no persisted checkout
  credentials, no AWS secrets, Linux/Windows tests, and package-install checks.
  Scanner canaries, full-index hooks, and reachable-history checks are valuable.

## Important operating limits

IAM is the real authorization boundary. A prior account review reported broad
administrator access; that is historical context, not a current permissions result.
Revalidate it separately, then use temporary credentials with a narrowly scoped
read role and a separate approved retry role. Do not grant StartJob for reporting.
AWS recommends temporary credentials, MFA, and least privilege.
[AWS IAM guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

Local deployment claims are relative to the selected audit directory. Another
worktree, directory, or machine can have a different claim store. The plan checksum
detects modification relative to the confirmed ID; it is not an approval signature.
Fresh preflight cannot make AWS reads and StartJob atomic. Use one controlled
operator and stable private audit directory until shared coordination is designed.

A CI check runs after upload. Hooks are bypassable, and a PR can edit its own
scanner. Required checks, restricted bypass, and independent review of security
controls remain necessary; check plan availability for stronger required workflows
and server-side secret controls. Do not use `pull_request_target` to execute
untrusted code with privileged credentials.
[GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

## Prioritized delivery plan

These are proposals, not implemented features. Keep milestones 1–7 complete.

| Order | Work item | Done when |
| --- | --- | --- |
| 1 | Close publication gaps A1 and A2 | Plain text, valid OOXML, mixed-case private paths, staged-only leaks, and deleted historical fixtures cannot bypass policy. Malformed/oversized archives fail safely. No secret values appear in diagnostics. |
| 2 | Review IAM and GitHub enforcement | A read role can run intended reports but cannot StartJob; retry permissions are separately scoped. Fresh main/dev PR checks and independent review requirements are verified with synthetic fixtures. No account identifiers enter tracked docs. |
| 3 | Monitor dependencies and test quality | Locked runtime/dev packages receive advisory scans and update PRs. Establish measured branch coverage and review uncovered security paths before setting a threshold; add focused static typing/security analysis without blanket suppressions. |
| 4 | Add a safe doctor command | Offline mode checks tool versions, profile presence, scanner, hooks, and worktree state without printing credentials. Optional live mode uses the explicit identity gate and reports permission failures without claiming exhaustive effective IAM evaluation. Coordinate with the existing `feature/doctor` worktree. |
| 5 | Improve report usability | Add `--version`, schema documentation, synthetic sample reports, and opt-in public-share exports that remove account/resource identifiers. Test that shareable output cannot expose identifiers through nested errors or metadata. Keep full private reports separate. |
| 6 | Improve reliability at scale | Add total scan/page/time budgets, progress on stderr, bounded GitHub capture, and cancellation tests. Limits must produce partial/unknown results, never false success. |
| 7 | Harden deployment coordination | Add durable shared claims or explicitly prohibit concurrent execution; document recovery from unknown outcomes. Test concurrency and crash windows before expanding write features. |

Nice to have after these gates: a synthetic offline demo for new developers;
redacted configuration snapshots and drift comparison; a single app-health summary;
read-only backend discovery with explicit evidence; reviewed release artifacts with
checksums and installation instructions; configurable developer-helper branch and
check settings for reuse. Defer cleanup, key rotation, and automatic deployment.

Keep the existing `src/amplify_ops`, `src/bototoolkit`, `tests`, `scripts`, and
`docs` layout. Group future test files by feature only when navigation becomes
difficult. Keep generated guides/reports and audit scratch files outside the
publishable source. Avoid a broad folder rewrite while fixing security controls.

## Verification results

- Existing suite: **195 passed**, no skips, 107.59 seconds.
- Newer helper suite: **28 passed**, 20.64 seconds. Initial 28 setup errors came
  from Windows blocking Git's shell for disposable local pushes; an approved
  rerun outside that restriction passed. No assertion was removed or weakened.
- Ruff lint and formatting: passed; 42 files already formatted. Lockfile: passed.
- Configured working-tree and reachable-history security scan: passed, including
  scanner canaries. A passing result has the binary-content limits described above.
- Public OSV batch lookup: 20 registry packages from `uv.lock`, zero known advisory
  matches returned. This excludes the project itself, Python, uv, Gitleaks, actions,
  and operating-system components. It does not prove absence of vulnerabilities.
- Wheel/source clean-install checks and both entry-point smoke tests passed.
- All nine command help paths passed; nine PowerShell blocks parsed successfully.
  Extracted guide text, XML properties, and relationships passed secret scanning.
  Word render/visual verification remains blocked by the unavailable LibreOffice
  runtime; no page-count or visual-quality claim is made.
- No AWS requests, deployment, GitHub mutation, or project commit/push/merge was
  made. Git workflow tests operated only on disposable local repositories.

Exact commands, additional package/helper checks, guide verification, and remaining
limitations are recorded in `IMPLEMENTATION_REPORT.md`.

## Sources

- [Pinned Gitleaks documentation](https://github.com/gitleaks/gitleaks/tree/v8.24.3)
- [OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/)
- [GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/about-push-protection)
