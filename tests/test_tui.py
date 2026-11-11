"""Exercise user journeys and the live and offline boundaries, without duplicating AWS tests."""

import asyncio
from unittest.mock import Mock

import pytest
import typer
from conftest import ACCOUNT, REGION, app_response, branch_response, identity_response
from rich.text import Text
from textual.widgets import DataTable, Footer, Input, Static
from typer.testing import CliRunner

from amplify_ops.cli import Settings, app, tui
from amplify_ops.tui import InventoryBrowser


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
