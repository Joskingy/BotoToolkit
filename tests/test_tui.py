"""Exercise user journeys and the offline boundary, without duplicating AWS tests."""

import asyncio
from unittest.mock import Mock

import pytest
from rich.text import Text
from textual.widgets import DataTable, Footer, Input, Static
from typer.testing import CliRunner

from amplify_ops.cli import app
from amplify_ops.tui import DemoBrowser


@pytest.fixture(scope="module")
def tui_runner():
    # Windows asyncio creates a local socketpair for its wakeup pipe. Initialize
    # it before function-scoped network guards; all application code runs after
    # those guards are installed. No external connection is permitted in a test.
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture(autouse=True)
def forbid_aws_session(monkeypatch):
    session = Mock(side_effect=AssertionError("Offline demo must never create an AWS session"))
    monkeypatch.setattr("boto3.Session", session)
    yield
    session.assert_not_called()


def details(browser):
    return browser.query_one("#details", Static).content.plain


def test_browse_search_and_reset_offline(tui_runner):
    async def journey():
        browser = DemoBrowser()
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


def test_partial_empty_and_no_deployments_are_distinct(tui_runner):
    async def journey():
        browser = DemoBrowser()
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


def test_resource_names_are_literal_and_control_characters_removed(tui_runner):
    async def journey():
        browser = DemoBrowser()
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


def test_cli_requires_demo_and_real_terminal():
    runner = CliRunner()
    assert runner.invoke(app, ["tui"]).exit_code == 2
    result = runner.invoke(app, ["--profile", "brewmaster", "tui", "--demo"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.stderr
    assert result.stdout == ""
    assert runner.invoke(app, ["tui", "--help"]).exit_code == 0


def test_cli_explains_missing_optional_extra(monkeypatch):
    monkeypatch.setattr("amplify_ops.cli.importlib.util.find_spec", lambda name: None)
    result = CliRunner().invoke(app, ["tui", "--demo"])
    assert result.exit_code == 1
    assert "uv sync --locked --extra tui" in result.stderr
    assert result.stdout == ""


def test_cli_launches_demo_without_identity_options(monkeypatch):
    run = Mock()
    monkeypatch.setattr("amplify_ops.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("amplify_ops.cli.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(DemoBrowser, "run", run)
    # Exercise the terminal launch boundary without starting an interactive driver.
    import amplify_ops.cli as cli

    cli.tui(demo=True)
    run.assert_called_once_with()
