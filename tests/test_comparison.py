import json

import pytest
from conftest import ACCOUNT, REGION, app_response, branch_response, identity_response
from typer.testing import CliRunner

from amplify_ops.cli import app

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
TARGET = ["compare", "--app-id", "d123"]


def branch_config(name, **settings):
    return {**branch_response(name), **settings}


def queue_configs(stubs, shared, left, right):
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("get_app", {"app": shared}, {"appId": "d123"})
    stub.add_response("get_branch", {"branch": left}, {"appId": "d123", "branchName": "dev"})
    stub.add_response("get_branch", {"branch": right}, {"appId": "d123", "branchName": "main"})


def run_json(*args):
    return runner.invoke(app, OPTIONS + TARGET + list(args) + ["--format", "json"])


def rows(report, section):
    return {item["key"]: item for item in report["entries"] if item["section"] == section}


def test_environment_inheritance_overrides_missing_and_empty_values(harness):
    _, session, stubs = harness
    queue_configs(
        stubs,
        app_response(
            environmentVariables={
                "COMMON": "shared-value",
                "OVERRIDE": "same-value",
                "EMPTY_OVERRIDE": "base-value",
            }
        ),
        branch_config(
            "dev",
            environmentVariables={
                "DIFFERENT": "left-value",
                "OVERRIDE": "same-value",
                "LEFT_ONLY": "left-only",
                "EMPTY": "",
                "EMPTY_OVERRIDE": "",
            },
        ),
        branch_config("main", environmentVariables={"DIFFERENT": "right-value", "RIGHT_ONLY": "r"}),
    )
    result = run_json()
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    env = rows(report, "environment")
    assert env["COMMON"]["result"] == "equal"
    assert env["COMMON"]["source_origin"] == env["COMMON"]["target_origin"] == "app"
    assert env["OVERRIDE"]["result"] == "equal" and env["OVERRIDE"]["origin_differs"]
    assert env["OVERRIDE"]["source_origin"] == "branch"
    assert env["OVERRIDE"]["target_origin"] == "app"
    assert env["DIFFERENT"]["result"] == "different"
    assert env["LEFT_ONLY"]["result"] == "missing_target"
    assert env["RIGHT_ONLY"]["result"] == "missing_source"
    assert env["EMPTY"]["source_state"] == "present_redacted"
    assert env["EMPTY"]["result"] == "missing_target"
    assert env["EMPTY_OVERRIDE"]["result"] == "different"
    assert report["complete"] and report["has_differences"]
    assert report["differences_found"] == 6
    assert session.client.call_count == 2  # one STS and one reused Amplify client


def test_redacted_json_file_and_stdout_never_contain_values(harness, tmp_path):
    _, _, stubs = harness
    secret_values = [
        "secret-app-value",
        "secret-left-value",
        "secret-right-value",
        "secret-build-spec",
        "secret-basic-auth-left",
        "secret-basic-auth-right",
        "secret-header-value",
        "secret-service-role",
        "secret-backend-stack",
    ]
    queue_configs(
        stubs,
        app_response(
            environmentVariables={"API_TOKEN": secret_values[0]},
            buildSpec=secret_values[3],
            customHeaders=secret_values[6],
            iamServiceRoleArn=secret_values[7],
        ),
        branch_config(
            "dev",
            environmentVariables={"API_TOKEN": secret_values[1]},
            basicAuthCredentials=secret_values[4],
            backend={"stackArn": secret_values[8]},
            stage="DEVELOPMENT",
        ),
        branch_config(
            "main",
            environmentVariables={"API_TOKEN": secret_values[2]},
            basicAuthCredentials=secret_values[5],
            stage="PRODUCTION",
        ),
    )
    path = tmp_path / "comparison.json"
    result = run_json("--output", str(path))
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    saved = path.read_text(encoding="utf-8")
    assert json.loads(saved) == report
    for value in [*secret_values, "DEVELOPMENT", "PRODUCTION", "sensitive-basic-auth"]:
        assert value not in result.output and value not in saved
    assert "API_TOKEN" in saved
    assert rows(report, "branch")["basicAuthCredentials"]["result"] == "different"
    assert rows(report, "shared_app")["buildSpec"]["result"] == "shared"
    assert rows(report, "branch")["buildSpec"]["result"] == "absent_both"
    assert "Verified account" in result.stderr
    # Ensure no incidental value/hash field is added to the output schema.
    for row in report["entries"]:
        assert set(row) == {
            "section",
            "key",
            "source_state",
            "target_state",
            "source_origin",
            "target_origin",
            "result",
            "origin_differs",
        }


def test_equal_configuration_does_not_compare_runtime_metadata(harness):
    _, _, stubs = harness
    queue_configs(
        stubs,
        app_response(environmentVariables={}),
        branch_config("dev", activeJobId="100", totalNumberOfJobs="200"),
        branch_config("main", activeJobId="1", totalNumberOfJobs="1"),
    )
    result = run_json()
    report = json.loads(result.stdout)
    assert result.exit_code == 0
    assert report["complete"] and report["has_differences"] is False
    assert report["differences_found"] == 0
    assert rows(report, "branch")["enableAutoBuild"]["source_state"] == "present_redacted"
    assert rows(report, "branch")["enableAutoBuild"]["result"] == "equal"
    assert "activeJobId" not in result.stdout


def test_app_access_failure_keeps_branch_evidence_without_inventing_inheritance(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_client_error(
        "get_app",
        "UnauthorizedException",
        "secret-error-message",
        expected_params={"appId": "d123"},
    )
    stub.add_response(
        "get_branch",
        {"branch": branch_config("dev", environmentVariables={"BOTH": "x", "LEFT": "left"})},
        {"appId": "d123", "branchName": "dev"},
    )
    stub.add_response(
        "get_branch",
        {"branch": branch_config("main", environmentVariables={"BOTH": "x"})},
        {"appId": "d123", "branchName": "main"},
    )
    result = run_json()
    assert result.exit_code == 3
    report = json.loads(result.stdout)
    env = rows(report, "environment")
    assert not report["complete"] and report["has_differences"] is None
    assert env["BOTH"]["result"] == "equal"
    assert env["LEFT"]["result"] == "unavailable"
    assert env["LEFT"]["target_state"] == "unavailable"
    assert rows(report, "shared_app")["platform"]["result"] == "unavailable"
    assert report["errors"][0]["category"] == "access_denied"
    assert "secret-error-message" not in result.output


def test_missing_source_branch_is_unknown_even_when_app_default_is_known(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response(
        "get_app", {"app": app_response(environmentVariables={"GLOBAL": "x"})}, {"appId": "d123"}
    )
    stub.add_client_error(
        "get_branch", "NotFoundException", expected_params={"appId": "d123", "branchName": "dev"}
    )
    stub.add_response(
        "get_branch",
        {"branch": branch_config("main", environmentVariables={})},
        {"appId": "d123", "branchName": "main"},
    )
    result = run_json()
    report = json.loads(result.stdout)
    assert result.exit_code == 3
    assert rows(report, "environment")["GLOBAL"]["source_state"] == "unavailable"
    assert rows(report, "environment")["GLOBAL"]["target_origin"] == "app"
    assert report["has_differences"] is None
    assert report["errors"][0]["branch_name"] == "dev"


def test_known_difference_is_retained_in_partial_report(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_client_error("get_app", "UnauthorizedException", expected_params={"appId": "d123"})
    for name, stage in [("dev", "DEVELOPMENT"), ("main", "PRODUCTION")]:
        stub.add_response(
            "get_branch",
            {"branch": branch_config(name, stage=stage)},
            {"appId": "d123", "branchName": name},
        )
    result = run_json()
    report = json.loads(result.stdout)
    assert result.exit_code == 3
    assert report["has_differences"] is True and report["differences_found"] == 1


def test_auth_failure_stops_before_remaining_branch_reads(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("get_app", {"app": app_response()}, {"appId": "d123"})
    stub.add_client_error(
        "get_branch",
        "ExpiredTokenException",
        expected_params={"appId": "d123", "branchName": "dev"},
    )
    result = run_json()
    assert result.exit_code == 1 and result.stdout == ""
    assert "authentication failed" in result.stderr


def test_wrong_account_prevents_config_reads(harness):
    _, session, stubs = harness
    identity_response(stubs, "000000000000")
    result = run_json()
    assert result.exit_code == 1 and result.stdout == ""
    assert session.client.call_count == 1


@pytest.mark.parametrize(
    "extra",
    [
        ["--source", "main"],
        ["--target", "<BRANCH>"],
        ["--source", ""],
        ["--source", "bad\nbranch"],
    ],
)
def test_invalid_branches_are_rejected_before_auth(harness, extra):
    factory, _, _ = harness
    result = run_json(*extra)
    assert result.exit_code == 2
    factory.assert_not_called()


def test_multiple_regions_rejected_before_auth(harness):
    factory, _, _ = harness
    result = runner.invoke(app, OPTIONS + ["--region", "us-west-2"] + TARGET)
    assert result.exit_code == 2
    factory.assert_not_called()


def test_custom_feature_branch_names_are_used_exactly(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("get_app", {"app": app_response()}, {"appId": "d123"})
    for name in ("feature/new", "release/candidate"):
        stub.add_response(
            "get_branch", {"branch": branch_config(name)}, {"appId": "d123", "branchName": name}
        )
    result = run_json("--source", "feature/new", "--target", "release/candidate")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["target_branch"] == "release/candidate"


def test_table_keeps_values_redacted(harness):
    _, _, stubs = harness
    queue_configs(
        stubs,
        app_response(),
        branch_config("dev", environmentVariables={"KEY": "left-secret"}),
        branch_config("main", environmentVariables={"KEY": "right-secret"}),
    )
    result = runner.invoke(app, OPTIONS + TARGET)
    assert result.exit_code == 0
    assert "COMPLETE comparison" in result.stdout
    assert "KEY" in result.stdout and "different" in result.stdout
    assert "left-secret" not in result.output and "right-secret" not in result.output
