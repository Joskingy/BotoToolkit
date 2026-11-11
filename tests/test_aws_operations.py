"""Exercise the AWS operations CLI with real SDK shapes and synthetic credentials."""

import json
from contextlib import ExitStack
from datetime import timedelta

import boto3
import pytest
from botocore.stub import ANY, Stubber
from conftest import ACCOUNT, NOW, REGION, identity_response
from typer.testing import CliRunner

from amplify_ops.cli import app

OPTIONS = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
INSTANCE = "i-00000000000000001"
OTHER_INSTANCE = "i-00000000000000002"
VOLUME = "vol-00000000000000001"
OTHER_VOLUME = "vol-00000000000000002"
VIEW = (
    f"arn:aws:resource-explorer-2:{REGION}:{ACCOUNT}:view/ops/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
)
runner = CliRunner()


@pytest.fixture
def service_stub(harness):
    _, session, stubs = harness
    real = boto3.session.Session(
        aws_access_key_id="testing", aws_secret_access_key="testing", region_name=REGION
    )
    session.client.side_effect = lambda service, *, region_name, config: (
        stubs[service, region_name].client
    )
    identity_response(stubs)
    with ExitStack() as stack:

        def create(service):
            stub = Stubber(real.client(service, region_name=REGION))
            stubs[service, REGION] = stub
            stack.enter_context(stub)
            return stub

        yield create


@pytest.mark.parametrize(
    "command",
    [
        ("ec2", "inventory"),
        ("cloudwatch", "alarms"),
        ("cloudtrail", "changes"),
        ("resources", "list", "--view-arn", VIEW),
        ("resources", "summary", "--view-arn", VIEW),
        ("ebs", "candidates"),
    ],
)
def test_wrong_account_blocks_each_operations_command(harness, command):
    factory, session, stubs = harness
    identity_response(stubs, "000000000000")

    result = runner.invoke(app, [*OPTIONS, *command, "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Account mismatch" in result.stderr
    factory.assert_called_once_with(profile_name="brewmaster", region_name=REGION)
    assert [call.args[0] for call in session.client.call_args_list] == ["sts"]


def test_ec2_retains_inventory_and_known_health_when_status_page_is_denied(service_stub):
    stub = service_stub("ec2")
    filters = [{"Name": "tag:Owner", "Values": ["platform"]}]
    stub.add_response(
        "describe_instances",
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE,
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                            "Tags": [
                                {"Key": "Name", "Value": "worker"},
                                {"Key": "Owner", "Value": "platform"},
                                {"Key": "aws:autoscaling:groupName", "Value": "workers"},
                                {"Key": "Private", "Value": "private-tag-value"},
                            ],
                            "BlockDeviceMappings": [{"Ebs": {"VolumeId": VOLUME}}],
                        }
                    ]
                }
            ],
            "NextToken": "more-instances",
        },
        {"Filters": filters},
    )
    stub.add_response(
        "describe_instances",
        {
            "Reservations": [
                {"Instances": [{"InstanceId": OTHER_INSTANCE, "State": {"Name": "stopped"}}]}
            ]
        },
        {"Filters": filters, "NextToken": "more-instances"},
    )
    health_params = {"InstanceIds": [INSTANCE, OTHER_INSTANCE], "IncludeAllInstances": True}
    stub.add_response(
        "describe_instance_status",
        {
            "InstanceStatuses": [
                {
                    "InstanceId": INSTANCE,
                    "InstanceStatus": {"Status": "impaired"},
                    "SystemStatus": {"Status": "ok"},
                }
            ],
            "NextToken": "more-health",
        },
        health_params,
    )
    stub.add_client_error(
        "describe_instance_status",
        "UnauthorizedOperation",
        "private-health-error",
        expected_params={**health_params, "NextToken": "more-health"},
    )

    result = runner.invoke(
        app, [*OPTIONS, "ec2", "inventory", "--owner", "platform", "--format", "json"]
    )

    assert result.exit_code == 3, result.output
    report = json.loads(result.stdout)
    assert not report["complete"]
    assert report["errors"][0]["category"] == "access_denied"
    first, second = report["rows"]
    assert first["auto_scaling_group"] == "workers"
    assert first["volume_ids"] == [VOLUME]
    assert first["owner"] == "platform" and first["instance_status"] == "impaired"
    assert second["instance_id"] == OTHER_INSTANCE and second["instance_status"] is None
    assert "private-tag-value" not in result.output
    assert "private-health-error" not in result.output


def test_cloudwatch_named_alarm_history_exports_only_states(service_stub, tmp_path):
    stub = service_stub("cloudwatch")
    name = "worker-health"
    stub.add_response(
        "describe_alarms",
        {
            "CompositeAlarms": [
                {
                    "AlarmName": name,
                    "StateValue": "ALARM",
                    "ActionsEnabled": False,
                    "StateUpdatedTimestamp": NOW,
                    "StateReason": "private-alarm-reason",
                    "AlarmActions": ["private-action-target"],
                }
            ]
        },
        {
            "AlarmTypes": ["MetricAlarm", "CompositeAlarm", "LogAlarm"],
            "AlarmNames": [name],
            "StateValue": "ALARM",
        },
    )
    stub.add_response(
        "describe_alarm_history",
        {
            "AlarmHistoryItems": [
                {
                    "AlarmName": name,
                    "Timestamp": NOW,
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": "private-history-summary",
                    "HistoryData": json.dumps(
                        {
                            "oldState": {"stateValue": "OK"},
                            "newState": {
                                "stateValue": "ALARM",
                                "stateReason": "private-history-data",
                            },
                        }
                    ),
                }
            ]
        },
        {
            "AlarmName": name,
            "AlarmTypes": ["CompositeAlarm"],
            "HistoryItemType": "StateUpdate",
            "ScanBy": "TimestampDescending",
        },
    )
    output = tmp_path / "alarms.json"

    result = runner.invoke(
        app,
        [
            *OPTIONS,
            "cloudwatch",
            "alarms",
            "--state",
            "ALARM",
            "--alarm-name",
            name,
            "--output",
            str(output),
        ],
        terminal_width=180,
    )

    assert result.exit_code == 0, result.output
    assert name in result.stdout
    saved = output.read_text(encoding="utf-8")
    alarm, change = json.loads(saved)["rows"]
    assert alarm["actions_enabled"] is False
    assert alarm["state"] == "ALARM"
    assert change["previous_state"] == "OK" and change["new_state"] == "ALARM"
    assert "private-" not in result.output + saved


def test_cloudtrail_bounds_scan_before_resource_filter_and_omits_raw_payload(service_stub):
    stub = service_stub("cloudtrail")
    event = {
        "EventId": "event-one",
        "EventTime": NOW,
        "EventName": "StopInstances",
        "EventSource": "ec2.amazonaws.com",
        "Username": "operator",
        "ReadOnly": "false",
        "Resources": [{"ResourceName": INSTANCE, "ResourceType": "AWS::EC2::Instance"}],
        "CloudTrailEvent": '{"requestParameters": "private-event-payload"}',
        "AccessKeyId": "private-access-key",
    }
    lookup = {
        "LookupAttributes": [{"AttributeKey": "ReadOnly", "AttributeValue": "false"}],
        "StartTime": ANY,
        "EndTime": ANY,
        "MaxResults": 2,
    }
    stub.add_response("lookup_events", {"Events": [event], "NextToken": "more-events"}, lookup)
    stub.add_response(
        "lookup_events",
        {
            "Events": [
                {**event, "EventId": "event-two", "Resources": [{"ResourceName": OTHER_INSTANCE}]}
            ]
        },
        {**lookup, "NextToken": "more-events"},
    )

    result = runner.invoke(
        app,
        [
            *OPTIONS,
            "cloudtrail",
            "changes",
            "--hours",
            "12",
            "--limit",
            "1",
            "--resource",
            INSTANCE,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 3, result.output
    report = json.loads(result.stdout)
    assert not report["complete"]
    assert report["errors"][0]["code"] == "EventLimitReached"
    assert [row["event_id"] for row in report["rows"]] == ["event-one"]
    assert report["rows"][0]["username"] == "operator"
    assert report["rows"][0]["resources"] == [INSTANCE]
    assert "private-" not in result.output


@pytest.mark.parametrize("command", ["list", "summary"])
def test_resources_uses_one_view_and_counts_each_owned_resource_once(service_stub, command):
    stub = service_stub("resource-explorer-2")
    stub.add_response(
        "get_view",
        {
            "View": {
                "ViewArn": VIEW,
                "Scope": f"arn:aws:iam::{ACCOUNT}:root",
                "Filters": {"FilterString": "tag:Owner=private-view-filter"},
                "IncludedProperties": [{"Name": "tags"}],
            }
        },
        {"ViewArn": VIEW},
    )
    stub.add_response(
        "get_index",
        {"Type": "AGGREGATOR", "State": "ACTIVE", "ReplicatingFrom": ["us-west-2"]},
        {},
    )
    instance = {
        "Arn": f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{INSTANCE}",
        "OwningAccountId": ACCOUNT,
        "Service": "ec2",
        "Region": REGION,
        "ResourceType": "ec2:instance",
        "LastReportedAt": NOW,
        "Properties": [{"Name": "tags", "Data": {"Owner": "private-tag-data"}}],
    }
    volume = {
        **instance,
        "Arn": f"arn:aws:ec2:us-west-2:{ACCOUNT}:volume/{VOLUME}",
        "Region": "us-west-2",
        "ResourceType": "ec2:volume",
    }
    request = {
        "ViewArn": VIEW,
        "MaxResults": 100,
        "Filters": {"FilterString": "service:ec2 tag:Owner=private-command-filter"},
    }
    stub.add_response(
        "list_resources",
        {"Resources": [instance], "NextToken": "another-page"},
        request,
    )
    stub.add_response(
        "list_resources",
        {
            "Resources": [
                instance,
                volume,
                {**instance, "Arn": "foreign-resource", "OwningAccountId": "000000000000"},
            ]
        },
        {**request, "NextToken": "another-page"},
    )

    result = runner.invoke(
        app,
        [
            *OPTIONS,
            "resources",
            command,
            "--view-arn",
            VIEW,
            "--filter",
            "service:ec2 tag:Owner=private-command-filter",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["complete"]
    assert any(
        "AGGREGATOR (ACTIVE)" in text and "us-west-2" in text for text in report["observations"]
    )
    assert "private-" not in result.output and "foreign-resource" not in result.output
    if command == "summary":
        assert report["rows"] == [
            {"service": "ec2", "region": REGION, "count": 1},
            {"service": "ec2", "region": "us-west-2", "count": 1},
        ]
    else:
        assert [row["arn"] for row in report["rows"]] == [instance["Arn"], volume["Arn"]]


@pytest.mark.parametrize("snapshot_denied", [False, True])
def test_ebs_candidates_distinguishes_snapshot_evidence_from_unavailable_data(
    service_stub, snapshot_denied
):
    stub = service_stub("ec2")
    stub.add_response(
        "describe_volumes",
        {
            "Volumes": [
                {
                    "VolumeId": VOLUME,
                    "State": "available",
                    "Size": 20,
                    "VolumeType": "gp3",
                    "CreateTime": NOW,
                    "Tags": [{"Key": "Owner", "Value": "platform"}],
                },
                {"VolumeId": OTHER_VOLUME, "State": "available", "Size": 10},
                {"VolumeId": "vol-00000000000000003", "State": "in-use"},
            ]
        },
        {"Filters": [{"Name": "status", "Values": ["available"]}]},
    )
    expected = {
        "OwnerIds": ["self"],
        "Filters": [
            {"Name": "volume-id", "Values": [VOLUME, OTHER_VOLUME]},
            {"Name": "status", "Values": ["completed"]},
        ],
    }
    newer = {
        "VolumeId": VOLUME,
        "SnapshotId": "snap-00000000000000002",
        "State": "completed",
        "StartTime": NOW + timedelta(hours=1),
    }
    stub.add_response(
        "describe_snapshots", {"Snapshots": [newer], "NextToken": "next-snapshot"}, expected
    )
    if snapshot_denied:
        stub.add_client_error(
            "describe_snapshots",
            "UnauthorizedOperation",
            "private-snapshot-error",
            expected_params={**expected, "NextToken": "next-snapshot"},
        )
    else:
        stub.add_response(
            "describe_snapshots",
            {"Snapshots": [{**newer, "SnapshotId": "snap-00000000000000001", "StartTime": NOW}]},
            {**expected, "NextToken": "next-snapshot"},
        )

    result = runner.invoke(app, [*OPTIONS, "ebs", "candidates", "--format", "json"])

    assert result.exit_code == (3 if snapshot_denied else 0), result.output
    report = json.loads(result.stdout)
    assert report["complete"] is not snapshot_denied
    first, second = report["rows"]
    assert first["size_gib"] == 20 and first["owner"] == "platform"
    assert first["snapshot_id"] == (None if snapshot_denied else newer["SnapshotId"])
    assert first["snapshot_check"] == ("unknown" if snapshot_denied else "found")
    assert second["snapshot_check"] == ("unknown" if snapshot_denied else "none_found")
    assert "private-snapshot-error" not in result.output
