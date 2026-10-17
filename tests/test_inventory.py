from datetime import timedelta

import pytest
from conftest import (
    ACCOUNT,
    NOW,
    OTHER_REGION,
    REGION,
    app_response,
    branch_response,
    identity_response,
    job_response,
)

from amplify_ops.aws import AuthenticationFailure, AwsAccess
from amplify_ops.inventory import collect_inventory


def connect():
    return AwsAccess.connect("brewmaster", ACCOUNT, REGION)


def test_wrong_account_blocks_amplify_clients(harness):
    factory, session, stubs = harness
    identity_response(stubs, "000000000000")
    with pytest.raises(AuthenticationFailure, match="Account mismatch"):
        connect()
    factory.assert_called_once_with(profile_name="brewmaster", region_name=REGION)
    assert [call.args[0] for call in session.client.call_args_list] == ["sts"]


def test_sts_failure_blocks_inventory_without_leaking_service_message(harness):
    _, session, stubs = harness
    stubs["sts", REGION].add_client_error(
        "get_caller_identity", "ExpiredToken", "private-service-message", expected_params={}
    )
    with pytest.raises(AuthenticationFailure, match="ExpiredToken") as error:
        connect()
    assert "private-service-message" not in str(error.value)
    assert session.client.call_count == 1


def test_paginates_apps_branches_and_jobs_and_chooses_latest(harness):
    _, session, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("list_apps", {"apps": [app_response()], "nextToken": "apps2"}, {})
    stub.add_response(
        "list_branches", {"branches": [branch_response()], "nextToken": "b2"}, {"appId": "d123"}
    )
    # Deliberately shuffled. Commit and end times must not decide which run is latest.
    stub.add_response(
        "list_jobs",
        {
            "jobSummaries": [
                job_response("9", NOW - timedelta(days=1), endTime=NOW + timedelta(days=2)),
                job_response("2", NOW + timedelta(hours=1), "RUNNING"),
            ],
            "nextToken": "jobs2",
        },
        {"appId": "d123", "branchName": "main"},
    )
    stub.add_response(
        "list_jobs",
        {"jobSummaries": [job_response("100", NOW)]},
        {"appId": "d123", "branchName": "main", "nextToken": "jobs2"},
    )
    stub.add_response(
        "list_branches",
        {"branches": [branch_response("dev")]},
        {"appId": "d123", "nextToken": "b2"},
    )
    stub.add_response("list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": "dev"})
    stub.add_response("list_apps", {"apps": [app_response("d456")]}, {"nextToken": "apps2"})
    stub.add_response("list_branches", {"branches": []}, {"appId": "d456"})
    report = collect_inventory(connect(), [REGION])
    assert report.complete
    assert [app.app_id for app in report.apps] == ["d123", "d456"]
    main, dev = report.apps[0].branches
    assert main.latest_deployment.job_id == "2"
    assert main.latest_deployment.status == "RUNNING"
    assert main.latest_deployment.end_time is None
    assert main.latest_deployment.start_time == (NOW + timedelta(hours=1)).isoformat()
    assert dev.latest_deployment is None and dev.deployments_complete
    assert report.apps[1].branches == [] and report.apps[1].branches_complete
    assert [call.args[0] for call in session.client.call_args_list] == ["sts", "amplify"]
    for call in session.client.call_args_list:
        config = call.kwargs["config"]
        assert config.retries == {"mode": "standard", "total_max_attempts": 3}
        assert config.connect_timeout == 5 and config.read_timeout == 20


def test_empty_multiple_regions(harness):
    _, _, stubs = harness
    identity_response(stubs)
    for region in (REGION, OTHER_REGION):
        stubs["amplify", region].add_response("list_apps", {"apps": []}, {})
    report = collect_inventory(connect(), [REGION, OTHER_REGION])
    assert report.complete and report.apps == []
    assert report.regions == [REGION, OTHER_REGION]


def test_regional_denial_continues_next_region(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_client_error(
        "list_apps", "AccessDeniedException", "secret-denial-message", expected_params={}
    )
    stubs["amplify", OTHER_REGION].add_response("list_apps", {"apps": []}, {})
    report = collect_inventory(connect(), [REGION, OTHER_REGION])
    assert not report.complete
    assert report.errors[0].category == "access_denied"
    assert report.errors[0].region == REGION


def test_branch_denial_retains_app_and_continues(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("list_apps", {"apps": [app_response(), app_response("d456")]}, {})
    stub.add_client_error(
        "list_branches", "UnauthorizedException", expected_params={"appId": "d123"}
    )
    stub.add_response("list_branches", {"branches": []}, {"appId": "d456"})
    report = collect_inventory(connect(), [REGION])
    assert not report.complete
    assert not report.apps[0].branches_complete
    assert report.apps[1].branches_complete
    assert report.errors[0].app_id == "d123"


def test_job_page_failure_does_not_claim_known_latest(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("list_apps", {"apps": [app_response()]}, {})
    stub.add_response(
        "list_branches",
        {"branches": [branch_response(), branch_response("dev")]},
        {"appId": "d123"},
    )
    stub.add_response(
        "list_jobs",
        {"jobSummaries": [job_response()], "nextToken": "more"},
        {"appId": "d123", "branchName": "main"},
    )
    stub.add_client_error(
        "list_jobs",
        "AccessDeniedException",
        expected_params={"appId": "d123", "branchName": "main", "nextToken": "more"},
    )
    stub.add_response("list_jobs", {"jobSummaries": []}, {"appId": "d123", "branchName": "dev"})
    report = collect_inventory(connect(), [REGION])
    main, dev = report.apps[0].branches
    assert not report.complete and main.latest_deployment is None
    assert not main.deployments_complete and dev.deployments_complete
    assert report.errors[0].branch_name == "main"


def test_auth_failure_during_inventory_stops_subsequent_calls(harness):
    _, session, stubs = harness
    identity_response(stubs)
    stubs["amplify", REGION].add_client_error(
        "list_apps", "ExpiredTokenException", expected_params={}
    )
    with pytest.raises(AuthenticationFailure, match="scan stopped"):
        collect_inventory(connect(), [REGION, OTHER_REGION])
    assert len(session.client.call_args_list) == 2


def test_tied_start_time_uses_numeric_job_id(harness):
    _, _, stubs = harness
    identity_response(stubs)
    stub = stubs["amplify", REGION]
    stub.add_response("list_apps", {"apps": [app_response()]}, {})
    stub.add_response("list_branches", {"branches": [branch_response()]}, {"appId": "d123"})
    stub.add_response(
        "list_jobs",
        {"jobSummaries": [job_response("10"), job_response("9")]},
        {"appId": "d123", "branchName": "main"},
    )
    report = collect_inventory(connect(), [REGION])
    assert report.apps[0].branches[0].latest_deployment.job_id == "10"
