
# Engineering Principles

## Core Philosophy
- Prioritize simplicity, readability, correctness, and maintainability.
- Build only what the current requirements justify (YAGNI).
- Prefer boring, proven solutions over clever abstractions.
- Follow KISS and DRY, but never sacrifice clarity to eliminate minor duplication.
- Choose the smallest coherent change that solves the problem.
- Do not build for hypothetical future requirements.

## Architecture
- Prefer a simple monolith unless multiple services are genuinely necessary.
- Use the existing project structure, dependencies, and conventions.
- Do not introduce design patterns, factories, service layers, interfaces, or generic frameworks without a concrete need.
- Do not create abstractions for a single implementation or speculative reuse.
- Keep functions and modules focused, with descriptive names.
- Avoid excessive indirection, wrappers, and configuration.
- Do not add dependencies, infrastructure, or new services without a clear justification and approval.

## Scope Control
- Implement only the explicitly requested feature or fix.
- Do not expand the scope with speculative improvements.
- Do not refactor unrelated code while implementing a feature.
- Prefer modifying existing files rather than creating new ones.
- If a change significantly increases complexity, stop and explain the simpler alternatives.
- For straightforward tasks, implement directly without creating a planning document.

## Testing
- Write tests based on behavior and risk, not coverage targets or test counts.
- Prefer a small number of meaningful tests covering critical paths, edge cases, and regressions.
- Reuse existing tests whenever possible.
- Avoid duplicate tests, trivial implementation-mirroring tests, and excessive mocking.
- Do not introduce parametrized permutations without a distinct failure risk.
- For small changes, typically add 0–3 focused tests; exceed this when justified by risk or behavior.
- Never remove valuable regression or security tests merely to reduce the test count.
- Run the relevant checks without repeatedly running the entire suite unnecessarily.

## Documentation
- README.md is the primary documentation entry point.
- Keep setup, usage, and essential troubleshooting instructions concise and practical.
- Do not generate implementation reports, summaries, walkthroughs, roadmaps, ADRs, or additional Markdown files unless explicitly requested or genuinely required.
- Update existing documentation instead of creating overlapping documents.
- Prefer examples and commands over lengthy theoretical explanations.
- Avoid repeating information already obvious from the source code.

## Delivery
- Keep each change small and independently reviewable.
- Preserve existing behavior unless a change is explicitly requested.
- Avoid unrelated formatting or directory restructuring.
- Report briefly: what changed, why, and how it was verified.
- Mention important risks or limitations without generating a separate report.
- Stop when the requested work is complete; do not automatically start additional improvements.

## Complexity Check
Before finishing, ask:
1. Is there a simpler implementation?
2. Did I create files, abstractions, tests, or dependencies that are unnecessary?
3. Can a developer unfamiliar with the project follow the code easily?
4. Did I solve the requested problem without expanding scope?

If complexity increased without clear value, simplify before finishing.


# Project conventions

- The user authorized finishing core roadmap milestones 1–7. Reporting and
  deploy-plan are read-only. The deploy command is the sole opt-in AWS write path.
- Always execute toolkit commands with local AWS profile `brewmaster`.
- Use the local AWS profile mapping. Never use an unrelated connector identity
  as a substitute for this profile.
- Obtain expected account/region from the user or private local settings. Keep
  all three CLI options explicit; never persist live identifiers in tracked files.
- Ask for unresolved account/region placeholders before any live AWS calls.
- Create one explicit Boto3 session and derive all clients from it. Verify
  `GetCallerIdentity` against the expected account before inventory calls.
- Stop on authentication failure or account mismatch. Never fall back to
  default credentials or another profile. Never request access keys or tokens.
- During implementation/live verification, do not execute live deployments,
  rotate credentials, delete resources, or change infrastructure. Mock StartJob.
- deploy requires a valid reviewed, unexpired RETRY plan, exact plan-ID
  confirmation, fresh preflight, production confirmation where applicable, and
  a persisted local audit claim. Use a separate StartJob permission policy.
- Never automatically retry StartJob: no idempotency token is available.
  Unknown outcomes consume the local plan; inspect AWS before further action.
- Never log credentials, environment-variable values, raw AWS responses,
  service error messages, signed source URLs, or basic-auth credentials.
- JSON stdout must contain only the report. Send identity and diagnostics
  to stderr. Export only fields declared in `models.py`.
- Use Python >=3.15, uv and its lockfile, src layout, Typer, Rich, and Boto3.
- Keep AWS access in `aws.py`, collection in `inventory.py`, presentation in
  `presentation.py`, and CLI validation/exit codes in `cli.py`. Investigation
  logic belongs in `investigation.py`; bounded log retrieval and signature
  recognition belong in `logs.py`.
- Configuration comparison belongs in `comparison.py`. Raw values may be
  compared in memory only. Export key names, presence, origin, and comparison
  relations; never values, hashes, lengths, build specs, or basic-auth contents.
- Apply app-to-branch inheritance only for environment variables. Compare other
  allowlisted branch fields as stored; show app-wide settings as shared context.
- Log inspection is opt-in. Export fixed error categories and line numbers only;
  never raw log text, free-form status reasons, or any signed URL. Enforce
  byte/time/count limits and reject redirects or non-allowlisted HTTPS hosts.
- Keep functions small and typed. Prefer dataclasses over extra dependencies.
- Preserve the original `bototoolkit` package and unrelated workspace files.
- Use SDK paginators, bounded retries, and timeouts. Do not assume job ordering.
- Mock AWS using Stubber and literal fake credentials; tests must not use
  real credentials or network access. Assert identity blocks service calls.
- Before finishing, run `uv run pytest`, `uv run ruff check .`, and
  `uv run ruff format --check .`. Fix failures and report checks actually run.
- Update ROADMAP.md only when milestone scope or status changes.
- Report changes and verification results in chat. Do not create or append
  implementation reports unless explicitly requested.

- Documentation uses ACCOUNT_ID, APP_ID, API_ID, and OWNER/REPOSITORY placeholders.
  Test identities must be synthetic. Never copy live results into public docs.
- Before publishing run scripts/security_check.py --history. Keep security
  workflow, scanner rules, hooks and installer under review; never blanket-exclude
  documentation or tests from secret scanning.
