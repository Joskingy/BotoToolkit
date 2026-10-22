# Deep code and test audit

Audit date: October 17, 2026, America/Mexico_City. This work used parallel audits
for legacy/coverage, SDK collectors/logs, and deployment/security behavior, plus
an independent review of the financial arithmetic and plan validation changes.
All credentials, repository fixtures, and operational values in tests are
synthetic. No AWS calls, infrastructure changes, remote pushes, or releases were
performed during this audit.

## Obsolescence decisions

No production code or tests were removed. Unused code was a hypothesis to
prove, not a deletion target.

- `src/bototoolkit/__init__.py` remains a console entry point in pyproject.toml,
  part of the uv build module list, documented as supported, and present in the
  built wheel. Its console smoke check passed. Removing it would break a shipped
  interface. The original empty whoami.py scaffold has no references, but the
  project explicitly preserves the original package; it has no executable code
  or obsolete tests to remove.
- Imports and callers connect the AWS readers, inventory helpers, log helpers,
  comparison helpers, typed rows, and deployment paths to active commands.
  Baseline function-call tracing exercised all amplify_ops function bodies
  except the generic table renderer. That renderer is an active command path,
  not dead code; new real CLI tests now exercise it.
- The scanner main function and installer are invoked by Git hooks and CI, even
  though the baseline pytest suite did not call all of them directly. New
  installer tests cover checksum rejection and extraction without a download.
- Similar authentication, partial-result, and redaction tests exercise separate
  command contracts. They were retained. No xfail or assertion removal was used
  to make failures disappear. The scanner fixture has an explicit skip when its
  binary is absent; the pinned binary was installed for this audit.

Raw dynamic tracing is stored only in ignored local audit artifacts. A numeric
coverage percentage is not reported: concurrent source changes shifted trace
line numbers, and lazy annotation code complicates Python 3.15 line accounting.
The call evidence was used to identify concrete missing behavior tests, not to
declare unvisited lines obsolete.

## Proven defects and changes

| Area | Evidence before the fix | Result and regression coverage |
| --- | --- | --- |
| Log completeness | A real stdlib HTTPResponse with a declared length larger than its body silently reached EOF; downloader returned complete and CLI exited 0. | LogIncompleteBody makes the investigation partial. Known/unknown complete lengths still succeed; partial CLI evidence retains job metadata and withholds raw body/URLs. |
| AppSync key identity | Missing/empty IDs with future expiry were labeled valid and fingerprinted as an empty string. New tests failed twice before the fix. | Missing identity now produces unknown key reference/expiry/status and incomplete API/report metadata. Valid keys retain fingerprints. |
| Cost arithmetic | A paginated finite amount with more than 28 significant digits lost supplied decimal places under the default context. | Addition and tag remainder use sufficient local precision, preserving all supplied places and keeping currencies separate. An independent 2,000-case signed decimal comparison against exact rational arithmetic passed under precision 1 and rounding traps. |
| Invalid cost metadata | Nonfinite or malformed amount strings caused exceptions or unusable totals. | The affected query is explicitly incomplete, totals stay unknown, and a fixed InvalidCostMetadata code is emitted without echoing the amount. |
| Production protection | An old feature branch mapped as app production, but with DEVELOPMENT stage, became a review candidate when absent on GitHub. | The app productionBranch mapping protects it alongside conventional names/stages. |
| Reviewed plan validation | A valid digest with list-valued app_id caused an uncaught TypeError; invalid source fields reached authentication. Boolean schema_version and string complete values were accepted. Deep JSON below the byte cap raised RecursionError. | Scalar/envelope types, supported stage/action, target formats, metadata lengths, timezone-aware timestamps, expiry, and digest are validated before authentication. Malformed/deep input receives a safe refusal. Existing preflight, production confirmation, and write/audit gates remain enforced. |
| Historical private artifacts | Committing then deleting a private JSON report without a known secret signature passed history scanning. | Every distinct reachable tree is checked for private paths, unsupported modes, and oversized files. Deleted artifacts and reused blobs moved into private paths fail. require-history now implies scanning. |

The SDK's installed model independently confirmed supported stage enums, numeric
job IDs, and the commit-ID length bound used in strict plan validation. No new
runtime dependency or report field was added.

## Test-integrity improvements

- Retained the old invalid-plan CLI case under an accurate name; its previous
  name claimed expiry coverage even though it supplied only `{}`. Added an
  authentic but expired plan that proves no new AWS session starts.
- Added default-table CLI cases for complete, partial, and empty AppSync
  reports, plus credential exclusion in console and exported JSON.
- Added an end-to-end CLI adapter case for a reviewed retry using actual
  Stubber preflight/submission responses and a local temporary audit file.
  StartJob remains mocked; its SDK attempt limit is still one.
- Added mocked ZIP/TAR installer cases for verification, existing-binary
  preservation, path-traversal entries, unsupported platforms, download errors,
  and a nonregular executable entry. They make no network requests.
- Added real scanner/Git integration cases for clean history, deleted JSON/env
  and private notes, unchanged blobs moved to private paths, historical links,
  submodules, oversized files, and missing history. Tests use disposable repos.

## Step-by-step verification

1. Recorded a clean baseline and inspected all source/test files, entry points,
   package configuration, imports/callers, skips, and workflow/hook references.
2. Ran the unmodified suite: **137 passed**. Ruff lint/format passed. A separate
   baseline call trace also completed successfully with 137 tests.
3. Demonstrated each changed behavior with an offline reproduction or failing
   regression before applying its fix. New reporting cases initially failed on
   missing identity and precision loss; malformed plan cases failed on unsafe
   errors or unexpected authentication; nested JSON failed on RecursionError.
4. Ran targeted collector/CLI, reporting, deployment, scanner, and installer
   suites as each owned change landed. All final targeted runs passed. Initial
   red runs are defect evidence, not counted as successful checks.
5. Ran the combined final suite, lint, formatting, lockfile, source/wheel build,
   CLI smoke, and sensitive-information checks. Final results are recorded
   below.

| Final check | Executed result |
| --- | --- |
| Full pytest suite | **185 passed in 91.27 seconds**, no skips; 48 additional cases over the 137-case baseline |
| Ruff lint | All checks passed |
| Ruff formatting | 37 files already formatted |
| Offline lockfile validation | Existing 21-package environment resolved successfully |
| Offline wheel/source build | Both artifacts built successfully |
| Archive inspection | Wheel: 23 entries; source archive: 24 entries; both packages present, both console entries in wheel, private/cache/workspace artifacts excluded |
| Console smoke checks | amplify-ops help displayed all commands; bototoolkit printed its preserved greeting |
| Real pinned Gitleaks plus historical policy | Passed on working files and actual reachable repository history, with scanner canaries |
| git diff --check | Passed; line-ending normalization warnings do not indicate whitespace errors |

The build warned that the local uv cache sits under the source directory.
Inspection of the actual wheel and source archive confirmed that cache files
were excluded; the warning was not treated as evidence of a packaging leak.

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv/cache'
$env:TEMP = Join-Path $PWD '.uv/test-temp'
$env:TMP = $env:TEMP
uv run --locked pytest -q --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check --offline
uv build --offline --out-dir .uv/audit/final-dist
uv run --locked amplify-ops --help
uv run --locked bototoolkit
uv run --locked python scripts/security_check.py --history --require-history
git diff --check
```

## Remaining limits

- Compatibility removal is not justified; the original console interface is
  still packaged and documented. Retiring it needs an explicit compatibility
  decision rather than an unused-line heuristic.
- This is offline verification against the installed SDK and mocked services.
  No new live AWS/GitHub behavior or remote CI enforcement is claimed.
- The installed interpreter is Python 3.15.0rc2. Repeat on the team's chosen
  stable interpreter before standardizing a shared environment. Security scripts
  retain a Python 3.12 syntax check, not execution on every supported OS/runtime.
- Windows x64 and Linux x64 archives are tested with synthetic data; the real
  scanner runs on the current Windows host. An actual Linux runner is outside
  this audit. Tests still explicitly skip scanner integration if its binary is
  missing, so contributors should install it; final audit results include it.
- No percentage target substitutes for meaningful assertions. History checks
  scale with distinct snapshots and fail on tool timeout; they do not silently
  omit disallowed historical paths to improve speed.

No blocker remains for this local audit. Remote checks, stable-runtime checks,
and any later compatibility deprecation are separate follow-up work; none were
silently presented as verified or completed here.
