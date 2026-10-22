from datetime import date, timedelta

import pytest
from conftest import ACCOUNT, NOW, OTHER_REGION, REGION, identity_response
from typer.testing import CliRunner

from amplify_ops.appsync import key_expirations
from amplify_ops.aws import AuthenticationFailure, AwsAccess
from amplify_ops.cli import app
from amplify_ops.costs import cost_report
from amplify_ops.models import ApiKeyExpiry, ApiSummary
from amplify_ops.presentation import json_report

OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
runner = CliRunner()


def connect():
    return AwsAccess.connect("brewmaster", ACCOUNT, REGION)


def test_appsync_all_pages_empty_apis_and_secret_free_refs(services):
    _, _, stubs = services
    identity_response(stubs)
    stub = stubs["appsync", REGION]
    stub.add_response(
        "list_graphql_apis", {"graphqlApis": [{"apiId": "api1"}], "nextToken": "apis2"}, {}
    )
    raw_key = "da2-secret-credential-must-never-leak"
    stub.add_response(
        "list_api_keys",
        {
            "apiKeys": [
                {
                    "id": raw_key,
                    "expires": int((NOW - timedelta(seconds=1)).timestamp()),
                    "description": "private-description",
                }
            ],
            "nextToken": "keys2",
        },
        {"apiId": "api1"},
    )
    stub.add_response(
        "list_api_keys",
        {
            "apiKeys": [
                {"id": "da2-next-secret", "expires": int((NOW + timedelta(days=3)).timestamp())}
            ]
        },
        {"apiId": "api1", "nextToken": "keys2"},
    )
    stub.add_response(
        "list_graphql_apis", {"graphqlApis": [{"apiId": "api2"}]}, {"nextToken": "apis2"}
    )
    stub.add_response("list_api_keys", {"apiKeys": []}, {"apiId": "api2"})
    stubs["appsync", OTHER_REGION].add_response("list_graphql_apis", {"graphqlApis": []}, {})
    report = key_expirations(connect(), [REGION, OTHER_REGION], [], None, 30, now=NOW)
    assert report.complete
    keys = [row for row in report.rows if isinstance(row, ApiKeyExpiry)]
    assert [row.status for row in keys] == ["expired", "expiring"]
    assert keys[0].key_ref.startswith("sha256:") and keys[0].app_id is None
    assert keys[0].association_evidence == "unknown"
    summaries = [row for row in report.rows if isinstance(row, ApiSummary)]
    assert summaries[-1].keys_found == 0 and summaries[-1].keys_complete
    document = json_report(report)
    assert raw_key not in document and "da2-next-secret" not in document
    assert "private-description" not in document


def test_explicit_api_scope_mapping_and_valid_key(services):
    _, _, stubs = services
    identity_response(stubs)
    stubs["appsync", REGION].add_response(
        "list_api_keys",
        {
            "apiKeys": [
                {"id": "da2-raw-secret", "expires": int((NOW + timedelta(days=31)).timestamp())}
            ]
        },
        {"apiId": "explicit"},
    )
    report = key_expirations(connect(), [REGION], ["explicit"], "d123", 30, now=NOW)
    assert report.complete and report.rows[0].status == "valid"
    assert report.rows[0].association_evidence == "operator_supplied"


def test_appsync_access_failure_keeps_other_apis(services):
    _, _, stubs = services
    identity_response(stubs)
    stub = stubs["appsync", REGION]
    stub.add_client_error(
        "list_api_keys",
        "AccessDeniedException",
        "secret-error",
        expected_params={"apiId": "denied"},
    )
    stub.add_response("list_api_keys", {"apiKeys": []}, {"apiId": "allowed"})
    report = key_expirations(connect(), [REGION], ["denied", "allowed"], None, 30, now=NOW)
    assert not report.complete and len(report.rows) == 2
    assert not report.rows[0].keys_complete and report.rows[1].keys_complete
    assert "secret-error" not in json_report(report)


@pytest.mark.parametrize(
    "key", [{"id": "da2-no-expiry"}, {"id": "da1-legacy", "expires": 9999999999999}]
)
def test_unknown_or_legacy_key_expiry_is_not_invented(services, key):
    _, _, stubs = services
    identity_response(stubs)
    stubs["appsync", REGION].add_response("list_api_keys", {"apiKeys": [key]}, {"apiId": "api1"})
    report = key_expirations(connect(), [REGION], ["api1"], None, 30, now=NOW)
    assert not report.complete and report.rows[0].status == "unknown"
    assert report.rows[0].expires_at is None


def test_appsync_auth_failure_stops_next_api(services):
    _, _, stubs = services
    identity_response(stubs)
    stubs["appsync", REGION].add_client_error(
        "list_api_keys", "ExpiredTokenException", expected_params={"apiId": "first"}
    )
    with pytest.raises(AuthenticationFailure):
        key_expirations(connect(), [REGION], ["first", "never-called"], None, 30, now=NOW)


@pytest.mark.parametrize("raw_id", [None, ""])
def test_key_without_identity_is_unknown_even_with_future_expiry(services, raw_id):
    _, _, stubs = services
    identity_response(stubs)
    key = {"expires": int((NOW + timedelta(days=31)).timestamp())}
    if raw_id is not None:
        key["id"] = raw_id
    stubs["appsync", REGION].add_response("list_api_keys", {"apiKeys": [key]}, {"apiId": "api1"})
    report = key_expirations(connect(), [REGION], ["api1"], None, 30, now=NOW)
    assert not report.complete
    row = report.rows[0]
    assert row.status == "unknown"
    assert row.key_ref == "unknown"
    assert row.expires_at is None
    assert not report.rows[-1].keys_complete


BASE = {
    "And": [
        {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [ACCOUNT]}},
        {"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}},
    ]
}
PARAMS = {
    "TimePeriod": {"Start": "2026-09-01", "End": "2026-10-01"},
    "Granularity": "MONTHLY",
    "Metrics": ["UnblendedCost"],
    "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    "Filter": BASE,
}


def cost_page(amount, service="AWS Amplify", unit="USD", estimated=False, **extra):
    return {
        "ResultsByTime": [
            {
                "TimePeriod": PARAMS["TimePeriod"],
                "Estimated": estimated,
                "Groups": [
                    {
                        "Keys": [service],
                        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": unit}},
                    }
                ],
            }
        ],
        **extra,
    }


def test_cost_pagination_decimal_attribution_and_tag_redaction(services):
    _, _, stubs = services
    identity_response(stubs)
    stub = stubs["ce", REGION]
    stub.add_response("get_cost_and_usage", cost_page("0.1", NextPageToken="next"), PARAMS)
    stub.add_response(
        "get_cost_and_usage", cost_page("0.2", estimated=True), {**PARAMS, "NextPageToken": "next"}
    )
    tag_filter = {"And": [BASE, {"Tags": {"Key": "App", "Values": ["private-tag-value"]}}]}
    stub.add_response("get_cost_and_usage", cost_page("0.1"), {**PARAMS, "Filter": tag_filter})
    report = cost_report(connect(), date(2026, 9, 1), date(2026, 10, 1), "App", "private-tag-value")
    assert report.complete and len(report.rows) == 1
    row = report.rows[0]
    assert row.account_cost == "0.3"
    assert row.tag_attributed_estimate == "0.1" and row.outside_tag_scope == "0.2"
    assert row.estimated_by_aws
    assert "private-tag-value" not in json_report(report)


def test_cost_units_are_not_combined(services):
    _, _, stubs = services
    identity_response(stubs)
    response = cost_page("3", NextPageToken="other")
    stubs["ce", REGION].add_response("get_cost_and_usage", response, PARAMS)
    stubs["ce", REGION].add_response(
        "get_cost_and_usage", cost_page("4", unit="EUR"), {**PARAMS, "NextPageToken": "other"}
    )
    report = cost_report(connect(), date(2026, 9, 1), date(2026, 10, 1), None, None)
    assert {row.currency: row.account_cost for row in report.rows} == {"USD": "3", "EUR": "4"}
    assert all(row.tag_attributed_estimate is None for row in report.rows)


def test_cost_partial_account_data_is_unknown_not_zero(services):
    _, _, stubs = services
    identity_response(stubs)
    stub = stubs["ce", REGION]
    stub.add_client_error("get_cost_and_usage", "AccessDeniedException", expected_params=PARAMS)
    filtered = {"And": [BASE, {"Tags": {"Key": "App", "Values": ["id"]}}]}
    stub.add_response("get_cost_and_usage", cost_page("10"), {**PARAMS, "Filter": filtered})
    report = cost_report(connect(), date(2026, 9, 1), date(2026, 10, 1), "App", "id")
    assert not report.complete
    assert report.rows[0].account_cost is None and report.rows[0].outside_tag_scope is None
    assert report.rows[0].tag_attributed_estimate == "10"


def test_cost_arithmetic_preserves_every_reported_decimal_place(services):
    _, _, stubs = services
    identity_response(stubs)
    stub = stubs["ce", REGION]
    stub.add_response(
        "get_cost_and_usage",
        cost_page("123456789.12345678912345678912", NextPageToken="next"),
        PARAMS,
    )
    stub.add_response(
        "get_cost_and_usage",
        cost_page("0.00000000000000000001"),
        {**PARAMS, "NextPageToken": "next"},
    )
    filtered = {"And": [BASE, {"Tags": {"Key": "App", "Values": ["fixture"]}}]}
    stub.add_response(
        "get_cost_and_usage",
        cost_page("0.00000000000000000002"),
        {**PARAMS, "Filter": filtered},
    )
    report = cost_report(connect(), date(2026, 9, 1), date(2026, 10, 1), "App", "fixture")
    assert report.complete
    row = report.rows[0]
    assert row.account_cost == "123456789.12345678912345678913"
    assert row.tag_attributed_estimate == "2E-20"
    assert row.outside_tag_scope == "123456789.12345678912345678911"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "not-a-cost"])
def test_invalid_cost_amount_is_incomplete_and_never_exported(services, amount):
    _, _, stubs = services
    identity_response(stubs)
    response = cost_page("1", NextPageToken="bad")
    stubs["ce", REGION].add_response("get_cost_and_usage", response, PARAMS)
    stubs["ce", REGION].add_response(
        "get_cost_and_usage", cost_page(amount), {**PARAMS, "NextPageToken": "bad"}
    )
    report = cost_report(connect(), date(2026, 9, 1), date(2026, 10, 1), None, None)
    assert not report.complete
    assert report.rows[0].account_cost is None
    assert report.rows[0].outside_tag_scope is None
    assert report.errors[-1].code == "InvalidCostMetadata"
    assert amount not in json_report(report)


@pytest.mark.parametrize(
    "command",
    [
        ["api-keys"],
        ["costs", "--start", "2026-09-01", "--end", "2026-10-01"],
        ["stale", "--app-id", "d123", "--repository", "org/repo"],
        [
            "deploy-plan",
            "--app-id",
            "d123",
            "--branch",
            "dev",
            "--job-id",
            "1",
            "--output",
            "unused.json",
        ],
    ],
)
def test_wrong_account_blocks_remaining_roadmap_commands(harness, command):
    _, session, stubs = harness
    identity_response(stubs, "000000000000")
    result = runner.invoke(app, OPTIONS + command + ["--format", "json"])
    assert result.exit_code == 1 and result.stdout == ""
    assert session.client.call_count == 1


@pytest.mark.parametrize(
    "command",
    [
        ["api-keys", "--app-id", "d123"],
        ["costs", "--start", "bad", "--end", "2026-10-01"],
        ["costs", "--start", "2026-10-01", "--end", "2026-09-01"],
        ["costs", "--start", "2026-09-01", "--end", "2026-10-01", "--tag-key", "App"],
    ],
)
def test_invalid_reporting_options_do_not_access_aws(harness, command):
    factory, _, _ = harness
    result = runner.invoke(app, OPTIONS + command)
    assert result.exit_code == 2
    factory.assert_not_called()
