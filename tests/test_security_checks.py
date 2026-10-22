"""Real scanner/git integration with synthetic canaries in disposable repositories."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("security_check", ROOT / "scripts/security_check.py")
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


@pytest.fixture
def scanner():
    path = (
        ROOT
        / ".uv/security-tools/gitleaks-8.24.3"
        / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
    )
    if not path.exists():
        pytest.skip("Install the pinned scanner to run real scanner integration tests")
    return path


@pytest.fixture
def repository(tmp_path):
    security.git(tmp_path, "init", "--quiet")
    security.git(tmp_path, "config", "user.name", "Synthetic Test")
    security.git(tmp_path, "config", "user.email", "test@example.invalid")
    security.git(tmp_path, "config", "core.hooksPath", ".no-hooks")
    return tmp_path


def test_real_canaries(scanner):
    security.self_test(scanner, ROOT / ".gitleaks.toml", ROOT / "scripts/security_report.tmpl")


def test_clean_placeholders_and_synthetic_fixtures(repository, scanner):
    (repository / "README.md").write_text("ACCOUNT_ID APP_ID API_ID OWNER/REPOSITORY")
    (repository / "tests").mkdir()
    (repository / "tests/fixture.py").write_text('ACCOUNT = "111122223333"')
    assert security.run(repository, scanner) == 0


@pytest.mark.parametrize("location", ["README.md", "tests/new_test.py"])
def test_account_ids_blocked_even_in_tests(repository, scanner, location, capsys):
    path = repository / location
    path.parent.mkdir(exist_ok=True)
    canary = "555566" + "667777"
    path.write_text(canary)
    assert security.run(repository, scanner) == 1
    output = capsys.readouterr().out
    assert "private-aws-account" in output and canary not in output


def test_synthetic_account_only_allowed_in_tests(repository, scanner):
    (repository / "README.md").write_text("111122223333")
    assert security.run(repository, scanner) == 1


def test_full_index_not_unstaged_worktree_is_scanned(repository, scanner):
    path = repository / "README.md"
    path.write_text("555566" + "667777")
    security.git(repository, "add", "README.md")
    path.write_text("ACCOUNT_ID")
    assert security.run(repository, scanner) == 0
    assert security.run(repository, scanner, staged=True) == 1


def test_deleted_historical_secret_is_still_blocked(repository, scanner, capsys):
    path = repository / "README.md"
    canary = "ghp_" + "AbCdEf0123456789" * 2 + "ABcd"
    path.write_text("token = " + canary)
    security.git(repository, "add", "README.md")
    security.git(repository, "commit", "--quiet", "-m", "Synthetic canary")
    path.write_text("Clean placeholder")
    security.git(repository, "add", "README.md")
    security.git(repository, "commit", "--quiet", "-m", "Remove canary")
    assert security.run(repository, scanner) == 0
    assert security.run(repository, scanner, history=True, require_history=True) == 1
    output = capsys.readouterr().out
    assert "github-pat" in output and canary not in output


def test_clean_history_passes_when_require_history_implies_scan(repository, scanner):
    path = repository / "README.md"
    path.write_text("ACCOUNT_ID APP_ID API_ID")
    security.git(repository, "add", "README.md")
    security.git(repository, "commit", "--quiet", "-m", "Clean placeholders")
    path.write_text("ACCOUNT_ID APP_ID API_ID OWNER/REPOSITORY")
    security.git(repository, "add", "README.md")
    security.git(repository, "commit", "--quiet", "-m", "More clean placeholders")
    assert security.run(repository, scanner, require_history=True) == 0


@pytest.mark.parametrize("name", ["operator-report.json", ".env", "private/notes.md"])
def test_deleted_historical_private_artifacts_blocked_without_signatures(repository, scanner, name):
    path = repository / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("Private operational notes without a known credential signature")
    security.git(repository, "add", name)
    security.git(repository, "commit", "--quiet", "-m", "Synthetic private artifact")
    path.unlink()
    security.git(repository, "add", name)
    security.git(repository, "commit", "--quiet", "-m", "Remove artifact")
    assert security.run(repository, scanner) == 0
    with pytest.raises(security.ScanFailure, match="Private artifact"):
        security.run(repository, scanner, history=True, require_history=True)


def test_reused_blob_in_historical_private_path_is_not_deduplicated_away(repository, scanner):
    path = repository / "notes.md"
    path.write_text("Plain synthetic notes")
    security.git(repository, "add", "notes.md")
    security.git(repository, "commit", "--quiet", "-m", "Ordinary notes")
    (repository / "private").mkdir()
    security.git(repository, "mv", "notes.md", "private/notes.md")
    security.git(repository, "commit", "--quiet", "-m", "Move unchanged notes to private path")
    security.git(repository, "rm", "private/notes.md")
    security.git(repository, "commit", "--quiet", "-m", "Remove notes")
    assert security.git(repository, "rev-parse", "HEAD~2:notes.md") == security.git(
        repository, "rev-parse", "HEAD~1:private/notes.md"
    )
    with pytest.raises(security.ScanFailure, match="Private artifact"):
        security.run(repository, scanner, require_history=True)


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_deleted_historical_symlink_or_submodule_blocks_publication(repository, scanner, mode):
    path = repository / "README.md"
    path.write_text("Clean placeholder")
    security.git(repository, "add", "README.md")
    security.git(repository, "commit", "--quiet", "-m", "Clean base")
    source = "HEAD:README.md" if mode == "120000" else "HEAD"
    oid = security.git(repository, "rev-parse", source).decode().strip()
    # Build Git modes directly; Windows symlink privileges and a remote are unnecessary.
    security.git(repository, "update-index", "--add", "--cacheinfo", f"{mode},{oid},old-link")
    security.git(repository, "commit", "--quiet", "-m", "Synthetic historical mode")
    security.git(repository, "update-index", "--force-remove", "old-link")
    security.git(repository, "commit", "--quiet", "-m", "Remove historical mode")
    with pytest.raises(security.ScanFailure, match="symlinks/submodules"):
        security.run(repository, scanner, require_history=True)


def test_deleted_historical_oversized_file_blocks_publication(repository, scanner):
    path = repository / "large.txt"
    path.write_bytes(b"x" * (security.MAX_FILE_BYTES + 1))
    security.git(repository, "add", "large.txt")
    security.git(repository, "commit", "--quiet", "-m", "Synthetic oversized file")
    path.unlink()
    security.git(repository, "add", "large.txt")
    security.git(repository, "commit", "--quiet", "-m", "Remove oversized file")
    with pytest.raises(security.ScanFailure, match="oversized"):
        security.run(repository, scanner, require_history=True)


def test_ignored_reports_excluded_but_force_staged_reports_blocked(repository, scanner):
    (repository / ".gitignore").write_text("*.json\n")
    (repository / "report.json").write_text("{}")
    assert security.run(repository, scanner) == 0
    security.git(repository, "add", "-f", "report.json")
    with pytest.raises(security.ScanFailure, match="Private artifact"):
        security.run(repository, scanner, staged=True)


def test_inline_allow_does_not_suppress_findings(repository, scanner):
    (repository / "README.md").write_text("555566" + "667777 # gitleaks:allow")
    assert security.run(repository, scanner) == 1


def test_missing_tool_blocks_publication(repository):
    with pytest.raises(security.ScanFailure, match="tool missing"):
        security.run(repository, repository / "missing-scanner")


@pytest.mark.parametrize("history", [False, True])
def test_ci_rejects_missing_history(repository, scanner, history):
    with pytest.raises(security.ScanFailure, match="History required"):
        security.run(repository, scanner, history=history, require_history=True)


def test_security_scripts_support_runner_python():
    import ast

    for name in ("security_check.py", "install_security_tools.py"):
        ast.parse((ROOT / "scripts" / name).read_text(), feature_version=(3, 12))
