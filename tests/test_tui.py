"""Exercise user journeys and the live and offline boundaries, without duplicating AWS tests."""

import asyncio
import json
from unittest.mock import Mock

import pytest
import typer
from botocore.stub import ANY
from conftest import ACCOUNT, NOW, REGION, app_response, branch_response, identity_response
from rich.text import Text
from textual.widgets import DataTable, Footer, Input, Select, Static
from typer.testing import CliRunner

from amplify_ops.cli import Settings, app, tui
from amplify_ops.tui import InventoryBrowser, View


@pytest.fixture(scope="module")
def tui_runner():
    # Windows asyncio creates a local socketpair for its wakeup pipe. Initialize
    # it before function-scoped network guards; all application code runs after
    # those guards are installed. No external connection is permitted in a test.
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture
def forbid_aws_session(monkeypatch):
    session = Mock(side_effect=AssertionError("Offline demo must never create an AWS session"))
    monkeypatch.setattr("boto3.Session", session)
    yield
    session.assert_not_called()


def details(browser):
    return str(browser.query_one("#details", Static).content)


@pytest.mark.usefixtures("forbid_aws_session")
def test_browse_search_and_reset_offline(tui_runner):
    async def journey():
        browser = InventoryBrowser()
        async with browser.run_test(size=(100, 35)) as pilot:
            table = browser.query_one(DataTable)
            assert table.row_count == 6
            assert "SUCCEED" in details(browser)
            await pilot.press("down")
            assert "FAILED" in details(browser)
            await pilot.press("slash")
            await pilot.press(*"feature/cart", "enter")
            assert table.row_count == 1
            assert "RUNNING" in details(browser)
            await pilot.press("escape")
            assert table.row_count == 6
            browser.query_one(Input).value = "no-such-app"
            await pilot.pause()
            assert table.row_count == 0
            assert "No matches" in str(browser.query_one("#details", Static).content)
            await pilot.press("ctrl+r")
            assert table.row_count == 6
            assert "SUCCEED" in details(browser)
            await pilot.press("ctrl+q")
        assert not browser.is_running

    tui_runner.run(journey())


@pytest.mark.usefixtures("forbid_aws_session")
def test_partial_empty_and_no_deployments_are_distinct(tui_runner):
    async def journey():
        browser = InventoryBrowser()
        async with browser.run_test(size=(80, 24)) as pilot:
            search = browser.query_one(Input)
            for query, expected in (
                ("partial", "Unknown (partial)"),
                ("empty", "No branches"),
                ("documentation", "No deployments"),
            ):
                search.value = query
                await pilot.pause()
                assert browser.query_one(DataTable).row_count == 1
                assert expected in details(browser)
                assert "Job: Not available" in details(browser)
            await pilot.resize_terminal(60, 20)
            await pilot.pause()
            assert browser.query_one(DataTable).region.height >= 5
            assert browser.query_one("#detail-scroll").region.height > 0
            assert browser.query_one("#detail-scroll").region.bottom < 20
            assert browser.query_one(Footer).region.bottom <= 20

    tui_runner.run(journey())


@pytest.mark.usefixtures("forbid_aws_session")
def test_resource_names_are_literal_and_control_characters_removed(tui_runner):
    async def journey():
        browser = InventoryBrowser()
        browser.apps[0].name = "[bold]fictional[/bold]\x1b\x07\u202e"
        async with browser.run_test() as pilot:
            await pilot.pause()
            cell = browser.query_one(DataTable).get_cell_at((0, 0))
            assert isinstance(cell, Text)
            assert cell.plain == "[bold]fictional[/bold]"
            assert not cell.spans
            assert "[bold]fictional[/bold]" in details(browser)
            assert all(c not in details(browser) for c in ("\x1b", "\x07", "\u202e"))

    tui_runner.run(journey())


@pytest.mark.usefixtures("forbid_aws_session")
def test_cli_requires_one_mode_and_real_terminal():
    runner = CliRunner()
    assert runner.invoke(app, ["tui"]).exit_code == 2
    assert runner.invoke(app, ["tui", "--demo", "--live"]).exit_code == 2
    assert runner.invoke(app, ["tui", "--live"]).exit_code == 2
    options = ["--profile", "brewmaster", "--expected-account", ACCOUNT, "--region", REGION]
    result = runner.invoke(app, [*options, "--region", "us-west-2", "tui", "--live"])
    assert result.exit_code == 2
    assert "exactly one region" in result.stderr
    wrong_view = f"arn:aws:resource-explorer-2:us-west-2:{ACCOUNT}:view/ops/example"
    result = runner.invoke(app, [*options, "tui", "--live", "--view-arn", wrong_view])
    assert result.exit_code == 2
    assert "Invalid value for --view-arn" in result.stderr
    assert "selected region and account" in result.stderr
    result = runner.invoke(app, ["--profile", "brewmaster", "tui", "--demo"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.stderr
    assert result.stdout == ""
    assert runner.invoke(app, ["tui", "--help"]).exit_code == 0


@pytest.mark.usefixtures("forbid_aws_session")
def test_cli_explains_missing_optional_extra(monkeypatch):
    monkeypatch.setattr("amplify_ops.cli.importlib.util.find_spec", lambda name: None)
    result = CliRunner().invoke(app, ["tui", "--demo"])
    assert result.exit_code == 1
    assert "uv sync --locked --extra tui" in result.stderr
    assert result.stdout == ""


@pytest.mark.usefixtures("forbid_aws_session")
def test_cli_launches_demo_without_identity_options(monkeypatch):
    run = Mock()
    monkeypatch.setattr("amplify_ops.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("amplify_ops.cli.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(InventoryBrowser, "run", run)
    ctx = typer.Context(typer.main.get_command(app), obj=Settings("", "", []))
    tui(ctx, demo=True)
    run.assert_called_once_with()


@pytest.mark.parametrize("matches", [True, False], ids=["verified", "wrong-account"])
def test_live_startup_verifies_identity_and_only_scans_once(
    tui_runner, harness, monkeypatch, matches
):
    factory, session, stubs = harness
    identity_response(stubs, ACCOUNT if matches else "000000000000")
    if matches:
        stub = stubs["amplify", REGION]
        stub.add_response("list_apps", {"apps": [app_response()]}, {})
        stub.add_response("list_branches", {"branches": [branch_response()]}, {"appId": "d123"})
        stub.add_client_error(
            "list_jobs",
            "AccessDeniedException",
            "private-service-message",
            expected_params={"appId": "d123", "branchName": "main"},
        )

    async def journey(browser):
        async with browser.run_test(size=(100, 30)) as pilot:
            await browser.workers.wait_for_complete()
            await pilot.pause()
            banner = str(browser.query_one("#banner", Static).content)
            if matches:
                assert f"Account {ACCOUNT}" in banner and REGION in banner and "PARTIAL" in banner
                assert "Unknown (partial)" in details(browser)
                assert "private-service-message" not in details(browser)
                await pilot.press("ctrl+r")
                assert browser.query_one(DataTable).row_count == 1
                assert "Test app" in details(browser)
            else:
                assert "Scan failed" in banner
                assert "Account mismatch" in details(browser)
                assert browser.query_one(DataTable).row_count == 0
            await pilot.press("ctrl+q")

    monkeypatch.setattr("amplify_ops.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("amplify_ops.cli.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(InventoryBrowser, "run", lambda browser: tui_runner.run(journey(browser)))
    ctx = typer.Context(typer.main.get_command(app), obj=Settings("brewmaster", ACCOUNT, [REGION]))
    with pytest.raises(typer.Exit) as error:
        tui(ctx, live=True)
    assert error.value.exit_code == (3 if matches else 1)
    factory.assert_called_once_with(profile_name="brewmaster", region_name=REGION)
    assert [call.args[0] for call in session.client.call_args_list] == (
        ["sts", "amplify"] if matches else ["sts"]
    )


def test_live_views_load_on_selection_and_reverify_before_each_scan(
    tui_runner, harness, service_stub, monkeypatch
):
    factory, session, stubs = harness
    stubs["amplify", REGION].add_response("list_apps", {"apps": []}, {})
    for _ in range(7):
        identity_response(stubs)
    identity_response(stubs, "000000000000")

    volume = "vol-00000000000000001"
    instance = "i-00000000000000001"
    ec2 = service_stub("ec2")
    ec2.add_response(
        "describe_volumes",
        {"Volumes": [{"VolumeId": volume, "State": "available", "Size": 20}]},
        {"Filters": [{"Name": "status", "Values": ["available"]}]},
    )
    ec2.add_client_error("describe_snapshots", "UnauthorizedOperation", "private-snapshot-error")
    ec2.add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [{"InstanceId": instance, "State": {"Name": "stopped"}}]}]},
        {},
    )
    ec2.add_response(
        "describe_instance_status",
        {"InstanceStatuses": []},
        {"InstanceIds": [instance], "IncludeAllInstances": True},
    )

    alarms = service_stub("cloudwatch")
    name = "[bold]demo-alarm[/bold]"
    alarm_types = {"AlarmTypes": ["MetricAlarm", "CompositeAlarm", "LogAlarm"]}
    alarm = {"CompositeAlarms": [{"AlarmName": name, "StateValue": "ALARM"}]}
    alarms.add_response("describe_alarms", alarm, alarm_types)
    alarms.add_response("describe_alarms", alarm, {**alarm_types, "AlarmNames": [name]})
    alarms.add_response(
        "describe_alarm_history",
        {
            "AlarmHistoryItems": [
                {
                    "Timestamp": NOW,
                    "HistoryData": json.dumps(
                        {
                            "oldState": {"stateValue": "OK"},
                            "newState": {"stateValue": "ALARM", "stateReason": "private-history"},
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

    trail = service_stub("cloudtrail")
    trail.add_response(
        "lookup_events",
        {
            "Events": [
                {
                    "EventId": "test-event",
                    "EventTime": NOW,
                    "EventName": "StopInstances",
                    "Username": "operator",
                    "Resources": [{"ResourceName": instance}],
                }
            ]
        },
        {
            "LookupAttributes": [{"AttributeKey": "ReadOnly", "AttributeValue": "false"}],
            "StartTime": ANY,
            "EndTime": ANY,
            "MaxResults": 50,
        },
    )

    view_arn = f"arn:aws:resource-explorer-2:{REGION}:{ACCOUNT}:view/ops/example"
    resources = service_stub("resource-explorer-2")
    resource_arn = f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{instance}"
    for _ in range(2):
        resources.add_response("get_view", {"View": {"ViewArn": view_arn}}, {"ViewArn": view_arn})
        resources.add_response("get_index", {"Type": "LOCAL", "State": "ACTIVE"}, {})
        resources.add_response(
            "list_resources",
            {
                "Resources": [
                    {
                        "Arn": resource_arn,
                        "OwningAccountId": ACCOUNT,
                        "Service": "ec2",
                        "Region": REGION,
                        "ResourceType": "ec2:instance",
                        "LastReportedAt": NOW,
                    }
                ]
            },
            {"ViewArn": view_arn, "MaxResults": 100},
        )

    async def journey(browser):
        async with browser.run_test(size=(110, 35)) as pilot:
            picker = browser.query_one(Select)
            table = browser.query_one(DataTable)

            async def finish_scan():
                await pilot.pause()
                await browser.workers.wait_for_complete()
                await pilot.pause()

            async def select(view):
                picker.value = view
                await finish_scan()

            def called_services():
                return [call.args[0] for call in session.client.call_args_list]

            await finish_scan()
            assert called_services() == ["sts", "amplify"]
            picker.focus()
            await pilot.press("enter", "escape")
            assert not picker.expanded
            assert called_services() == ["sts", "amplify"]
            await pilot.press("enter", "down", "enter")
            await finish_scan()
            assert picker.value is View.EBS
            assert table.row_count == 1 and volume in details(browser)
            assert "PARTIAL" in str(browser.query_one("#banner", Static).content)
            assert "Snapshot check: unknown" in details(browser)
            assert "private-snapshot-error" not in details(browser)

            await select(View.EC2)
            assert "stopped" in details(browser) and instance in details(browser)
            await select(View.CLOUDWATCH)
            assert name in details(browser) and "Recent state changes" not in details(browser)
            assert called_services().count("cloudwatch") == 1
            table.focus()
            await pilot.press("enter")
            await finish_scan()
            assert "OK → ALARM" in details(browser)
            assert "private-history" not in details(browser)

            await select(View.CLOUDTRAIL)
            browser.query_one(Input).value = instance
            await pilot.pause()
            assert table.row_count == 1 and "operator" in details(browser)
            await select(View.RESOURCES)
            assert resource_arn in details(browser)
            await select(View.RESOURCE_COUNTS)
            assert "Count: 1" in details(browser)

            await select(View.EBS)
            assert "Account mismatch" in details(browser)
            assert picker.disabled
            assert called_services() == [
                "sts",
                "amplify",
                "sts",
                "ec2",
                "sts",
                "ec2",
                "sts",
                "cloudwatch",
                "sts",
                "cloudwatch",
                "sts",
                "cloudtrail",
                "sts",
                "resource-explorer-2",
                "sts",
                "resource-explorer-2",
                "sts",
            ]
            await pilot.press("ctrl+q")

    monkeypatch.setattr("amplify_ops.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("amplify_ops.cli.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(InventoryBrowser, "run", lambda browser: tui_runner.run(journey(browser)))
    ctx = typer.Context(typer.main.get_command(app), obj=Settings("brewmaster", ACCOUNT, [REGION]))
    with pytest.raises(typer.Exit) as error:
        tui(ctx, live=True, view_arn=view_arn)
    assert error.value.exit_code == 1
    factory.assert_called_once_with(profile_name="brewmaster", region_name=REGION)
