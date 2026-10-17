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
- Keep milestone status in ROADMAP.md. Record all implemented changes and exact
  verification steps/results in IMPLEMENTATION_REPORT.md for this request.

- Documentation uses ACCOUNT_ID, APP_ID, API_ID, and OWNER/REPOSITORY placeholders.
  Test identities must be synthetic. Never copy live results into public docs.
- Before publishing run scripts/security_check.py --history. Keep security
  workflow, scanner rules, hooks and installer under review; never blanket-exclude
  documentation or tests from secret scanning.
