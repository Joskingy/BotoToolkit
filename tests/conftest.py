"""Stubber exercises real SDK shapes and pagination; network is forbidden."""

import os
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import Mock

import boto3
import pytest
from botocore.endpoint import Endpoint
from botocore.stub import Stubber

ACCOUNT = "111122223333"
REGION = "us-east-1"
OTHER_REGION = "us-west-2"
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
ARN = f"arn:aws:iam::{ACCOUNT}:user/test"


@pytest.fixture(autouse=True)
def isolate_external_configuration(monkeypatch, tmp_path_factory):
    """Never load a developer's credentials, providers, Git hooks, or signing settings."""
    configuration = tmp_path_factory.mktemp("external-configuration")
    for name in tuple(os.environ):
        if name.startswith(("AWS_", "GIT_")) or name == "BOTO_CONFIG":
            monkeypatch.delenv(name)
    for name, filename in (
        ("AWS_CONFIG_FILE", "aws-config"),
        ("AWS_SHARED_CREDENTIALS_FILE", "aws-credentials"),
        ("BOTO_CONFIG", "boto-config"),
    ):
        target = configuration / filename
        target.write_text("", encoding="utf-8")
        monkeypatch.setenv(name, str(target))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    template = configuration / "git-template"
    (template / "hooks").mkdir(parents=True)
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch, isolate_external_configuration):
    def fail(*args, **kwargs):
        pytest.fail("Tests must not make network calls")

    monkeypatch.setattr(Endpoint, "_send", fail)
    monkeypatch.setattr("socket.create_connection", fail)
    monkeypatch.setattr("socket.socket.connect", fail)
    monkeypatch.setattr("socket.socket.connect_ex", fail)
    monkeypatch.setattr("amplify_ops.github.run_command", fail)


@pytest.fixture
def harness(monkeypatch):
    # Literal fake credentials plus isolated configuration avoid real providers.
    real = boto3.Session(
        aws_access_key_id="testing", aws_secret_access_key="testing", region_name=REGION
    )
    clients = {("sts", REGION): real.client("sts", region_name=REGION)}
    clients.update(
        {("amplify", r): real.client("amplify", region_name=r) for r in (REGION, OTHER_REGION)}
    )
    stubs = {key: Stubber(client) for key, client in clients.items()}
    session = Mock()
    session.client.side_effect = lambda service, *, region_name, config: clients[
        service, region_name
    ]
    factory = Mock(return_value=session)
    monkeypatch.setattr("amplify_ops.aws.boto3.Session", factory)
    with ExitStack() as stack:
        for stub in stubs.values():
            stack.enter_context(stub)
        yield factory, session, stubs
        for stub in stubs.values():
            stub.assert_no_pending_responses()


def identity_response(stubs, account=ACCOUNT):
    stubs["sts", REGION].add_response(
        "get_caller_identity", {"Account": account, "Arn": ARN, "UserId": "test"}, {}
    )


def app_response(app_id="d123", **extra):
    return {
        "appId": app_id,
        "appArn": f"arn:aws:amplify:{REGION}:{ACCOUNT}:apps/{app_id}",
        "name": "Test app",
        "description": "",
        "repository": "https://github.com/org/repo",
        "platform": "WEB",
        "createTime": NOW,
        "updateTime": NOW,
        "environmentVariables": {"SECRET": "app-secret"},
        "defaultDomain": f"{app_id}.amplifyapp.com",
        "enableBranchAutoBuild": False,
        "enableBasicAuth": True,
        "basicAuthCredentials": "sensitive-basic-auth",
        **extra,
    }


def branch_response(name="main"):
    return {
        "branchArn": f"arn:aws:amplify:{REGION}:{ACCOUNT}:apps/d123/branches/{name}",
        "branchName": name,
        "description": "",
        "stage": "PRODUCTION",
        "displayName": name,
        "enableNotification": False,
        "createTime": NOW,
        "updateTime": NOW,
        "environmentVariables": {"SECRET": "branch-secret"},
        "enableAutoBuild": False,
        "customDomains": [],
        "framework": "React",
        "activeJobId": "1",
        "totalNumberOfJobs": "1",
        "enableBasicAuth": True,
        "basicAuthCredentials": "branch-basic-auth",
        "ttl": "5",
        "enablePullRequestPreview": False,
    }


def job_response(job_id="1", start=NOW, status="SUCCEED", **extra):
    return {
        "jobArn": f"arn:aws:amplify:{REGION}:{ACCOUNT}:apps/d123/branches/main/jobs/{job_id}",
        "jobId": job_id,
        "commitId": "abc",
        "commitMessage": "private-commit-message",
        "commitTime": NOW,
        "startTime": start,
        "status": status,
        "jobType": "WEB_HOOK",
        **extra,
    }


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


@pytest.fixture
def services(harness):
    factory, session, stubs = harness
    real = boto3.session.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name=REGION,
    )
    with ExitStack() as stack:
        for service, region in [("appsync", REGION), ("appsync", OTHER_REGION), ("ce", REGION)]:
            stub = Stubber(real.client(service, region_name=region))
            stubs[service, region] = stub
            stack.enter_context(stub)
        session.client.side_effect = lambda service, *, region_name, config: (
            stubs[service, region_name].client
        )
        yield factory, session, stubs
