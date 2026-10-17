import json
from unittest.mock import Mock

import pytest
from botocore.exceptions import ProfileNotFound
from conftest import (
    ACCOUNT,
    ARN,
    REGION,
    app_response,
    branch_response,
    identity_response,
    job_response,
)
from typer.testing import CliRunner

from amplify_ops.cli import app

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]


def test_json_allowlist_stdout_and_file(harness, tmp_path):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response(
        "list_apps",
        {
            "apps": [
                app_response(
                    repository="https://user:repo-token@github.com/org/repo?token=query-secret#fragment-secret"
                )
            ]
        },
        {},
    )
    stub.add_response("list_branches", {"branches": [branch_response()]}, {"appId": "d123"})
    stub.add_response(
        "list_jobs",
        {"jobSummaries": [job_response(sourceUrl="https://signed.example/?token=source-secret")]},
        {"appId": "d123", "branchName": "main"},
    )
    output = tmp_path / "inventory.json"
    result = runner.invoke(
        app, OPTIONS + ["inventory", "--format", "json", "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document == json.loads(output.read_text(encoding="utf-8"))
    assert document["identity"] == {"account_id": ACCOUNT, "caller_arn": ARN}
    assert document["apps"][0]["repository"] == "https://github.com/org/repo"
    assert "Verified account" in result.stderr
    assert "Regions: us-east-1" in result.stderr
    for sensitive in (
        "environmentVariables",
        "basicAuthCredentials",
        "app-secret",
        "branch-secret",
        "sensitive-basic-auth",
        "branch-basic-auth",
        "private-commit-message",
        "source-secret",
        "repo-token",
        "query-secret",
        "fragment-secret",
        "ResponseMetadata",
    ):
        assert sensitive not in result.output
        assert sensitive not in output.read_text(encoding="utf-8")


def test_partial_scan_has_valid_json_and_nonzero_exit(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_client_error(
        "list_apps", "UnauthorizedException", "do-not-export-this-message", expected_params={}
    )
    result = runner.invoke(app, OPTIONS + ["inventory", "--format", "json"])
    assert result.exit_code == 3
    document = json.loads(result.stdout)
    assert document["complete"] is False
    assert document["errors"][0]["category"] == "access_denied"
    assert "PARTIAL" in result.stderr
    assert "do-not-export-this-message" not in result.output


def test_identity_displays_verified_account_and_arn(harness):
    _, _, stubs = harness
    identity_response(stubs)
    result = runner.invoke(app, OPTIONS + ["identity"])
    assert result.exit_code == 0
    assert ACCOUNT in result.stdout and ARN in result.stdout


def test_identity_mismatch_returns_failure_with_no_stdout(harness):
    _, session, stubs = harness
    identity_response(stubs, "000000000000")
    result = runner.invoke(app, OPTIONS + ["inventory", "--format", "json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Account mismatch" in result.stderr
    assert session.client.call_count == 1


def test_missing_profile_has_no_fallback(harness):
    factory, _, _ = harness
    factory.side_effect = ProfileNotFound(profile="brewmaster")
    result = runner.invoke(app, OPTIONS + ["identity"])
    assert result.exit_code == 1
    assert "ProfileNotFound" in result.stderr
    assert factory.call_count == 1


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--profile", "<AWS_PROFILE>", "--expected-account", ACCOUNT, "--region", REGION],
        ["--profile", "brewmaster", "--expected-account", "<AWS_ACCOUNT_ID>", "--region", REGION],
        ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", "<AWS_REGION>"],
    ],
)
def test_unresolved_or_missing_options_fail_before_session(monkeypatch, options):
    factory = Mock()
    monkeypatch.setattr("amplify_ops.aws.boto3.Session", factory)
    result = runner.invoke(app, options + ["identity"])
    assert result.exit_code == 2
    factory.assert_not_called()


def test_table_displays_app_without_branches(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_response("list_apps", {"apps": [app_response()]}, {})
    stubs["amplify", REGION].add_response("list_branches", {"branches": []}, {"appId": "d123"})
    result = runner.invoke(app, OPTIONS + ["inventory"], terminal_width=180)
    assert result.exit_code == 0
    assert "COMPLETE scan" in result.stdout
    assert "(no branches)" in result.stdout
    assert "Test app" in result.stdout


def test_duplicate_regions_are_scanned_once(harness):
    _, session, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_response("list_apps", {"apps": []}, {})
    result = runner.invoke(app, OPTIONS + ["--region", REGION, "inventory", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["regions"] == [REGION]
    assert session.client.call_count == 2


def test_existing_output_is_not_overwritten(harness, tmp_path):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_response("list_apps", {"apps": []}, {})
    target = tmp_path / "existing.json"
    target.write_text("keep", encoding="utf-8")
    result = runner.invoke(app, OPTIONS + ["inventory", "--output", str(target)])
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == "keep"
    assert "Cannot write JSON" in result.stderr
