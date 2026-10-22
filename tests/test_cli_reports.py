"""Exercise shipped default-table command paths with real SDK response shapes."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import (
    ACCOUNT,
    REGION,
    app_response,
    branch_response,
    identity_response,
    job_response,
)
from typer.testing import CliRunner

from amplify_ops.aws import AwsAccess
from amplify_ops.cli import app
from amplify_ops.deployments import create_plan
from amplify_ops.models import Report
from amplify_ops.presentation import json_report

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]


def test_api_keys_default_table_and_json_file_keep_credentials_private(services, tmp_path):
    _, _, stubs = services
    identity_response(stubs)
    raw_key = "da2-private-key-must-not-appear"
    stubs["appsync", REGION].add_response(
        "list_api_keys",
        {
            "apiKeys": [
                {
                    "id": raw_key,
                    "expires": int((datetime.now(UTC) + timedelta(days=3)).timestamp()),
                    "description": "private-api-key-description",
                }
            ]
        },
        {"apiId": "api1"},
    )
    output = tmp_path / "api-keys.json"

    result = runner.invoke(
        app,
        OPTIONS + ["api-keys", "--api-id", "api1", "--output", str(output)],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "COMPLETE" in result.stdout
    assert "api1" in result.stdout and "expiring" in result.stdout
    assert "sha256:" in result.stdout
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["complete"] is True
    assert document["rows"][0]["status"] == "expiring"
    assert document["rows"][1]["keys_found"] == 1
    for sensitive in (raw_key, "private-api-key-description"):
        assert sensitive not in result.output
        assert sensitive not in output.read_text(encoding="utf-8")


def test_api_key_denial_keeps_partial_default_table_and_safe_diagnostic(services, tmp_path):
    _, _, stubs = services
    identity_response(stubs)
    stubs["appsync", REGION].add_client_error(
        "list_api_keys",
        "AccessDeniedException",
        "private-service-diagnostic",
        expected_params={"apiId": "denied-api"},
    )
    output = tmp_path / "partial.json"

    result = runner.invoke(
        app,
        OPTIONS + ["api-keys", "--api-id", "denied-api", "--output", str(output)],
        terminal_width=240,
    )

    assert result.exit_code == 3
    assert "PARTIAL" in result.stdout and "denied-api" in result.stdout
    assert "access_denied" in result.stderr
    assert "private-service-diagnostic" not in result.output
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["complete"] is False
    assert document["rows"][0]["keys_complete"] is False
    assert document["errors"][0]["code"] == "AccessDeniedException"


@pytest.mark.parametrize("denied", [False, True])
def test_api_keys_empty_default_table_distinguishes_no_resources_from_denial(services, denied):
    _, _, stubs = services
    identity_response(stubs)
    if denied:
        stubs["appsync", REGION].add_client_error(
            "list_graphql_apis", "AccessDeniedException", expected_params={}
        )
    else:
        stubs["appsync", REGION].add_response("list_graphql_apis", {"graphqlApis": []}, {})

    result = runner.invoke(app, OPTIONS + ["api-keys"], terminal_width=240)

    assert result.exit_code == (3 if denied else 0)
    if denied:
        assert "PARTIAL" in result.stdout and "No rows retrieved." in result.stdout
    else:
        assert "COMPLETE" in result.stdout
        assert "No matching resources/costs found." in result.stdout


def queue_retry_preflight(stubs):
    stub = stubs["amplify", REGION]
    stub.add_response("get_app", {"app": app_response()}, {"appId": "d123"})
    stub.add_response(
        "get_branch",
        {"branch": {**branch_response("dev"), "stage": "DEVELOPMENT"}},
        {"appId": "d123", "branchName": "dev"},
    )
    stub.add_response(
        "get_job",
        {"job": {"summary": job_response("1", status="FAILED"), "steps": []}},
        {"appId": "d123", "branchName": "dev", "jobId": "1"},
    )
    stub.add_response("list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": "dev"})


def test_reviewed_deploy_cli_submits_mocked_retry_and_renders_receipt(harness, tmp_path):
    _, session, stubs = harness
    identity_response(stubs)
    access = AwsAccess.connect("brewmaster", ACCOUNT, REGION)
    queue_retry_preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    envelope = Report(access.identity, "deployment_plan", plan.created_at, [REGION])
    envelope.rows.append(plan)
    path = tmp_path / "plan.json"
    path.write_text(json_report(envelope), encoding="utf-8")
    identity_response(stubs)
    queue_retry_preflight(stubs)
    stubs["amplify", REGION].add_response(
        "start_job",
        {"jobSummary": job_response("2", status="PENDING")},
        {"appId": "d123", "branchName": "dev", "jobId": "1", "jobType": "RETRY"},
    )
    audit_dir = tmp_path / "audit"
    output = tmp_path / "receipt.json"

    result = runner.invoke(
        app,
        OPTIONS
        + [
            "deploy",
            "--plan",
            str(path),
            "--confirm-plan",
            plan.plan_id,
            "--audit-dir",
            str(audit_dir),
            "--output",
            str(output),
        ],
        terminal_width=240,
    )

    assert result.exit_code == 0, result.output
    assert "COMPLETE" in result.stdout
    assert "PENDING" in result.stdout and "submitted" in result.stdout
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["complete"] is True
    assert document["rows"][0]["job_id"] == "2"
    assert document["rows"][0]["plan_id"] == plan.plan_id
    assert (audit_dir / (plan.plan_id + ".jsonl")).exists()
    assert session.client.call_args.kwargs["config"].retries["total_max_attempts"] == 1
    for sensitive in ("private-commit-message", "app-secret", "branch-basic-auth"):
        assert sensitive not in result.output
        assert sensitive not in output.read_text(encoding="utf-8")
