# Diagnose a development environment

`doctor` helps a new contributor check setup before running AWS commands.
It reports `pass`, `warn`, `fail`, or `skip` for each check and suggests a next
step. It does not repair the environment or change AWS resources.

## From a source clone

Install the locked environment first, then check it:

```powershell
uv sync --locked
uv run --offline --no-sync amplify-ops doctor --project .
uv run --offline --no-sync amplify-ops doctor --project . --format json
```

The `--offline --no-sync` flags belong to uv. They keep the launcher from
synchronizing dependencies or contacting a registry before doctor starts.
`--project .` belongs to doctor. It explicitly selects the source checkout;
doctor does not infer a repository from the current working directory.

## From an installed tool

```powershell
amplify-ops doctor
amplify-ops doctor --format json
```

Repository and uv checks are skipped unless `--project` is supplied. A standalone
tool installation does not require a checkout or uv on PATH merely to run doctor.
The runtime still needs Python and its installed package dependencies to start.
If the CLI cannot import, repair its installation before running diagnostics.

## Check local AWS settings without signing in

Replace PROFILE_NAME with your local profile name. The three AWS options go before
the command. Resolve ACCOUNT_ID locally using an independently trusted account
mapping. Do not commit the
resolved value or copy an STS response just to make the comparison pass.

```powershell
uv run --offline --no-sync amplify-ops --profile PROFILE_NAME --expected-account ACCOUNT_ID --region us-east-1 doctor
```

This reads bounded local AWS INI configuration only to determine whether the
selected profile exists. It honors AWS_CONFIG_FILE and
AWS_SHARED_CREDENTIALS_FILE, including their standard home-directory defaults.
It does not create a Boto3 session, resolve credentials, run credential_process,
refresh SSO, contact metadata services, or verify that credentials are valid.
Missing selections are warnings. An explicitly selected missing profile or
unreadable/malformed configuration is a failed check. An absent optional default
configuration file is allowed; an explicitly configured missing file fails.

## Opt in to identity verification

```powershell
uv run --offline --no-sync amplify-ops --profile PROFILE_NAME --expected-account ACCOUNT_ID --region us-east-1 doctor --online
```

Online mode requires all three AWS options and exactly one region. After local
checks pass, the existing AWS access layer creates one explicit-profile Boto3
session and calls STS GetCallerIdentity with bounded SDK retries and timeouts.
The selected profile's normal credential provider can run or refresh credentials
in this mode. There is no fallback to another profile. Account mismatch or an
authentication/connectivity failure fails the identity check. A local failure
skips AWS verification and marks the report incomplete.

No Amplify, AppSync, Cost Explorer, GitHub, inventory, or deployment calls are
made. A successful identity check confirms the caller's account only; it does
not prove permission to use any service. Online tests use synthetic credentials
and Stubber; live verification is a separate operator action.

## Checks and limits

| Check | What it establishes |
| --- | --- |
| Python | The running interpreter is Python 3.15 or newer. |
| Required packages | Metadata for amplify-ops, boto3, Typer, and Rich is available. This alone does not prove version compatibility. |
| AWS profile | The selected profile exists in bounded local INI configuration. Values are never exported. |
| Account and regions | Explicit selections have valid syntax. Offline checks cannot establish account ownership or regional service availability. |
| Project files | The explicitly selected directory contains pyproject.toml and uv.lock. |
| uv | An executable is available on PATH for project validation. |
| Lockfile | `uv lock --check` passes offline, with builds, downloads, and keyring credential lookup disabled. |
| Dependencies | `uv pip check` passes for the interpreter running doctor. It does not prove exact equality to every lockfile version. |
| Identity | Skipped by default; online mode verifies the expected account using STS. |

Project commands each have a 30-second timeout, discard subprocess output, and
never run sync, install, or lockfile updates. They require a trusted uv executable
and trusted source checkout. uv may use temporary files while validating; doctor
does not promise zero filesystem activity. Offline lock validation may fail if
required metadata is unavailable, so inspect uv locally when its generic finding
is insufficient. Doctor does not check Git hooks, GitHub login, scanner setup,
CI, deployment readiness, or full SDK/service compatibility.

## Output and automation

```powershell
uv run --offline --no-sync amplify-ops doctor --project . --format json --output .amplify-ops/doctor.json
```

Create the ignored destination directory first. The output file is created
exclusively: an existing file is never overwritten. JSON stdout contains only
the report; file-write diagnostics go to stderr. Reports contain schema version
1, report type `doctor`, a `complete` boolean, and a list of checks containing
only `name`, `status`, `message`, and `next_step`.

Doctor reports use fixed diagnostic text. They omit account IDs, caller ARNs,
selected profile names, paths, credentials, environment-variable values, raw
AWS responses, raw subprocess output, and exception messages. Other toolkit
commands retain their documented report schemas; this privacy guarantee is
specific to doctor output.

| Exit code | Meaning |
| --- | --- |
| 0 | No failed checks. Warnings and deliberate skips can still be present. |
| 1 | At least one check failed, or the requested report file could not be written. |
| 2 | Invalid CLI usage, including unresolved placeholders or missing online options. |

`complete` indicates whether requested checks were attempted, not whether all
passed. An attempted STS check that fails can have `complete: true`; use the
exit code and check statuses to decide success. Offline mode deliberately skips
identity and can succeed without AWS settings. Use `--online` when identity is
a required part of your validation.
