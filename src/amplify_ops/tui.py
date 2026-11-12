"""Optional terminal browser for offline demo and read-only AWS inventory."""

import unicodedata
from collections.abc import Callable, Iterator, Sequence
from dataclasses import fields
from enum import StrEnum

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Label, Select, Static
from textual.worker import Worker, WorkerState, get_current_worker

from amplify_ops.aws import AuthenticationFailure
from amplify_ops.models import (
    AlarmStateChange,
    Branch,
    CloudWatchAlarm,
    EbsCandidate,
    Inventory,
    Report,
    ReportRow,
)
from amplify_ops.models import App as ReportApp
from amplify_ops.tui_demo import demo_apps


def plain(value: str) -> str:
    """Keep untrusted names literal and remove terminal/control formatting characters."""
    return "".join(c for c in value if not unicodedata.category(c).startswith("C"))


def deployment_status(branch: Branch | None, app: ReportApp) -> str:
    if branch is None:
        return "No branches" if app.branches_complete else "Unknown (partial)"
    if not branch.deployments_complete:
        return "Unknown (partial)"
    if branch.latest_deployment is None:
        return "No deployments"
    return branch.latest_deployment.status


class View(StrEnum):
    AMPLIFY = "Amplify"
    EBS = "Unattached EBS volumes"
    CLOUDWATCH = "CloudWatch alarms"
    CLOUDTRAIL = "Recent CloudTrail changes"
    EC2 = "EC2 inventory"
    RESOURCES = "Resource Explorer"
    RESOURCE_COUNTS = "Resource Explorer counts"


REPORT_COLUMNS = {
    View.EBS: ("volume_id", "size_gib", "volume_type", "owner", "snapshot_check"),
    View.CLOUDWATCH: ("state", "name", "alarm_type", "state_updated_at"),
    View.CLOUDTRAIL: ("timestamp", "event_name", "username", "event_source"),
    View.EC2: ("instance_id", "name", "state", "instance_status", "system_status"),
    View.RESOURCES: ("service", "resource_type", "region", "arn"),
    View.RESOURCE_COUNTS: ("service", "region", "count"),
}
RESOURCE_VIEWS = (View.RESOURCES, View.RESOURCE_COUNTS)
LIMIT_REASONS = {
    "PageLimit": "request limit reached",
    "TimeLimit": "time limit reached",
    "Cancelled": "scan cancelled",
    "EventLimitReached": "event limit reached",
}

type LoadView = Callable[[View, str | None, Callable[[], bool]], Inventory | Report]
type DisplayRow = tuple[ReportApp, Branch | None] | ReportRow


def field_label(name: str) -> str:
    return {
        "size_gib": "Size (GiB)",
        "arn": "ARN",
    }.get(name, name.replace("_", " ").capitalize())


def field_value(value: object) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "None"
    return str(value)


class InventoryBrowser(App[None]):
    TITLE = "BotoToolkit"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $surface; }
    #banner { height: auto; padding: 0 1; background: $primary; text-style: bold; }
    #view-bar { height: auto; margin: 0 1; align-vertical: middle; }
    #view-label { width: auto; padding-right: 1; text-style: bold; }
    #view { width: 1fr; max-width: 38; }
    #view > SelectCurrent {
        padding: 0 1;
        background: $accent;
    }
    #view > SelectCurrent #label, #view > SelectCurrent .arrow {
        color: auto 100%;
        text-style: bold;
    }
    #view > SelectCurrent:hover, #view:focus-within > SelectCurrent {
        background-tint: $foreground 20%;
    }
    #view:focus-within > SelectCurrent #label,
    #view > SelectCurrent #label:hover, #view > SelectCurrent .arrow:hover {
        text-style: bold underline;
    }
    #view:disabled > SelectCurrent { background: $surface-lighten-1; }
    #search { margin: 0 1; }
    #summary { height: 1; margin: 0 1; }
    #resources { height: 1fr; min-height: 5; margin: 0 1; border: round $primary; }
    #detail-scroll { height: 1fr; min-height: 5; max-height: 11;
                     margin: 0 1; border: round $accent; }
    #details { height: auto; padding: 0 1; }
    """
    BINDINGS = [
        Binding("f2", "open_views", "Views", priority=True),
        Binding("slash", "search", "Search"),
        Binding("escape", "reset_search", "Clear search", priority=True),
        Binding("ctrl+r", "reset_demo", "Reset demo", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self, load_view: LoadView | None = None, *, resource_explorer: bool = False
    ) -> None:
        super().__init__()
        self.load_view = load_view
        self.resource_explorer = resource_explorer
        self.sub_title = "Offline demo" if load_view is None else "AWS inventory"
        self.view = View.AMPLIFY
        self.apps = demo_apps() if load_view is None else []
        self.report: Report | None = None
        self.history_alarm: str | None = None
        self.alarm_history: Report | None = None
        self.highlighted: str | None = None
        self.empty_message = ""
        self.scanning = False
        self.identity_failed = False
        self.scan_exit_code = 0
        self.rows: dict[str, DisplayRow] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        banner = (
            "OFFLINE DEMO | Synthetic data | AWS not connected | No write actions"
            if self.load_view is None
            else "LIVE | Read-only"
        )
        yield Static(banner, id="banner", markup=False)
        if self.load_view is not None:
            with Horizontal(id="view-bar"):
                yield Label("AWS view", id="view-label")
                yield Select(
                    [
                        (view.value, view)
                        for view in View
                        if self.resource_explorer or view not in RESOURCE_VIEWS
                    ],
                    allow_blank=False,
                    value=self.view,
                    id="view",
                    compact=True,
                )
        yield Input(placeholder="Search displayed inventory…", id="search")
        yield Static(id="summary")
        yield DataTable(id="resources", cursor_type="row", zebra_stripes=True)
        with VerticalScroll(id="detail-scroll"):
            yield Static(id="details", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.set_columns()
        self.query_one(DataTable).focus()
        if self.load_view is None:
            self.populate("")
        else:
            self.start_scan()

    def set_columns(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        if self.view is View.AMPLIFY:
            table.add_columns("App", "Branch", "Region", "Deployment")
        else:
            table.add_columns(*(field_label(name) for name in REPORT_COLUMNS[self.view]))

    @on(Select.Changed, "#view")
    def change_view(self, event: Select.Changed) -> None:
        if (
            self.scanning
            or self.identity_failed
            or not isinstance(event.value, View)
            or event.value is self.view
        ):
            return
        self.view = event.value
        self.apps = []
        self.report = None
        self.set_columns()
        self.query_one(Input).value = ""
        self.start_scan()

    def start_scan(self, alarm_name: str | None = None) -> None:
        if self.load_view is None or self.scanning or self.identity_failed:
            return
        self.scanning = True
        self.scan_exit_code = 3
        self.history_alarm = alarm_name
        self.alarm_history = None
        self.query_one(Select).disabled = True
        self.refresh_bindings()
        label = "alarm history" if alarm_name is not None else self.view.value
        self.empty_message = f"Loading {label}…"
        self.query_one("#banner", Static).update(f"LIVE | Read-only | {self.empty_message}")
        if alarm_name is None:
            self.populate("")
        elif self.highlighted is not None:
            self.show_details(self.highlighted)
        self.scan(self.load_view, self.view, alarm_name)

    @work(thread=True)
    def scan(
        self, load_view: LoadView, view: View, alarm_name: str | None
    ) -> Inventory | Report | AuthenticationFailure | str:
        worker = get_current_worker()
        try:
            return load_view(view, alarm_name, lambda: worker.is_cancelled)
        except AuthenticationFailure as error:
            return error
        except Exception:
            # Avoid rendering tracebacks that could include live service data.
            return "AWS inventory scan failed."

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is not WorkerState.SUCCESS:
            return
        result = event.worker.result
        self.scanning = False
        self.identity_failed = isinstance(result, AuthenticationFailure)
        self.query_one(Select).disabled = self.identity_failed
        self.refresh_bindings()
        if isinstance(result, (str, AuthenticationFailure)):
            self.scan_exit_code = 1
            self.query_one("#banner", Static).update("LIVE | Read-only | Scan failed")
            self.empty_message = plain(str(result))
        elif isinstance(result, Inventory):
            self.apps = result.apps
            self.show_status(result)
        elif isinstance(result, Report):
            if self.history_alarm is not None:
                self.alarm_history = result
                self.show_status(self.report or result, history=result)
            else:
                self.report = result
                self.show_status(result)
        if self.history_alarm is not None and self.highlighted is not None:
            self.show_details(self.highlighted)
        else:
            self.populate(self.query_one(Input).value)

    def show_status(self, report: Inventory | Report, *, history: Report | None = None) -> None:
        complete = report.complete and (history is None or history.complete)
        status = "Complete"
        self.scan_exit_code = 0 if complete else 3
        self.empty_message = "No matching resources in this scan."
        if not complete:
            errors = [*report.errors, *(history.errors if history is not None else [])]
            limit = next((error for error in errors if error.category == "limit"), None)
            reason = LIMIT_REASONS.get(limit.code) if limit else None
            status = f"PARTIAL ({reason or 'some AWS data could not be read'})"
            self.empty_message = "No rows collected. The scan is incomplete."
        label = f"{self.view.value} history" if history is not None else self.view.value
        self.query_one("#banner", Static).update(
            plain(
                f"LIVE | Read-only | {label} | Account {report.identity.account_id} | "
                f"{report.regions[0]} | {status} | Started {(history or report).generated_at}"
            )
        )

    def display_rows(self) -> Iterator[tuple[tuple[str, ...], DisplayRow]]:
        if self.view is View.AMPLIFY:
            for app in self.apps:
                for branch in app.branches or [None]:
                    yield (
                        (
                            app.name,
                            branch.name if branch else "—",
                            app.region,
                            deployment_status(branch, app),
                        ),
                        (app, branch),
                    )
        elif self.report is not None:
            rows: Sequence[ReportRow] = self.report.rows
            if self.view is View.EBS:
                rows = sorted(
                    (row for row in rows if isinstance(row, EbsCandidate)),
                    key=lambda row: row.size_gib if row.size_gib is not None else -1,
                    reverse=True,
                )
            elif self.view is View.CLOUDWATCH:
                rank = {"ALARM": 0, "INSUFFICIENT_DATA": 1, "OK": 2}
                rows = sorted(
                    (row for row in rows if isinstance(row, CloudWatchAlarm)),
                    key=lambda row: (rank.get(row.state or "", 3), row.name.casefold()),
                )
            for row in rows:
                yield (
                    tuple(field_value(getattr(row, name)) for name in REPORT_COLUMNS[self.view]),
                    row,
                )

    def populate(self, query: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.rows.clear()
        self.highlighted = None
        needle = query.strip().casefold()
        for index, (values, row) in enumerate(self.display_rows()):
            searchable = (
                values
                if isinstance(row, tuple)
                else tuple(field_value(getattr(row, field.name)) for field in fields(row))
            )
            if needle not in " ".join(plain(value) for value in searchable).casefold():
                continue
            key = str(index)
            self.rows[key] = row
            table.add_row(*(Text(plain(value)) for value in values), key=key)
        hint = "Enter: alarm history" if self.view is View.CLOUDWATCH else "Tab: change panel"
        sample = " | Sample: 2026-01-15" if self.load_view is None else ""
        self.query_one("#summary", Static).update(
            f"{len(self.rows)} matching rows{sample} | {hint}"
        )
        if self.rows:
            table.move_cursor(row=0, column=0)
            self.show_details(next(iter(self.rows)))
        else:
            empty = not (self.apps or (self.report is not None and self.report.rows))
            message = self.empty_message if empty else ""
            notes = self.report.observations if self.report is not None else []
            self.set_details([message or "No matches. Change the search or press Esc.", *notes])

    @on(Input.Changed, "#search")
    def search_changed(self, event: Input.Changed) -> None:
        self.populate(event.value)

    @on(Input.Submitted, "#search")
    def search_submitted(self) -> None:
        self.query_one(DataTable).focus()

    @on(DataTable.RowHighlighted, "#resources")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value in self.rows:
            self.show_details(event.row_key.value)

    @on(DataTable.RowSelected, "#resources")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        row = self.rows.get(event.row_key.value)
        if isinstance(row, CloudWatchAlarm):
            self.start_scan(row.name)

    def show_details(self, key: str) -> None:
        self.highlighted = key
        row = self.rows[key]
        if isinstance(row, tuple):
            self.set_details(self.amplify_details(*row))
            return
        lines = [
            f"{field_label(field.name)}: {field_value(getattr(row, field.name))}"
            for field in fields(row)
        ]
        if isinstance(row, CloudWatchAlarm) and row.name == self.history_alarm:
            lines.extend(self.history_details())
        if self.report is not None:
            lines.extend(self.report.observations)
        self.set_details(lines)

    def history_details(self) -> list[str]:
        if self.alarm_history is None:
            return ["", self.empty_message]
        changes = [
            f"{row.timestamp}  {field_value(row.previous_state)} → {field_value(row.new_state)}"
            for row in self.alarm_history.rows
            if isinstance(row, AlarmStateChange)
        ]
        if not changes:
            changes = [
                "No state updates retrieved."
                if self.alarm_history.complete
                else "State history is incomplete."
            ]
        return ["", "Recent state changes (up to 20)", *changes]

    def amplify_details(self, app: ReportApp, branch: Branch | None) -> list[str]:
        job = branch.latest_deployment if branch and branch.deployments_complete else None
        listing = "Complete" if app.branches_complete else "PARTIAL — branches may be missing"
        app_label = "Synthetic app" if self.load_view is None else "App ID"
        return [
            f"{app.name} / {branch.name if branch else '(no branch)'}",
            f"{app_label}: {app.app_id} | Region: {app.region}",
            f"Stage: {branch.stage or 'Unknown' if branch else 'Not applicable'}",
            f"Deployment: {deployment_status(branch, app)}",
            f"Branch listing: {listing}",
            f"Job: {job.job_id if job else 'Not available'}",
            f"Started: {job.start_time if job else 'Not available'}",
            f"Ended: {job.end_time or 'Not recorded' if job else 'Not available'}",
        ]

    def set_details(self, lines: list[str]) -> None:
        self.query_one("#details", Static).update(Text("\n".join(plain(line) for line in lines)))
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)

    def action_open_views(self) -> None:
        picker = self.query_one(Select)
        picker.focus()
        picker.action_show_overlay()

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_reset_search(self) -> None:
        if self.load_view is not None:
            picker = self.query_one(Select)
            if picker.expanded:
                picker.expanded = False
                picker.focus()
                return
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "open_views":
            if self.load_view is None:
                return False
            return None if self.scanning or self.identity_failed else True
        if action == "reset_demo" and self.load_view is not None:
            return False
        return super().check_action(action, parameters)

    async def action_quit(self) -> None:
        self.exit(return_code=self.scan_exit_code)

    def action_reset_demo(self) -> None:
        self.apps = demo_apps()
        self.query_one(Input).value = ""
        self.populate("")
        self.query_one(DataTable).focus()
