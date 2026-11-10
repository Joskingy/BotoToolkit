# amplify-ops scope and status

Core milestones 1–7 are implemented. Reporting and `deploy-plan` read AWS;
`deploy` is the sole opt-in write path and supports completed-job RETRY only.

| Milestone | Implemented behavior |
| --- | --- |
| 1. Inventory | Apps, branches, and latest job summaries across explicit regions. |
| 2. Investigation | Latest failed or selected job, step evidence, opt-in bounded log signatures. |
| 3. Comparison | Redacted branch configuration and environment inheritance. |
| 4. AppSync keys | Expiry/status and opaque fingerprints; no raw keys or rotation. |
| 5. Costs | Exact account/service totals and optional tag estimates; no invented per-resource allocation. |
| 6. Stale environments | Conservative AWS/GitHub evidence; no automatic cleanup. |
| 7. Controlled retry | Expiring reviewed plans, exact confirmation, fresh preflight, persisted local claim, one submission attempt. |

Local `doctor` diagnostics and optional STS-only verification are implemented.
The optional Textual TUI is an offline synthetic demo; see [the TUI guide](docs/tui.md).
The `dev.ps1` helper supports worktree setup, checks, feature PRs, and promotion.

## Operating limits

- All AWS commands require an explicit local profile, independently expected
  account, and selected region. This project uses `brewmaster`.
- Unread or incomplete evidence is unknown, never proof of absence or no cost.
- Reports withhold secrets and raw logs, but account/resource metadata remains
  private. See [security guidance](docs/security.md).
- Local audit claims are not distributed idempotency. Use one controlled operator
  and a stable private audit directory; inspect AWS after uncertain submissions.
- Tests mock AWS, including StartJob. Live writes are not part of implementation
  verification. Hosted checks and repository enforcement require separate review.

Live TUI access, continuous monitoring, broader backend discovery, CI AWS
authentication, shared deployment coordination, and additional write actions are
outside the current implementation. They require demonstrated need and explicit
approval before development.

Use [README](README.md) for setup and commands, [additional command details](docs/remaining-commands.md)
for costs/stale/retry semantics and IAM, and [CONTRIBUTING](CONTRIBUTING.md) for development.
Historical audits and implementation records remain available in Git history.
