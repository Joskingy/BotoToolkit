"""Doctor's public CLI contract, identity gate, and safe output boundary."""

import json
from unittest.mock import Mock

import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import ACCOUNT, ARN, OTHER_REGION, REGION, identity_response
from rich.text import Text
from typer.testing import CliRunner

from amplify_ops.cli import app
from amplify_ops.models import DoctorCheck

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
AWS_COMMANDS = {
    "identity": [],
    "inventory": [],
    "investigate": ["--app-id", "d123", "--branch", "dev"],
    "compare": ["--app-id", "d123"],
    "api-keys": [],
    "costs": ["--start", "2026-01-01", "--end", "2026-02-01"],
    "stale": ["--app-id", "d123", "--repository", "OWNER/REPOSITORY"],
    "deploy-plan": [
        "--app-id",
        "d123",
        "--branch",
        "dev",
        "--job-id",
        "1",
        "--output",
        "plan.json",
    ],
    "deploy": ["--plan", "must-not-read.json", "--confirm-plan", "unreviewed-plan"],
}


@pytest.fixture
def local_config(monkeypatch, tmp_path):
    """Real config parsing must never activate a credential provider offline."""
    config = tmp_path / "private-aws-config"
    credentials = tmp_path / "private-aws-credentials"
    config.write_text(
        "[profile brewmaster]\n"
        f"region = {REGION}\n"
        "credential_process = doctor-provider-must-not-execute\n",
        encoding="utf-8",
    )
    credentials.write_text(
        "[brewmaster]\n"
        "aws_access_key_id = testing\n"
        "aws_secret_access_key = private-fixture-credential\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    factory = Mock(side_effect=AssertionError("Offline doctor created an AWS session"))
    subprocess = Mock(side_effect=AssertionError("Offline doctor launched a provider"))
    monkeypatch.setattr("amplify_ops.aws.boto3.Session", factory)
    monkeypatch.setattr("subprocess.run", subprocess)
    yield config, credentials, factory, subprocess
    factory.assert_not_called()
    subprocess.assert_not_called()


@pytest.fixture
def passing_checks(monkeypatch):
    collector = Mock(return_value=[DoctorCheck("local_setup", "pass", "Setup is ready.", "")])
    monkeypatch.setattr("amplify_ops.cli.collect_checks", collector)
    return collector


@pytest.fixture(params=(False, True), ids=("plain", "colored"))
def terminal_output(request, monkeypatch):
    """Exercise semantic errors with and without Rich's terminal styling."""
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", request.param)
    monkeypatch.setattr("typer.rich_utils.COLOR_SYSTEM", "standard" if request.param else None)
    monkeypatch.delenv("NO_COLOR", raising=False)
    return request.param


def parse_report(result):
    report = json.loads(result.stdout)
    assert set(report) == {"report_type", "schema_version", "complete", "checks"}
    assert report["report_type"] == "doctor"
    assert report["schema_version"] == 1
    assert isinstance(report["complete"], bool)
    assert report["checks"]
    for check in report["checks"]:
        assert set(check) == {"name", "status", "message", "next_step"}
        assert check["status"] in {"pass", "warn", "fail", "skip"}
    return report


def assert_private(text, *extra):
    for sensitive in (
        ACCOUNT,
        ARN,
        "000000000000",
        "brewmaster",
        "private-fixture-credential",
        "doctor-provider-must-not-execute",
        "private-service-error",
        *extra,
    ):
        assert sensitive not in text


def test_doctor_without_flags_is_offline_and_explains_unselected_settings(local_config):
    result = runner.invoke(app, ["doctor", "--format", "json"])

    assert result.exit_code == 0, result.output
    report = parse_report(result)
    checks = {check["name"]: check for check in report["checks"]}
    for name in ("aws_profile", "expected_account", "regions"):
        assert checks[name]["status"] == "warn"
        assert checks[name]["next_step"]
    assert checks["identity"]["status"] == "skip"
    assert report["complete"] is True
    assert result.stderr == ""
    assert_private(result.output, *(str(path) for path in local_config[:2]))


def test_explicit_offline_profile_is_read_without_resolving_credentials(local_config, tmp_path):
    output = tmp_path / "doctor.json"
    result = runner.invoke(app, OPTIONS + ["doctor", "--format", "json", "--output", str(output)])

    assert result.exit_code == 0, result.output
    report = parse_report(result)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["aws_profile"]["status"] == "pass"
    assert checks["identity"]["status"] == "skip"
    saved = output.read_text(encoding="utf-8")
    assert json.loads(saved) == report
    assert_private(result.output + saved, *(str(path) for path in local_config[:2]))
    assert result.stderr == ""


def test_selected_missing_profile_fails_locally_without_aws(local_config):
    config, credentials, _, _ = local_config
    config.write_text("[profile another-profile]\n", encoding="utf-8")
    credentials.write_text("[another-profile]\n", encoding="utf-8")

    result = runner.invoke(app, OPTIONS + ["doctor", "--format", "json"])

    assert result.exit_code == 1, result.output
    report = parse_report(result)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["aws_profile"]["status"] == "fail"
    assert checks["identity"]["status"] == "skip"
    assert report["complete"] is True
    assert_private(result.output, str(config), str(credentials))


@pytest.mark.parametrize("command", AWS_COMMANDS)
@pytest.mark.parametrize("omitted", ("--profile", "--expected-account", "--region"))
def test_existing_aws_commands_still_require_each_explicit_option(monkeypatch, command, omitted):
    factory = Mock(side_effect=AssertionError("AWS called before options were validated"))
    monkeypatch.setattr("amplify_ops.aws.boto3.Session", factory)
    options = []
    for index in range(0, len(OPTIONS), 2):
        if OPTIONS[index] != omitted:
            options.extend(OPTIONS[index : index + 2])

    result = runner.invoke(app, options + [command] + AWS_COMMANDS[command])

    assert result.exit_code == 2, result.output
    assert omitted in Text.from_ansi(result.output).plain
    factory.assert_not_called()


@pytest.mark.parametrize(
    "options",
    (
        ["--profile", ""],
        ["--profile", "<PROFILE>"],
        ["--profile", "unsafe\nprofile"],
        ["--expected-account", ""],
        ["--expected-account", "ACCOUNT_ID"],
        ["--expected-account", "11112222333"],
        ["--region", "REGION"],
    ),
)
def test_doctor_rejects_explicit_malformed_settings_before_local_checks(passing_checks, options):
    result = runner.invoke(app, options + ["doctor", "--format", "json"])

    assert result.exit_code == 2, result.output
    passing_checks.assert_not_called()


@pytest.mark.parametrize("omitted", ("--profile", "--expected-account", "--region", "all"))
def test_online_doctor_requires_all_explicit_settings_before_checks(passing_checks, omitted):
    options = []
    if omitted != "all":
        for index in range(0, len(OPTIONS), 2):
            if OPTIONS[index] != omitted:
                options.extend(OPTIONS[index : index + 2])

    result = runner.invoke(app, options + ["doctor", "--online", "--format", "json"])

    assert result.exit_code == 2, result.output
    assert ("--profile" if omitted == "all" else omitted) in Text.from_ansi(result.output).plain
    passing_checks.assert_not_called()


def test_online_doctor_rejects_multiple_regions_before_checks(passing_checks):
    result = runner.invoke(
        app, OPTIONS + ["--region", OTHER_REGION, "doctor", "--online", "--format", "json"]
    )

    assert result.exit_code == 2, result.output
    assert "--region" in Text.from_ansi(result.output).plain
    passing_checks.assert_not_called()


@pytest.mark.parametrize("scenario", ("missing_options", "multiple_regions"))
def test_cli_errors_remain_readable_with_or_without_color(
    passing_checks, terminal_output, monkeypatch, scenario
):
    factory = Mock(side_effect=AssertionError("AWS called before options were validated"))
    monkeypatch.setattr("amplify_ops.aws.boto3.Session", factory)
    if scenario == "missing_options":
        arguments = ["doctor", "--online"]
        option = "--profile"
    else:
        arguments = OPTIONS + ["--region", OTHER_REGION, "doctor", "--online"]
        option = "--region"

    result = runner.invoke(app, arguments)

    assert result.exit_code == 2, result.output
    assert option in Text.from_ansi(result.output).plain
    assert ("\x1b[" in result.output) is terminal_output
    passing_checks.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize(
    "outcome", ("success", "mismatch", "ExpiredToken", "AccessDenied", "transport")
)
def test_online_doctor_only_verifies_identity_and_never_exports_it(
    harness, passing_checks, tmp_path, monkeypatch, outcome
):
    factory, session, stubs = harness
    sts = stubs["sts", REGION]
    if outcome == "success":
        identity_response(stubs)
    elif outcome == "mismatch":
        identity_response(stubs, "000000000000")
    elif outcome == "transport":
        monkeypatch.setattr(
            sts.client,
            "get_caller_identity",
            Mock(side_effect=EndpointConnectionError(endpoint_url="https://private-service-error")),
        )
    else:
        sts.add_client_error(
            "get_caller_identity", outcome, "private-service-error", expected_params={}
        )
    output = tmp_path / "doctor.json"

    result = runner.invoke(
        app,
        OPTIONS
        + [
            "doctor",
            "--online",
            "--project",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == (0 if outcome == "success" else 1), result.output
    report = parse_report(result)
    assert report["complete"] is True
    identity = next(check for check in report["checks"] if check["name"] == "identity")
    assert identity["status"] == ("pass" if outcome == "success" else "fail")
    if outcome != "success":
        assert identity["next_step"]
    factory.assert_called_once_with(profile_name="brewmaster", region_name=REGION)
    session.client.assert_called_once()
    assert session.client.call_args.args == ("sts",)
    assert session.client.call_args.kwargs["region_name"] == REGION
    passing_checks.assert_called_once_with("brewmaster", ACCOUNT, [REGION], tmp_path)
    saved = output.read_text(encoding="utf-8")
    assert json.loads(saved) == report
    assert result.stderr == ""
    assert_private(result.output + saved, str(output), str(tmp_path))


def test_online_local_failure_skips_identity_and_marks_report_incomplete(monkeypatch, harness):
    factory, session, _ = harness
    monkeypatch.setattr(
        "amplify_ops.cli.collect_checks",
        Mock(
            return_value=[DoctorCheck("aws_profile", "fail", "Profile missing.", "Configure it.")]
        ),
    )

    result = runner.invoke(app, OPTIONS + ["doctor", "--online", "--format", "json"])

    assert result.exit_code == 1, result.output
    report = parse_report(result)
    assert report["complete"] is False
    identity = next(check for check in report["checks"] if check["name"] == "identity")
    assert identity["status"] == "skip"
    assert identity["next_step"]
    factory.assert_not_called()
    session.client.assert_not_called()


@pytest.mark.parametrize("status,exit_code", (("warn", 0), ("fail", 1)))
def test_table_explains_findings_and_writes_same_structured_report(
    monkeypatch, tmp_path, status, exit_code
):
    monkeypatch.setattr(
        "amplify_ops.cli.collect_checks",
        Mock(
            return_value=[DoctorCheck("local_setup", status, "Local setup finding.", "Run setup.")]
        ),
    )
    output = tmp_path / "doctor.json"

    result = runner.invoke(app, ["doctor", "--output", str(output)], terminal_width=180)

    assert result.exit_code == exit_code, result.output
    assert "Local setup finding." in result.stdout
    assert "Run setup." in result.stdout
    assert status.upper() in result.stdout
    assert "SKIP" in result.stdout
    assert "service permissions are not tested" in " ".join(result.stdout.split())
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["checks"][0]["status"] == status
    assert report["checks"][-1]["name"] == "identity"
    assert_private(result.output + output.read_text(encoding="utf-8"), str(output))


@pytest.mark.parametrize("exists", (True, False))
def test_output_failures_do_not_overwrite_files_or_expose_paths(passing_checks, tmp_path, exists):
    output = tmp_path / (
        "private-existing.json" if exists else "private-missing-parent/doctor.json"
    )
    if exists:
        output.write_text("keep this existing report", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--format", "json", "--output", str(output)])

    assert result.exit_code == 1, result.output
    parse_report(result)
    assert "Cannot write JSON output" in result.stderr
    assert str(output) not in result.output
    assert output.name not in result.output
    if exists:
        assert output.read_text(encoding="utf-8") == "keep this existing report"
    else:
        assert not output.exists()


@pytest.mark.parametrize(
    "arguments",
    (["--help"], ["doctor", "--help"], *([command, "--help"] for command in AWS_COMMANDS)),
)
def test_help_requires_no_aws_settings_or_local_checks(passing_checks, arguments):
    result = runner.invoke(app, arguments)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.stdout
    passing_checks.assert_not_called()


@pytest.mark.parametrize("blocked_check", ("project_files", "uv"))
def test_requested_project_checks_skipped_offline_mark_report_incomplete(
    local_config, tmp_path, monkeypatch, blocked_check
):
    project = tmp_path / "private-selected-project"
    if blocked_check == "uv":
        project.mkdir()
        for filename in ("pyproject.toml", "uv.lock"):
            (project / filename).write_text("", encoding="utf-8")
        monkeypatch.setattr("amplify_ops.doctor.shutil.which", lambda _: None)

    result = runner.invoke(app, ["doctor", "--project", str(project), "--format", "json"])

    assert result.exit_code == 1, result.output
    report = parse_report(result)
    assert report["complete"] is False
    checks = {check["name"]: check for check in report["checks"]}
    assert checks[blocked_check]["status"] == "fail"
    for name in ("uv_lock", "dependencies", "identity"):
        assert checks[name]["status"] == "skip"
    assert_private(result.output, str(project))
