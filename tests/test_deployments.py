import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import (
    ACCOUNT,
    NOW,
    REGION,
    app_response,
    branch_response,
    identity_response,
    job_response,
)
from typer.testing import CliRunner

from amplify_ops.aws import AwsAccess
from amplify_ops.cli import app
from amplify_ops.deployments import (
    DeploymentBlocked,
    create_plan,
    execute_plan,
    load_plan,
    plan_digest,
)
from amplify_ops.models import DeploymentPlan, Report
from amplify_ops.presentation import json_report

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]


def connect(stubs):
    identity_response(stubs)
    return AwsAccess.connect("brewmaster", ACCOUNT, REGION)


def preflight(
    stubs,
    branch="dev",
    stage="DEVELOPMENT",
    update=NOW,
    commit="abc",
    active=False,
    source_status="FAILED",
):
    stub = stubs["amplify", REGION]
    stub.add_response("get_app", {"app": app_response()}, {"appId": "d123"})
    stub.add_response(
        "get_branch",
        {"branch": {**branch_response(branch), "stage": stage, "updateTime": update}},
        {"appId": "d123", "branchName": branch},
    )
    stub.add_response(
        "get_job",
        {"job": {"summary": job_response("1", status=source_status, commitId=commit), "steps": []}},
        {"appId": "d123", "branchName": branch, "jobId": "1"},
    )
    if source_status in {"FAILED", "SUCCEED", "CANCELLED"}:
        stub.add_response(
            "list_jobs",
            {"jobSummaries": [job_response("3", status="RUNNING")] if active else []},
            {"appId": "d123", "branchName": branch},
        )


def write_plan(path, plan, access):
    report = Report(access.identity, "deployment_plan", plan.created_at, [REGION])
    report.rows.append(plan)
    path.write_text(json_report(report), encoding="utf-8")


def test_plan_is_read_only_and_loadable(harness, tmp_path):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    assert plan.action == "RETRY" and not plan.production
    assert plan.source_commit_id == "abc"
    path = tmp_path / "plan.json"
    write_plan(path, plan, access)
    assert load_plan(path) == plan
    assert session.client.call_count == 2


@pytest.mark.parametrize("branch,stage", [("main", "DEVELOPMENT"), ("release", "PRODUCTION")])
def test_production_detection_and_confirmation_before_preflight(harness, tmp_path, branch, stage):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs, branch, stage)
    plan = create_plan(access, REGION, "d123", branch, "1")
    assert plan.production
    count = session.client.call_count
    with pytest.raises(DeploymentBlocked, match="Production"):
        execute_plan(access, plan, plan.plan_id, None, tmp_path)
    assert session.client.call_count == count


@pytest.mark.parametrize("active,source_status", [(True, "FAILED"), (False, "RUNNING")])
def test_active_jobs_cannot_be_planned(harness, active, source_status):
    _, _, stubs = harness
    access = connect(stubs)
    preflight(stubs, active=active, source_status=source_status)
    with pytest.raises(DeploymentBlocked):
        create_plan(access, REGION, "d123", "dev", "1")


def test_exact_retry_submission_and_audit(harness, tmp_path):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    preflight(stubs)
    stubs["amplify", REGION].add_response(
        "start_job",
        {"jobSummary": job_response("2", status="PENDING")},
        {"appId": "d123", "branchName": "dev", "jobId": "1", "jobType": "RETRY"},
    )
    report = execute_plan(access, plan, plan.plan_id, None, tmp_path)
    assert report.complete and report.rows[0].job_id == "2"
    audit = [
        json.loads(line) for line in (tmp_path / (plan.plan_id + ".jsonl")).read_text().splitlines()
    ]
    assert [row["event"] for row in audit] == ["submitting", "submitted"]
    assert all(row["account_id"] == ACCOUNT and row["branch"] == "dev" for row in audit)
    assert session.client.call_args.kwargs["config"].retries["total_max_attempts"] == 1
    preflight(stubs)
    with pytest.raises(DeploymentBlocked, match="consumed"):
        execute_plan(access, plan, plan.plan_id, None, tmp_path)


@pytest.mark.parametrize("change", ["time", "commit", "production"])
def test_target_drift_blocks_write(harness, tmp_path, change):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    preflight(
        stubs,
        update=NOW + timedelta(minutes=1) if change == "time" else NOW,
        commit="different" if change == "commit" else "abc",
        stage="PRODUCTION" if change == "production" else "DEVELOPMENT",
    )
    with pytest.raises(DeploymentBlocked, match="changed"):
        execute_plan(access, plan, plan.plan_id, None, tmp_path)
    assert session.client.call_count == 3
    assert not list(tmp_path.iterdir())


def test_missing_or_wrong_confirmation_never_writes(harness, tmp_path):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    with pytest.raises(DeploymentBlocked, match="confirm-plan"):
        execute_plan(access, plan, "wrong", None, tmp_path)
    assert session.client.call_count == 2


def test_modified_and_expired_plan_files_rejected(harness, tmp_path):
    _, _, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    path = tmp_path / "plan.json"
    write_plan(path, replace(plan, branch="main"), access)
    with pytest.raises(DeploymentBlocked):
        load_plan(path)
    write_plan(path, plan, access)
    with pytest.raises(DeploymentBlocked):
        load_plan(path, now=datetime.now(UTC) + timedelta(minutes=16))


def test_audit_unavailable_prevents_start_job(harness, tmp_path):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    preflight(stubs)
    target = tmp_path / "not-a-directory"
    target.write_text("keep")
    with pytest.raises(DeploymentBlocked, match="Audit"):
        execute_plan(access, plan, plan.plan_id, None, target)
    assert session.client.call_count == 3


def test_uncertain_submission_is_claimed_and_not_retried(harness, tmp_path, monkeypatch):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    preflight(stubs)
    client = stubs["amplify", REGION].client
    start = Mock(side_effect=EndpointConnectionError(endpoint_url="private-endpoint"))
    monkeypatch.setattr(client, "start_job", start)
    report = execute_plan(access, plan, plan.plan_id, None, tmp_path)
    assert not report.complete and start.call_count == 1
    assert (tmp_path / (plan.plan_id + ".jsonl")).exists()
    assert "private-endpoint" not in json_report(report)
    assert session.client.call_args.kwargs["config"].retries["total_max_attempts"] == 1


def test_cli_rejects_invalid_plan_before_aws(harness, tmp_path):
    factory, _, _ = harness
    path = tmp_path / "invalid.json"
    path.write_text("{}")
    result = runner.invoke(app, OPTIONS + ["deploy", "--plan", str(path), "--confirm-plan", "x"])
    assert result.exit_code == 1
    factory.assert_not_called()


def test_cli_rejects_expired_plan_before_aws(harness, tmp_path):
    factory, _, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(
        access,
        REGION,
        "d123",
        "dev",
        "1",
        now=datetime.now(UTC) - timedelta(minutes=16),
    )
    path = tmp_path / "expired.json"
    write_plan(path, plan, access)
    factory.reset_mock()

    result = runner.invoke(
        app, OPTIONS + ["deploy", "--plan", str(path), "--confirm-plan", plan.plan_id]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "expired" in result.stderr
    factory.assert_not_called()


def test_job_appearing_after_plan_blocks_execution(harness, tmp_path):
    _, session, stubs = harness
    access = connect(stubs)
    preflight(stubs)
    plan = create_plan(access, REGION, "d123", "dev", "1")
    preflight(stubs, active=True)
    with pytest.raises(DeploymentBlocked, match="active job"):
        execute_plan(access, plan, plan.plan_id, None, tmp_path)
    assert session.client.call_count == 3
    assert not list(tmp_path.iterdir())


def plan_document(**changes):
    now = datetime.now(UTC)
    data = {
        "account_id": ACCOUNT,
        "region": REGION,
        "app_id": "d123",
        "branch": "dev",
        "stage": "DEVELOPMENT",
        "action": "RETRY",
        "source_job_id": "1",
        "source_commit_id": "abc",
        "branch_updated_at": NOW.isoformat(),
        "production": False,
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=14)).isoformat(),
        **changes,
    }
    data["plan_id"] = plan_digest(data)
    return {"report_type": "deployment_plan", "schema_version": 1, "complete": True, "rows": [data]}


@pytest.mark.parametrize(
    "change",
    [
        {"app_id": ["d123"]},
        {"region": [REGION]},
        {"source_job_id": None},
        {"source_job_id": "unresolved"},
        {"source_commit_id": {}},
        {"stage": None},
        {"branch_updated_at": None},
        {"created_at": []},
        {"production": 1},
    ],
)
def test_cli_refuses_malformed_plan_fields_with_valid_digest_before_aws(harness, tmp_path, change):
    factory, _, _ = harness
    document = plan_document(**change)
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = runner.invoke(
        app,
        OPTIONS + ["deploy", "--plan", str(path), "--confirm-plan", document["rows"][0]["plan_id"]],
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Plan is invalid" in result.stderr
    assert isinstance(result.exception, SystemExit)
    factory.assert_not_called()


@pytest.mark.parametrize("change", [{"schema_version": True}, {"complete": "false"}])
def test_plan_envelope_requires_exact_types(tmp_path, change):
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps({**plan_document(), **change}), encoding="utf-8")
    with pytest.raises(DeploymentBlocked):
        load_plan(path)


def test_plan_loader_rejects_invalid_text_with_safe_error(tmp_path):
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe-not-json")
    with pytest.raises(DeploymentBlocked, match="unreadable"):
        load_plan(path)


def test_valid_plan_envelope_remains_loadable(tmp_path):
    document = plan_document()
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_plan(path) == DeploymentPlan(**document["rows"][0])


def test_deeply_nested_plan_refused_safely_before_aws(harness, tmp_path):
    factory, _, _ = harness
    path = tmp_path / "nested.json"
    path.write_text("[" * 20000 + "0" + "]" * 20000, encoding="utf-8")
    result = runner.invoke(app, OPTIONS + ["deploy", "--plan", str(path), "--confirm-plan", "x"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Plan is invalid" in result.stderr
    assert isinstance(result.exception, SystemExit)
    factory.assert_not_called()
