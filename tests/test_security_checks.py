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


def test_ci_rejects_missing_history(repository, scanner):
    with pytest.raises(security.ScanFailure, match="History required"):
        security.run(repository, scanner, history=True, require_history=True)


def test_security_scripts_support_runner_python():
    import ast

    for name in ("security_check.py", "install_security_tools.py"):
        ast.parse((ROOT / "scripts" / name).read_text(), feature_version=(3, 12))
