import json
import subprocess
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import (
    ACCOUNT,
    NOW,
    REGION,
    app_response,
    branch_response,
    identity_response,
    job_response,
)

from amplify_ops.aws import AwsAccess
from amplify_ops.github import GitHubReadFailure, RepositoryEvidence, repository_evidence
from amplify_ops.stale import stale_environments


def test_github_pagination_and_fork_pr_separation(monkeypatch):
    first = [{"name": f"branch-{i}"} for i in range(100)]
    values = [
        first,
        [{"name": "feature/final"}],
        [
            {"branch": "feature/final", "repo": "org/repo"},
            {"branch": "feature/fork", "repo": "fork/repo"},
        ],
    ]
    run = Mock(
        side_effect=[SimpleNamespace(returncode=0, stdout=json.dumps(value)) for value in values]
    )
    monkeypatch.setattr("amplify_ops.github.run_command", run)
    evidence = repository_evidence("org/repo")
    assert len(evidence.branches) == 101
    assert evidence.open_pr_heads == ["feature/final"]
    assert "page=2" in run.call_args_list[1].args[0][6]
    for call in run.call_args_list:
        args = call.args[0]
        assert args[:6] == ["gh", "api", "--hostname", "github.com", "--method", "GET"]


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="private-error"),
        SimpleNamespace(returncode=0, stdout="not-json"),
    ],
)
def test_github_denied_or_invalid_is_unknown(monkeypatch, result):
    monkeypatch.setattr("amplify_ops.github.run_command", Mock(return_value=result))
    with pytest.raises(GitHubReadFailure) as error:
        repository_evidence("org/repo")
    assert "private-error" not in str(error.value)


@pytest.mark.parametrize(
    "diagnostic,code",
    [
        ("HTTP 401 private-token", "GitHubAuthenticationRequired"),
        ("run gh auth login private-token", "GitHubAuthenticationRequired"),
        ("HTTP 403 private-token", "GitHubAccessDenied"),
        ("HTTP 404 private-token", "GitHubRepositoryUnavailable"),
        ("HTTP 429 private-token", "GitHubRateLimited"),
        ("HTTP 403 secondary rate limit private-token", "GitHubRateLimited"),
    ],
)
def test_github_safe_actionable_errors(monkeypatch, diagnostic, code):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr=diagnostic))
    monkeypatch.setattr("amplify_ops.github.run_command", run)
    with pytest.raises(GitHubReadFailure, match=f"^{code}$"):
        repository_evidence("org/repo")
    assert run.call_count == 1  # No blind rate-limit or access-denied retry.


@pytest.mark.parametrize(
    "error,code",
    [
        (FileNotFoundError(), "GitHubCliMissing"),
        (subprocess.TimeoutExpired("gh", 20), "GitHubTimeout"),
    ],
)
def test_github_process_failures(monkeypatch, error, code):
    monkeypatch.setattr("amplify_ops.github.run_command", Mock(side_effect=error))
    with pytest.raises(GitHubReadFailure, match=code):
        repository_evidence("org/repo")


@pytest.mark.parametrize(
    "branches,pulls",
    [
        ([{"name": None}], []),
        ([{"name": "same"}, {"name": "same"}], []),
        ([], [{"branch": None, "repo": "org/repo"}]),
        ([], [{"branch": "main", "repo": []}]),
        ([], [{"branch": "main"}]),
    ],
)
def test_invalid_evidence_never_establishes_absence(monkeypatch, branches, pulls):
    monkeypatch.setattr("amplify_ops.github.read_pages", Mock(side_effect=[branches, pulls]))
    with pytest.raises(GitHubReadFailure, match="GitHubInvalidResponse"):
        repository_evidence("org/repo")


def test_deleted_fork_and_explicit_request_controls(monkeypatch):
    monkeypatch.setenv("GH_DEBUG", "api")
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    run = Mock(
        side_effect=[
            SimpleNamespace(returncode=0, stdout='[{"name":"main"}]'),
            SimpleNamespace(returncode=0, stdout='[{"branch":"gone","repo":null}]'),
        ]
    )
    monkeypatch.setattr("amplify_ops.github.run_command", run)
    result = repository_evidence("org/repo")
    assert result.branches == {"main"} and result.open_pr_heads == []
    assert "state=open" in run.call_args_list[1].args[0][6]
    for call in run.call_args_list:
        assert "X-GitHub-Api-Version: 2022-11-28" in call.args[0]
        assert "GH_DEBUG" not in call.kwargs["env"]
        assert call.kwargs["env"]["GH_PROMPT_DISABLED"] == "1"
        assert call.kwargs["env"]["GH_TOKEN"] == "synthetic-token"


@pytest.mark.parametrize("repository", ["org/repo?x=y", "org/..", "org/repo/other"])
def test_repository_input_rejected_before_process(monkeypatch, repository):
    run = Mock()
    monkeypatch.setattr("amplify_ops.github.run_command", run)
    with pytest.raises(GitHubReadFailure, match="GitHubInvalidRepository"):
        repository_evidence(repository)
    run.assert_not_called()


def seed(stubs, branches):
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response(
        "get_app",
        {"app": app_response(repository="https://github.com/org/repo.git")},
        {"appId": "d123"},
    )
    stub.add_response("list_branches", {"branches": branches}, {"appId": "d123"})
    return stub


def old_branch(name, **extra):
    return {
        **branch_response(name),
        "stage": "DEVELOPMENT",
        "createTime": NOW - timedelta(days=200),
        "updateTime": NOW - timedelta(days=100),
        **extra,
    }


def test_stale_protection_candidates_existing_branches_and_prs(harness, monkeypatch):
    _, _, stubs = harness
    names = ["main", "dev", "feature/deleted", "feature/present", "feature/pr", "production-other"]
    branches = [old_branch(name) for name in names]
    branches[-1]["stage"] = "PRODUCTION"
    branches[2]["backendEnvironmentArn"] = (
        "arn:aws:amplify:us-east-1:111122223333:apps/d123/backendenvironments/old"
    )
    stub = seed(stubs, branches)
    for name in names:
        stub.add_response("list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": name})
    monkeypatch.setattr(
        "amplify_ops.stale.repository_evidence",
        lambda repo: RepositoryEvidence({"main", "dev", "feature/present"}, ["feature/pr"]),
    )
    report = stale_environments(
        AwsAccess.connect("brewmaster", ACCOUNT, REGION), REGION, "d123", "org/repo", 90, now=NOW
    )
    assert report.complete
    rows = {row.branch: row for row in report.rows}
    assert rows["main"].classification == rows["dev"].classification == "protected"
    assert rows["production-other"].classification == "protected"
    assert rows["feature/deleted"].classification == "review_candidate"
    assert rows["feature/deleted"].confidence == "medium"
    assert rows["feature/deleted"].backend_association_present
    assert rows["feature/present"].classification == "old_but_unproven"
    assert rows["feature/pr"].classification == "active"


def test_recent_branch_config_and_active_jobs_prevent_candidates(harness, monkeypatch):
    _, _, stubs = harness
    stub = seed(stubs, [old_branch("feature/recent", updateTime=NOW), old_branch("feature/active")])
    stub.add_response(
        "list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": "feature/recent"}
    )
    stub.add_response(
        "list_jobs",
        {"jobSummaries": [job_response(start=NOW - timedelta(days=100), status="RUNNING")]},
        {"appId": "d123", "branchName": "feature/active"},
    )
    monkeypatch.setattr(
        "amplify_ops.stale.repository_evidence", lambda repo: RepositoryEvidence(set(), [])
    )
    report = stale_environments(
        AwsAccess.connect("brewmaster", ACCOUNT, REGION), REGION, "d123", "org/repo", 90, now=NOW
    )
    assert [row.classification for row in report.rows] == ["recent", "active"]


def test_missing_github_evidence_never_means_deleted(harness, monkeypatch):
    _, _, stubs = harness
    stub = seed(stubs, [old_branch("feature/unknown")])
    stub.add_response(
        "list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": "feature/unknown"}
    )
    monkeypatch.setattr(
        "amplify_ops.stale.repository_evidence",
        Mock(side_effect=GitHubReadFailure("GitHubUnavailable")),
    )
    report = stale_environments(
        AwsAccess.connect("brewmaster", ACCOUNT, REGION), REGION, "d123", "org/repo", 90, now=NOW
    )
    assert not report.complete
    assert report.rows[0].classification == report.rows[0].github_branch == "unknown"


def test_job_read_failure_never_means_no_activity(harness, monkeypatch):
    _, _, stubs = harness
    stub = seed(stubs, [old_branch("feature/unknown")])
    stub.add_client_error(
        "list_jobs",
        "UnauthorizedException",
        expected_params={"appId": "d123", "branchName": "feature/unknown"},
    )
    monkeypatch.setattr(
        "amplify_ops.stale.repository_evidence", lambda repo: RepositoryEvidence(set(), [])
    )
    report = stale_environments(
        AwsAccess.connect("brewmaster", ACCOUNT, REGION), REGION, "d123", "org/repo", 90, now=NOW
    )
    assert not report.complete and report.rows[0].classification == "unknown"


def test_repository_mismatch_blocks_github_and_branch_reads(harness, monkeypatch):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_response("get_app", {"app": app_response()}, {"appId": "d123"})
    github = Mock()
    monkeypatch.setattr("amplify_ops.stale.repository_evidence", github)
    report = stale_environments(
        AwsAccess.connect("brewmaster", ACCOUNT, REGION),
        REGION,
        "d123",
        "different/repo",
        90,
        now=NOW,
    )
    assert not report.complete and report.errors[0].code == "RepositoryMismatch"
    github.assert_not_called()
