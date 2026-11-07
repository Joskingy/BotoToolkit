"""Offline doctor checks use local files and bounded, non-mutating validation only."""

import io
import stat
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from amplify_ops import doctor

ACCOUNT = "111122223333"
REGION = "us-east-1"
PRIVATE_MARKER = "private-doctor-canary"


@pytest.fixture
def local_files(tmp_path, monkeypatch):
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text("[profile brewmaster]\nregion = us-east-1\n", encoding="utf-8")
    credentials.write_text("", encoding="utf-8")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setattr(doctor.metadata, "version", lambda name: "1.0")
    return config, credentials


def run_checks(project=None, profile="brewmaster", account=ACCOUNT, regions=None):
    checks = doctor.collect_checks(
        profile, account, [REGION] if regions is None else regions, project
    )
    return {check.name: check for check in checks}


def assert_redacted(checks, *private_values):
    text = repr([asdict(check) for check in checks.values()])
    for value in private_values:
        assert value not in text


def test_offline_checks_never_resolve_credentials_or_spawn_processes(local_files, monkeypatch):
    config, credentials = local_files
    config.write_text(
        f"[profile brewmaster]\ncredential_process = {PRIVATE_MARKER}\n"
        "sso_session = local-session\n[sso-session local-session]\n"
        f"sso_start_url = https://{PRIVATE_MARKER}.example.invalid\n",
        encoding="utf-8",
    )
    forbidden = Mock(side_effect=AssertionError("Offline checks invoked an external provider"))
    monkeypatch.setattr("boto3.Session", forbidden)
    monkeypatch.setattr("botocore.session.get_session", forbidden)
    monkeypatch.setattr(doctor.subprocess, "run", forbidden)
    monkeypatch.setattr(doctor.shutil, "which", forbidden)
    checks = run_checks()
    assert checks["aws_profile"].status == "pass"
    assert checks["project_files"].status == "skip"
    assert checks["dependencies"].status == "skip"
    assert not any(check.status == "fail" for check in checks.values())
    forbidden.assert_not_called()
    assert_redacted(checks, PRIVATE_MARKER, str(config), str(credentials), ACCOUNT, REGION)


def test_unselected_options_warn_without_using_environment_defaults(local_files, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "brewmaster")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "brewmaster")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    read = Mock(side_effect=AssertionError("Unselected profile must not read AWS files"))
    monkeypatch.setattr(doctor, "_read_sections", read)
    checks = run_checks(profile=None, account=None, regions=[])
    for name in ("aws_profile", "expected_account", "regions"):
        assert checks[name].status == "warn"
        assert checks[name].next_step
    read.assert_not_called()


@pytest.mark.parametrize(
    "version,status", [((3, 14, 9), "fail"), ((3, 15, 0), "pass"), ((3, 16, 0), "pass")]
)
def test_python_minimum(local_files, monkeypatch, version, status):
    monkeypatch.setattr(doctor.sys, "version_info", version)
    assert run_checks()["python"].status == status


@pytest.mark.parametrize("name", doctor.DISTRIBUTIONS)
def test_missing_required_distribution_fails_safely(local_files, monkeypatch, name):
    def version(distribution):
        if distribution == name:
            raise doctor.metadata.PackageNotFoundError(PRIVATE_MARKER)
        return "1.0"

    monkeypatch.setattr(doctor.metadata, "version", version)
    checks = run_checks()
    assert checks["package_" + name.replace("-", "_")].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_version_metadata_is_not_claimed_healthy(local_files, monkeypatch, value):
    monkeypatch.setattr(doctor.metadata, "version", lambda name: value)
    checks = run_checks()
    assert checks["package_boto3"].status == "fail"


def test_package_versions_are_not_exported(local_files, monkeypatch):
    monkeypatch.setattr(doctor.metadata, "version", lambda name: PRIVATE_MARKER)
    assert_redacted(run_checks(), PRIVATE_MARKER)


@pytest.mark.parametrize("location", ["config", "credentials"])
def test_profile_can_be_defined_in_either_file(local_files, location):
    config, credentials = local_files
    config.write_text("", encoding="utf-8")
    if location == "config":
        config.write_text('[profile "brewmaster"]\nsso_session = local\n', encoding="utf-8")
    else:
        credentials.write_text(
            f"[brewmaster]\naws_access_key_id = {PRIVATE_MARKER}\n", encoding="utf-8"
        )
    checks = run_checks()
    assert checks["aws_profile"].status == "pass"
    assert_redacted(checks, PRIVATE_MARKER)


def test_default_profile_section_is_supported_only_when_selected(local_files):
    config, _ = local_files
    config.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    assert run_checks(profile="default")["aws_profile"].status == "pass"
    assert run_checks()["aws_profile"].status == "fail"


def test_other_profile_does_not_supply_selected_profile(local_files):
    config, credentials = local_files
    config.write_text(f"[profile {PRIVATE_MARKER}]\n", encoding="utf-8")
    credentials.write_text("[default]\n", encoding="utf-8")
    checks = run_checks()
    assert checks["aws_profile"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)


def test_default_aws_file_paths_and_absent_credentials_are_supported(
    tmp_path, local_files, monkeypatch
):
    aws = tmp_path / ".aws"
    aws.mkdir()
    (aws / "config").write_text("[profile brewmaster]\nsso_session = local\n", encoding="utf-8")
    monkeypatch.delenv("AWS_CONFIG_FILE")
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert run_checks()["aws_profile"].status == "pass"


@pytest.mark.parametrize("variable", ["AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"])
@pytest.mark.parametrize("value", ["", "missing", "directory"])
def test_explicit_unusable_aws_path_fails(local_files, tmp_path, monkeypatch, variable, value):
    path = "" if not value else str(tmp_path if value == "directory" else tmp_path / "missing")
    monkeypatch.setenv(variable, path)
    checks = run_checks()
    assert checks["aws_profile"].status == "fail"
    assert_redacted(checks, str(tmp_path))


@pytest.mark.parametrize(
    "contents",
    [
        b"not INI",
        b"[profile brewmaster]\nkey=one\nkey=two\n",
        b"[profile brewmaster]\n[profile brewmaster]\n",
        b"\xff",
        b'[profile "unterminated]\n',
    ],
)
def test_malformed_aws_config_fails_without_leaking_contents(local_files, contents):
    config, _ = local_files
    config.write_bytes(contents)
    checks = run_checks()
    assert checks["aws_profile"].status == "fail"
    assert_redacted(checks, str(config))


def test_malformed_credentials_fail_even_when_config_contains_profile(local_files):
    _, credentials = local_files
    credentials.write_text(PRIVATE_MARKER, encoding="utf-8")
    checks = run_checks()
    assert checks["aws_profile"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)


def test_unreadable_config_error_is_redacted(local_files, monkeypatch):
    config, _ = local_files
    original = Path.open

    def open_file(path, *args, **kwargs):
        if path == config:
            raise PermissionError(PRIVATE_MARKER)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    checks = run_checks()
    assert checks["aws_profile"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)


def test_oversized_config_is_rejected_before_reading(local_files, monkeypatch):
    config, _ = local_files
    config.write_bytes(b"x" * (doctor.MAX_CONFIG_BYTES + 1))
    opened = Mock(side_effect=AssertionError("Oversized file was read"))
    monkeypatch.setattr(Path, "open", opened)
    assert run_checks()["aws_profile"].status == "fail"
    opened.assert_not_called()


def test_config_growth_still_uses_a_bounded_read(local_files, monkeypatch):
    config, _ = local_files
    original = Path.stat
    original_open = Path.open
    reads = []

    class GrowingFile(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def file_stat(path, *args, **kwargs):
        if path == config:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_size=1)
        return original(path, *args, **kwargs)

    def open_file(path, *args, **kwargs):
        if path == config:
            return GrowingFile(b"x" * (doctor.MAX_CONFIG_BYTES + 1))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", file_stat)
    monkeypatch.setattr(Path, "open", open_file)
    assert run_checks()["aws_profile"].status == "fail"
    assert reads == [doctor.MAX_CONFIG_BYTES + 1]


@pytest.mark.parametrize("account", ["ACCOUNT_ID", "123", "１" * 12])
def test_invalid_account_is_rejected_without_exporting_it(local_files, account):
    assert run_checks(account=account)["expected_account"].status == "fail"


def test_invalid_region_is_rejected_without_exporting_it(local_files):
    checks = run_checks(regions=[PRIVATE_MARKER])
    assert checks["regions"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "source"
    path.mkdir()
    (path / "pyproject.toml").write_text('[project]\nname="fixture"\n', encoding="utf-8")
    (path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("missing", ["pyproject.toml", "uv.lock"])
def test_missing_project_file_prevents_subprocess(local_files, project, monkeypatch, missing):
    (project / missing).unlink()
    runner = Mock(side_effect=AssertionError("Incomplete project ran uv"))
    monkeypatch.setattr(doctor.subprocess, "run", runner)
    checks = run_checks(project)
    assert checks["project_files"].status == "fail"
    assert checks["uv_lock"].status == "skip"
    runner.assert_not_called()


def test_missing_project_directory_fails(local_files, tmp_path):
    assert run_checks(tmp_path / "missing")["project_files"].status == "fail"


def test_missing_uv_fails_and_skips_validation(local_files, project, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: None)
    runner = Mock(side_effect=AssertionError("Missing uv must not run"))
    monkeypatch.setattr(doctor.subprocess, "run", runner)
    checks = run_checks(project)
    assert checks["uv"].status == "fail"
    assert checks["uv_lock"].status == checks["dependencies"].status == "skip"
    runner.assert_not_called()


def test_project_validation_is_offline_bounded_and_uses_current_interpreter(
    local_files, project, monkeypatch
):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "uv")
    monkeypatch.setenv("UV_FROZEN", "true")
    monkeypatch.setenv("UV_PYTHON", PRIVATE_MARKER)
    monkeypatch.setenv("VIRTUAL_ENV", PRIVATE_MARKER)
    runner = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(doctor.subprocess, "run", runner)
    before = {path.name: path.read_bytes() for path in project.iterdir()}
    checks = run_checks(project)
    assert checks["uv_lock"].status == checks["dependencies"].status == "pass"
    assert runner.call_count == 2
    commands = []
    for call in runner.call_args_list:
        command = call.args[0]
        commands.append(command)
        assert "--offline" in command and "--no-python-downloads" in command
        assert "--no-cache" in command
        assert command[command.index("--python") + 1] == doctor.sys.executable
        assert call.kwargs["cwd"] == project
        assert call.kwargs["timeout"] == doctor.UV_TIMEOUT_SECONDS
        assert (
            call.kwargs["stdin"]
            == call.kwargs["stdout"]
            == call.kwargs["stderr"]
            == subprocess.DEVNULL
        )
        assert not any(key.upper().startswith("UV_") for key in call.kwargs["env"])
        assert "VIRTUAL_ENV" not in call.kwargs["env"]
        assert call.kwargs["check"] is False
    assert commands[0][1:3] == ["lock", "--check"]
    assert "--no-build" in commands[0]
    assert commands[0][commands[0].index("--keyring-provider") + 1] == "disabled"
    assert commands[1][1:3] == ["pip", "check"]
    assert {path.name: path.read_bytes() for path in project.iterdir()} == before
    assert_redacted(checks, str(project), PRIVATE_MARKER)


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError(PRIVATE_MARKER),
        ValueError(PRIVATE_MARKER),
        subprocess.TimeoutExpired(PRIVATE_MARKER, doctor.UV_TIMEOUT_SECONDS, output=PRIVATE_MARKER),
    ],
)
def test_subprocess_failures_are_reported_and_redacted(local_files, project, monkeypatch, failure):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "uv")
    monkeypatch.setattr(doctor.subprocess, "run", Mock(side_effect=failure))
    checks = run_checks(project)
    assert checks["uv_lock"].status == checks["dependencies"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER, str(project))


def test_nonzero_validations_report_failure_without_replaying_tool_output(
    local_files, project, monkeypatch
):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "uv")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        Mock(
            return_value=SimpleNamespace(returncode=1, stdout=PRIVATE_MARKER, stderr=PRIVATE_MARKER)
        ),
    )
    checks = run_checks(project)
    assert checks["uv_lock"].status == checks["dependencies"].status == "fail"
    assert_redacted(checks, PRIVATE_MARKER)
