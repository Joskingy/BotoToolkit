import json
from datetime import timedelta
from http.client import HTTPResponse
from io import BytesIO
from unittest.mock import Mock

import pytest
from conftest import ACCOUNT, NOW, REGION, identity_response, job_response
from typer.testing import CliRunner

from amplify_ops.cli import app
from amplify_ops.logs import MAX_LOG_BYTES, LogReadFailure, download_log

runner = CliRunner()
OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
TARGET = ["investigate", "--app-id", "d123", "--branch", "feature/preview"]
PARAMS = {"appId": "d123", "branchName": "feature/preview"}
URL = "https://bucket.s3.us-east-1.amazonaws.com/log?X-Amz-Signature=private-url-signature"


def step(name="BUILD", status="FAILED", **extra):
    return {
        "stepName": name,
        "startTime": NOW,
        "endTime": NOW + timedelta(minutes=1),
        "status": status,
        "statusReason": "ENV_SECRET=do-not-export",
        "context": "private-context",
        "logUrl": URL,
        "artifactsUrl": "https://private-artifacts",
        "screenshots": {"test": "private-screen"},
        **extra,
    }


def details(job_id="1", status="FAILED", steps=None):
    return {
        "job": {
            "summary": job_response(job_id, status=status),
            "steps": [step()] if steps is None else steps,
        }
    }


def add_job(stubs, job_id="1", status="FAILED", steps=None):
    stubs["amplify", REGION].add_response(
        "get_job",
        details(job_id, status, steps),
        {**PARAMS, "jobId": job_id},
    )


def run_json(*args):
    return runner.invoke(app, OPTIONS + TARGET + list(args) + ["--format", "json"])


def stub_log(
    monkeypatch,
    content=b"npm ERR! code ERESOLVE secret=private-log-value\n",
    status=200,
    encoding="identity",
):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = status
    response.length = None
    response.getheader.return_value = encoding
    response.read1.side_effect = BytesIO(content).read1
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr("amplify_ops.logs.HTTPSConnection", factory)
    return factory, connection, response


def stub_http_log(monkeypatch, content, content_length):
    headers = b"HTTP/1.1 200 OK\r\n"
    if content_length is not None:
        headers += f"Content-Length: {content_length}\r\n".encode("ascii")
    socket = Mock()
    socket.makefile.return_value = BytesIO(headers + b"\r\n" + content)
    response = HTTPResponse(socket)
    response.begin()
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr("amplify_ops.logs.HTTPSConnection", Mock(return_value=connection))
    return connection


def test_selects_latest_failed_across_unordered_pages(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response(
        "list_jobs",
        {
            "jobSummaries": [
                job_response("100", NOW + timedelta(days=5), "SUCCEED"),
                job_response("1", NOW - timedelta(days=1), "FAILED"),
            ],
            "nextToken": "next",
        },
        PARAMS,
    )
    stub.add_response(
        "list_jobs",
        {
            "jobSummaries": [
                job_response("2", NOW, "FAILED"),
                job_response("3", NOW + timedelta(days=1), "CANCELLED"),
            ]
        },
        {**PARAMS, "nextToken": "next"},
    )
    add_job(stubs, "2")
    result = run_json()
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["job"]["job_id"] == "2"
    assert report["selection"] == "latest_failed"
    assert report["steps"][0]["status"] == "FAILED"
    assert report["steps"][0]["log"]["state"] == "not_requested"
    assert "BUILD" in report["observations"][0]


def test_explicit_job_bypasses_listing_and_exports_no_sensitive_fields(harness, tmp_path):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs, "17", "SUCCEED", [step(status="SUCCEED")])
    target = tmp_path / "investigation.json"
    result = run_json("--job-id", "17", "--output", str(target))
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document == json.loads(target.read_text(encoding="utf-8"))
    assert document["complete"] is True
    assert document["selection"] == "explicit_job"
    for secret in (
        "statusReason",
        "context",
        "logUrl",
        "artifactsUrl",
        "screenshots",
        "private-",
        "ENV_SECRET",
        "do-not-export",
        "commitMessage",
    ):
        assert secret not in result.output
        assert secret not in target.read_text(encoding="utf-8")


def test_no_failed_jobs_is_complete_and_needs_no_get_job(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_response(
        "list_jobs",
        {"jobSummaries": [job_response(status="SUCCEED")]},
        PARAMS,
    )
    result = run_json()
    report = json.loads(result.stdout)
    assert result.exit_code == 0 and report["complete"]
    assert report["job"] is None
    assert "No failed jobs" in report["observations"][0]


def test_failed_history_page_does_not_guess_latest(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response(
        "list_jobs", {"jobSummaries": [job_response(status="FAILED")], "nextToken": "next"}, PARAMS
    )
    stub.add_client_error(
        "list_jobs", "UnauthorizedException", expected_params={**PARAMS, "nextToken": "next"}
    )
    result = run_json()
    assert result.exit_code == 3
    report = json.loads(result.stdout)
    assert not report["complete"] and report["job"] is None
    assert report["errors"][0]["operation"] == "list_jobs"


@pytest.mark.parametrize("code", ["UnauthorizedException", "NotFoundException"])
def test_get_job_failure_is_incomplete_and_safe(harness, code):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_client_error(
        "get_job", code, "secret-service-message", expected_params={**PARAMS, "jobId": "1"}
    )
    result = run_json("--job-id", "1")
    assert result.exit_code == 3
    assert json.loads(result.stdout)["errors"][0]["code"] == code
    assert "secret-service-message" not in result.output


def test_identity_mismatch_blocks_job_and_logs(harness):
    _, session, stubs = harness
    identity_response(stubs, "000000000000")
    result = run_json("--job-id", "1", "--inspect-logs")
    assert result.exit_code == 1 and result.stdout == ""
    assert session.client.call_count == 1


def test_get_job_auth_failure_emits_no_report(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_client_error(
        "get_job", "ExpiredTokenException", expected_params={**PARAMS, "jobId": "1"}
    )
    result = run_json("--job-id", "1", "--inspect-logs")
    assert result.exit_code == 1 and result.stdout == ""
    assert "authentication failed" in result.stderr


def test_log_inspection_exports_fixed_clues_and_line_numbers(harness, monkeypatch):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs)
    factory, connection, _ = stub_log(
        monkeypatch,
        b"SECRET=unknown-format-secret\n"
        b"npm ERR! code ERESOLVE token=another-secret\nCannot find module private-module\n",
    )
    result = run_json("--job-id", "1", "--inspect-logs")
    assert result.exit_code == 0, result.output
    review = json.loads(result.stdout)["steps"][0]["log"]
    assert [(item["line"], item["category"]) for item in review["findings"]] == [
        (2, "dependency_conflict"),
        (3, "missing_module"),
    ]
    assert review["state"] == "inspected" and review["lines_scanned"] == 3
    assert "unknown-format-secret" not in result.output
    assert "another-secret" not in result.output and "private-module" not in result.output
    assert "private-url-signature" not in result.output
    factory.assert_called_once_with("bucket.s3.us-east-1.amazonaws.com", timeout=5)
    assert connection.request.call_args.args[0] == "GET"
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "log_url",
    [
        "http://bucket.s3.amazonaws.com/log",
        "https://127.0.0.1/log",
        "https://169.254.169.254/latest/meta-data",
        "https://s3.amazonaws.com.attacker.test/log",
        "https://evil.test/log",
        "file:///secret",
        "https://user:secret@s3.amazonaws.com/log",
        "https://s3.amazonaws.com:8443/log",
        "https://s3.amazonaws.com/log\r\nX-Secret: value",
    ],
)
def test_unsafe_log_urls_rejected_before_connection(monkeypatch, log_url):
    factory = Mock()
    monkeypatch.setattr("amplify_ops.logs.HTTPSConnection", factory)
    with pytest.raises(LogReadFailure, match="UnsupportedLogURL"):
        download_log(log_url)
    factory.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 403, 404, 500])
def test_log_http_errors_and_redirects_are_not_followed(monkeypatch, status):
    factory, connection, response = stub_log(monkeypatch, status=status)
    with pytest.raises(LogReadFailure, match=f"LogHTTP{status}"):
        download_log(URL)
    assert factory.call_count == 1 and connection.request.call_count == 1
    response.read1.assert_not_called()
    connection.close.assert_called_once()


def test_truncated_log_marks_report_incomplete(harness, monkeypatch):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs)
    stub_log(monkeypatch, b"x" * (MAX_LOG_BYTES + 100))
    result = run_json("--job-id", "1", "--inspect-logs")
    report = json.loads(result.stdout)
    assert result.exit_code == 3 and not report["complete"]
    assert report["steps"][0]["log"]["truncated"]
    assert report["steps"][0]["log"]["bytes_read"] == MAX_LOG_BYTES


def test_log_request_count_is_bounded(harness, monkeypatch):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs, steps=[step()] * 5)
    factory, _, _ = stub_log(monkeypatch, b"build failed\n")
    result = run_json("--job-id", "1", "--inspect-logs")
    report = json.loads(result.stdout)
    assert result.exit_code == 3 and factory.call_count == 4
    assert report["errors"][0]["code"] == "LogCountLimit"


def test_missing_log_keeps_step_evidence_with_partial_report(harness):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs, steps=[step(logUrl="")])
    result = run_json("--job-id", "1", "--inspect-logs")
    report = json.loads(result.stdout)
    assert result.exit_code == 3
    assert report["steps"][0]["status"] == "FAILED"
    assert report["steps"][0]["log"]["state"] == "unavailable"
    assert report["errors"][0]["code"] == "LogUnavailable"


def test_compressed_log_is_rejected(monkeypatch):
    _, _, response = stub_log(monkeypatch, encoding="gzip")
    with pytest.raises(LogReadFailure, match="UnsupportedLogEncoding"):
        download_log(URL)
    response.read1.assert_not_called()


def test_log_connection_error_does_not_leak_url(monkeypatch):
    _, connection, _ = stub_log(monkeypatch)
    connection.request.side_effect = OSError(URL)
    with pytest.raises(LogReadFailure) as error:
        download_log(URL)
    assert str(error.value) == "LogConnectionFailure"


@pytest.mark.parametrize("content_length", [None, 9])
def test_complete_http_log_with_known_or_unknown_length(monkeypatch, content_length):
    content = b"ERESOLVE\n"
    connection = stub_http_log(monkeypatch, content, content_length)
    assert download_log(URL) == (content, False)
    connection.close.assert_called_once()


def test_early_http_eof_rejects_incomplete_log(monkeypatch):
    connection = stub_http_log(monkeypatch, b"ERESOLVE\n", 100)
    with pytest.raises(LogReadFailure, match="^LogIncompleteBody$"):
        download_log(URL)
    connection.close.assert_called_once()


def test_early_http_eof_keeps_job_evidence_and_marks_report_partial(harness, monkeypatch):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs)
    stub_http_log(monkeypatch, b"ERESOLVE private-log-value\n", 100)
    result = run_json("--job-id", "1", "--inspect-logs")
    report = json.loads(result.stdout)
    assert result.exit_code == 3 and not report["complete"]
    assert report["job"]["status"] == "FAILED"
    assert report["steps"][0]["status"] == "FAILED"
    assert report["steps"][0]["log"]["state"] == "unavailable"
    assert report["errors"][0]["code"] == "LogIncompleteBody"
    assert "private-log-value" not in result.output
    assert "private-url-signature" not in result.output


def test_log_deadline_is_enforced(monkeypatch):
    _, _, response = stub_log(monkeypatch)
    clock = Mock(side_effect=[0, 16])
    monkeypatch.setattr("amplify_ops.logs.monotonic", clock)
    with pytest.raises(LogReadFailure, match="LogTimeLimit"):
        download_log(URL)
    response.read1.assert_not_called()


def test_multiregion_investigation_rejected_before_identity(harness):
    factory, _, _ = harness
    result = runner.invoke(app, OPTIONS + ["--region", "us-west-2"] + TARGET)
    assert result.exit_code == 2
    factory.assert_not_called()


def test_table_has_failed_step_and_withholds_reason(harness):
    _, _, stubs = harness
    identity_response(stubs)
    add_job(stubs)
    result = runner.invoke(app, OPTIONS + TARGET + ["--job-id", "1"])
    assert result.exit_code == 0
    assert "BUILD" in result.stdout and "FAILED" in result.stdout
    assert "ENV_SECRET" not in result.output


def test_live_shape_with_missing_step_timestamps(harness):
    _, _, stubs = harness
    identity_response(stubs)
    response = details(steps=[step(), step("DEPLOY", "PENDING")])
    stubs["amplify", REGION].add_response("get_job", response, {**PARAMS, "jobId": "1"})
    # The SDK model requires these fields, but live GetJob omits them on some
    # steps. Change the queued response after model validation to reproduce it.
    for item in response["job"]["steps"]:
        item.pop("startTime")
        item.pop("endTime")
    result = run_json("--job-id", "1")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["complete"]
    assert report["steps"][0]["start_time"] is None
    assert report["steps"][1]["end_time"] is None
