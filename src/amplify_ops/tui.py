"""Optional terminal browser for offline demo and read-only AWS inventory."""

import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from enum import StrEnum

from rich.filesize import decimal
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Label, Link, Select, Static
from textual.worker import Worker, WorkerState, get_current_worker

from amplify_ops.aws import AuthenticationFailure
from amplify_ops.models import (
    AlarmStateChange,
    AppSyncApi,
    AppSyncTableSource,
    Branch,
    CloudFormationResource,
    CloudFormationStack,
    CloudWatchAlarm,
    DynamoDbTable,
    EbsCandidate,
    Ec2Instance,
    Inventory,
    Report,
    ReportRow,
)
from amplify_ops.models import App as ReportApp
from amplify_ops.tui_demo import (
    demo_alarms,
    demo_apps,
    demo_appsync,
    demo_instances,
    demo_stacks,
    demo_tables,
)


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
    COSTS = "Cost Explorer"
    STACKS = "CloudFormation stacks"
    DYNAMODB = "DynamoDB tables"
    APPSYNC = "AppSync data sources"


REPORT_COLUMNS = {
    View.DYNAMODB: ("name",),
    View.APPSYNC: ("name", "api_id"),
    View.EBS: ("volume_id", "size_gib", "volume_type", "owner", "snapshot_check"),
    View.CLOUDTRAIL: ("timestamp", "event_name", "username", "event_source"),
    View.RESOURCES: ("service", "resource_type", "region", "arn"),
    View.RESOURCE_COUNTS: ("service", "region", "count"),
    View.COSTS: ("service", "account_cost", "currency", "estimated_by_aws"),
}
ALARM_STATES = {
    "ALARM": ("In alarm", "bold red"),
    "INSUFFICIENT_DATA": ("Insufficient data", "yellow"),
    "OK": ("OK", "green"),
}
ALARM_ORDER = {state: index for index, state in enumerate(ALARM_STATES)}
ALARM_TYPES = {"MetricAlarm": "Metric", "CompositeAlarm": "Composite", "LogAlarm": "Log"}
ACTION_LABELS = {True: "Enabled", False: "Disabled", None: "Unknown"}
EC2_CHECK_STATES = {
    "ok": "Passed",
    "impaired": "Impaired",
    "initializing": "Initializing",
    "insufficient-data": "Insufficient data",
    "not-applicable": "Not applicable",
}
EC2_HEALTH_STYLES = {"impaired": "bold red", "passed": "green", "stopped": "", "unknown": "yellow"}
BILLING_MODES = {"PAY_PER_REQUEST": "On demand", "PROVISIONED": "Provisioned"}
TABLE_RESOURCE_TYPES = {"AWS::DynamoDB::Table", "AWS::DynamoDB::GlobalTable"}
TABLE_MEMBERSHIP_STATES = {
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "IMPORT_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
}
DETAIL_VIEWS = (View.DYNAMODB, View.APPSYNC)
COMPACT_STATUS_VIEWS = (View.CLOUDWATCH, View.EC2, View.STACKS, *DETAIL_VIEWS)
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
        "estimated_by_aws": "Estimated by AWS",
    }.get(name, name.replace("_", " ").capitalize())


def field_value(value: object) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "None"
    return str(value)


def alarm_status(state: str | None) -> tuple[str, str]:
    return ALARM_STATES.get(state or "", ("Unknown", ""))


def stack_status(status: str) -> str:
    return status.replace("_", " ").capitalize()


def stack_to_open(row: CloudFormationStack | CloudFormationResource) -> str | None:
    if isinstance(row, CloudFormationStack):
        return row.stack_id
    return row.physical_id if row.resource_type == "AWS::CloudFormation::Stack" else None


def ec2_health(instance: Ec2Instance) -> tuple[str, str]:
    if instance.state == "stopped":
        return "stopped", "Stopped"
    if instance.system_status == "impaired":
        label = "Both impaired" if instance.instance_status == "impaired" else "System impaired"
        return "impaired", label
    if instance.instance_status == "impaired":
        return "impaired", "Instance impaired"
    if instance.state == "running" and instance.system_status == instance.instance_status == "ok":
        return "passed", "Checks passed"
    return "unknown", "Checks unknown"


def alarm_update(value: str | None, scanned_at: str) -> str:
    if value is None:
        return "Unknown"
    try:
        updated = datetime.fromisoformat(value)
        elapsed = datetime.fromisoformat(scanned_at) - updated
    except ValueError, TypeError:
        return value
    if updated.tzinfo is None:
        return value
    exact = updated.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 0:
        return exact
    if minutes == 0:
        return f"{exact} (less than a minute before scan)"
    if minutes >= 1440:
        amount, unit = minutes // 1440, "day"
    elif minutes >= 60:
        amount, unit = minutes // 60, "hour"
    else:
        amount, unit = minutes, "minute"
    return f"{exact} ({amount} {unit}{'s' if amount != 1 else ''} before scan)"


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
    #cost-console { display: none; margin: 0 1; }
    #search { margin: 0 1; }
    #summary { height: auto; margin: 0 1; }
    #resources { height: 1fr; min-height: 5; margin: 0 1; border: round $primary; }
    #detail-scroll { height: 1fr; min-height: 5; max-height: 11;
                     margin: 0 1; border: round $accent; }
    #details { height: auto; padding: 0 1; }
    """
    BINDINGS = [
        Binding("f2", "open_views", "Views", priority=True),
        Binding("slash", "search", "Search"),
        Binding("escape", "reset_search", "Clear search", priority=True),
        Binding("ctrl+r", "reset_demo", "Reset", priority=True),
        Binding("f5", "refresh_costs", "Fetch costs (API fee)", priority=True),
        Binding("backspace", "back_stack", "Back to parent", show=False),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self, load_view: LoadView | None = None, *, resource_explorer: bool = False
    ) -> None:
        super().__init__()
        self.load_view = load_view
        self.resource_explorer = resource_explorer
        self.sub_title = "Browse | Offline demo" if load_view is None else "Browse | AWS inventory"
        self.view = View.AMPLIFY
        self.apps = demo_apps() if load_view is None else []
        self.report: Report | None = None
        self.cached_costs: Report | None = None
        self.stack_path: list[str] = []
        self.stack_reports: dict[str | None, Report] = {}
        self.pending_detail: str | None = None
        self.detail_reports: dict[tuple[View, str], Report] = {}
        self.appsync_apis: Report | None = None
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
            "OFFLINE DEMO | Sample data | AWS not connected"
            if self.load_view is None
            else "LIVE | Read-only"
        )
        yield Static(banner, id="banner", markup=False)
        views = (
            (View.AMPLIFY, View.CLOUDWATCH, View.EC2, View.STACKS, *DETAIL_VIEWS)
            if self.load_view is None
            else tuple(
                view for view in View if self.resource_explorer or view not in RESOURCE_VIEWS
            )
        )
        with Horizontal(id="view-bar"):
            yield Label("Demo view" if self.load_view is None else "AWS view", id="view-label")
            yield Select(
                [(view.value, view) for view in views],
                allow_blank=False,
                value=self.view,
                id="view",
                compact=True,
            )
        if self.load_view is not None:
            yield Link(
                "Open Cost Explorer in the AWS console (free)",
                url="https://console.aws.amazon.com/costmanagement/home#/cost-explorer",
                tooltip="Uses your browser’s AWS sign-in. Check the account in the console.",
                id="cost-console",
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
        elif self.view is View.CLOUDWATCH:
            table.add_columns("State", "Alarm", "Actions")
        elif self.view is View.DYNAMODB:
            table.add_column("Table name", width=48)
        elif self.view is View.APPSYNC:
            table.add_column("GraphQL API", width=24)
            table.add_column("API ID", width=27)
        elif self.view is View.EC2:
            table.add_column("Health", width=17)
            table.add_column("Instance", width=19)
            table.add_column("Owner", width=12)
        elif self.view is View.STACKS:
            if self.stack_path:
                table.add_column("Logical ID", width=14)
                table.add_column("Resource type", width=21)
                table.add_column("Status", width=15)
            else:
                table.add_column("Stack", width=22)
                table.add_column("Status", width=17)
                table.add_column("Changed", width=10)
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
        self.stack_path.clear()
        self.apps = []
        self.report = None
        self.set_columns()
        if self.load_view is None:
            self.action_reset_demo()
            return
        self.query_one(Input).value = ""
        self.query_one("#cost-console", Link).display = self.view is View.COSTS
        if self.view is View.COSTS:
            self.history_alarm = None
            self.alarm_history = None
            self.report = self.cached_costs
            if self.report is None:
                self.query_one("#banner", Static).update("LIVE | Read-only | Cost Explorer")
                self.empty_message = (
                    "No cost data loaded. Press F5 to fetch from AWS ($0.01 per page)."
                )
            else:
                self.show_status(self.report, cached=True)
            self.populate("")
            self.refresh_bindings()
        elif self.view is View.STACKS:
            self.show_stack_level()
        else:
            if self.view in DETAIL_VIEWS:
                self.query_one(DataTable).focus()
            self.start_scan()

    def start_scan(self, selection: str | None = None) -> None:
        if self.load_view is None or self.scanning or self.identity_failed:
            return
        if self.view is View.COSTS:
            self.report = None
        self.scanning = True
        self.scan_exit_code = 3
        self.history_alarm = selection if self.view is View.CLOUDWATCH else None
        self.pending_detail = selection if self.view in DETAIL_VIEWS else None
        self.alarm_history = None
        self.query_one(Select).disabled = True
        self.refresh_bindings()
        label = self.view.value
        if self.history_alarm is not None:
            label = "alarm history"
        elif self.pending_detail is not None:
            label = "table metadata" if self.view is View.DYNAMODB else "data sources"
        elif self.view is View.STACKS and selection is not None:
            label = "stack resources"
        self.empty_message = f"Loading {label}…"
        self.query_one("#banner", Static).update(f"LIVE | Read-only | {self.empty_message}")
        if self.history_alarm is None and self.pending_detail is None:
            self.populate("")
        elif self.highlighted is not None:
            self.show_details(self.highlighted)
        self.scan(self.load_view, self.view, selection)

    @work(thread=True)
    def scan(
        self, load_view: LoadView, view: View, selection: str | None
    ) -> Inventory | Report | AuthenticationFailure | str:
        worker = get_current_worker()
        try:
            return load_view(view, selection, lambda: worker.is_cancelled)
        except AuthenticationFailure as error:
            return error
        except Exception:
            # Avoid rendering tracebacks that could include live service data.
            return "AWS inventory scan failed."

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is not WorkerState.SUCCESS:
            return
        result = event.worker.result
        detail_id, self.pending_detail = self.pending_detail, None
        self.scanning = False
        self.identity_failed = isinstance(result, AuthenticationFailure)
        if self.identity_failed:
            self.cached_costs = None
            self.stack_reports.clear()
            self.detail_reports.clear()
            self.appsync_apis = None
            if self.view in DETAIL_VIEWS:
                self.report = None
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
                self.show_status(self.report or result, detail=result)
            elif detail_id is not None:
                self.detail_reports[self.view, detail_id] = result
                self.show_status(self.report or result, detail=result)
            else:
                self.report = result
                if self.view is View.COSTS:
                    self.cached_costs = result
                if self.view is View.APPSYNC:
                    self.appsync_apis = result
                if self.view is View.STACKS and result.complete:
                    self.stack_reports[self.current_stack_id()] = result
                self.show_status(result)
        if (
            (self.history_alarm is not None or detail_id is not None)
            and self.highlighted is not None
            and not (detail_id is not None and self.identity_failed)
        ):
            self.show_details(self.highlighted)
        else:
            self.populate(self.query_one(Input).value)

    def show_status(
        self, report: Inventory | Report, *, detail: Report | None = None, cached: bool = False
    ) -> None:
        complete = report.complete and (detail is None or detail.complete)
        status = "Complete"
        self.scan_exit_code = 0 if complete else 3
        self.empty_message = "No matching resources in this scan."
        if self.view is View.COSTS:
            self.empty_message = "No service costs were returned for this period."
        if not complete:
            errors = [*report.errors, *(detail.errors if detail is not None else [])]
            limit = next((error for error in errors if error.category == "limit"), None)
            reason = LIMIT_REASONS.get(limit.code) if limit else None
            unread = (
                "data unread"
                if self.view in COMPACT_STATUS_VIEWS
                else "some AWS data could not be read"
            )
            status = f"PARTIAL ({reason or unread})"
            self.empty_message = "No rows collected. The scan is incomplete."
        label = self.view.value
        scope = "All billing regions" if self.view is View.COSTS else report.regions[0]
        banner = self.query_one("#banner", Static)
        if self.view in COMPACT_STATUS_VIEWS:
            identity = f"LIVE | Read-only | Account {report.identity.account_id} | {scope}"
            started = datetime.fromisoformat((detail or report).generated_at).astimezone(UTC)
            run = f"{status} | {started:%Y-%m-%d %H:%M:%SZ}"
            banner.update(plain(identity) + "\n" + ("Cached | " if cached else "") + plain(run))
            return
        source = "Cached | " if cached else ""
        banner.update(
            plain(
                f"LIVE | Read-only | {label} | Account {report.identity.account_id} | "
                f"{scope} | {status} | {source}Started {(detail or report).generated_at}"
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
                alarms = sorted(
                    (row for row in rows if isinstance(row, CloudWatchAlarm)),
                    key=lambda row: (ALARM_ORDER.get(row.state or "", 3), row.name.casefold()),
                )
                for alarm in alarms:
                    state, _ = alarm_status(alarm.state)
                    yield (state, alarm.name, ACTION_LABELS[alarm.actions_enabled]), alarm
                return
            elif self.view is View.EC2:
                instances = sorted(
                    (row for row in rows if isinstance(row, Ec2Instance)),
                    key=lambda row: ec2_health(row)[0] != "impaired",
                )
                for instance in instances:
                    _, health = ec2_health(instance)
                    yield (
                        (
                            health,
                            instance.name or instance.instance_id,
                            instance.owner or "Unknown",
                        ),
                        instance,
                    )
                return
            elif self.view is View.STACKS:
                for row in rows:
                    if isinstance(row, CloudFormationStack):
                        name = f"↳ {row.name}" if row.parent_id else row.name
                        yield (name, stack_status(row.status), row.changed_at[:10]), row
                    elif isinstance(row, CloudFormationResource):
                        yield (
                            (
                                row.logical_id,
                                row.resource_type.removeprefix("AWS::"),
                                stack_status(row.status),
                            ),
                            row,
                        )
                return
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
            if isinstance(
                row, CloudWatchAlarm | Ec2Instance | CloudFormationStack | CloudFormationResource
            ):
                searchable = (*values, *searchable)
            if needle not in " ".join(plain(value) for value in searchable).casefold():
                continue
            key = str(index)
            self.rows[key] = row
            cells = [Text(plain(value)) for value in values]
            if isinstance(row, CloudWatchAlarm):
                cells[0].stylize(alarm_status(row.state)[1])
            elif isinstance(row, Ec2Instance):
                cells[0].stylize(EC2_HEALTH_STYLES[ec2_health(row)[0]])
            table.add_row(*cells, key=key)
        if self.view is View.CLOUDWATCH and self.report is not None:
            summary = self.alarm_summary(self.report)
        elif self.view is View.EC2 and self.report is not None:
            summary = self.ec2_summary(self.report)
        elif self.view is View.STACKS and self.report is not None:
            kind = "Recorded resources" if self.stack_path else "Current stacks"
            partial = "Partial · " if not self.report.complete else ""
            summary = f"{kind} · {partial}{len(self.rows)} of {len(self.report.rows)} shown"
            if self.stack_path:
                summary += "\nBackspace: previous list"
            elif self.rows:
                summary += "\nEnter: view stack resources"
        elif self.view in DETAIL_VIEWS and self.report is not None:
            partial = "Partial · " if not self.report.complete else ""
            kind = "tables" if self.view is View.DYNAMODB else "GraphQL APIs"
            summary = f"{partial}{len(self.rows)} of {len(self.report.rows)} {kind} shown"
            if self.rows:
                action = "table metadata" if self.view is View.DYNAMODB else "DynamoDB data sources"
                summary += f"\nEnter: view {action}"
        else:
            sample = " | Sample: 2026-01-15" if self.load_view is None else ""
            summary = f"{len(self.rows)} matching rows{sample} | Tab: change panel"
        self.query_one("#summary", Static).update(summary)
        if self.rows:
            table.move_cursor(row=0, column=0)
            self.show_details(next(iter(self.rows)))
        else:
            empty = not (self.apps or (self.report is not None and self.report.rows))
            message = self.empty_message if empty else ""
            notes = self.report.observations if self.report is not None else []
            lines = [message or "No matches. Change the search or press Esc.", *notes]
            if self.view is View.STACKS and self.stack_path:
                lines.insert(0, f"Stack: {self.stack_path[-1].split('/')[1]}")
            self.set_details(lines)

    def alarm_summary(self, report: Report) -> str:
        alarms = [row for row in report.rows if isinstance(row, CloudWatchAlarm)]
        counts = Counter(alarm.state for alarm in alarms)
        states = (
            f"{counts['ALARM']} in alarm · {counts['INSUFFICIENT_DATA']} insufficient data"
            f" · {counts['OK']} OK"
        )
        unknown = len(alarms) - sum(counts[state] for state in ALARM_STATES)
        if unknown:
            states += f" · {unknown} unknown"
        disabled = sum(alarm.actions_enabled is False for alarm in alarms)
        matches = f"{len(self.rows)} of {len(alarms)} alarms · Actions disabled: {disabled}"
        if not report.complete:
            matches = (
                f"Partial · {len(self.rows)} of {len(alarms)} retrieved"
                f" · Actions disabled: {disabled}"
            )
        elif self.load_view is not None:
            matches += " · Enter: history"
        return f"{states}\n{matches}"

    def ec2_summary(self, report: Report) -> str:
        counts = Counter(ec2_health(row)[0] for row in report.rows if isinstance(row, Ec2Instance))
        states = (
            f"{counts['impaired']} impaired · {counts['passed']} passed"
            f" · {counts['stopped']} stopped · {counts['unknown']} unknown"
        )
        partial = "Partial · " if not report.complete else ""
        return f"{states}\n{partial}{counts.total()} instances retrieved · {len(self.rows)} shown"

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
        if self.scanning or self.identity_failed:
            return
        row = self.rows.get(event.row_key.value)
        if isinstance(row, CloudWatchAlarm):
            self.start_scan(row.name)
        elif isinstance(row, DynamoDbTable | AppSyncApi):
            selection = row.name if isinstance(row, DynamoDbTable) else row.api_id
            if self.load_view is None:
                demo = demo_tables if isinstance(row, DynamoDbTable) else demo_appsync
                self.detail_reports[self.view, selection] = demo(selection)
            report = self.detail_reports.get((self.view, selection))
            if report is None or not report.complete:
                self.start_scan(selection)
            elif event.row_key.value is not None:
                self.show_details(event.row_key.value)
        elif isinstance(row, CloudFormationStack | CloudFormationResource):
            stack_id = stack_to_open(row)
            if stack_id is not None and stack_id not in self.stack_path:
                self.stack_path.append(stack_id)
                self.show_stack_level()

    def show_details(self, key: str) -> None:
        self.highlighted = key
        row = self.rows[key]
        if isinstance(row, tuple):
            self.set_details(self.amplify_details(*row))
            return
        if isinstance(row, CloudWatchAlarm) and self.report is not None:
            lines = [
                row.name,
                f"State: {alarm_status(row.state)[0]} | "
                f"Actions: {ACTION_LABELS[row.actions_enabled]}",
                f"Last state update: "
                f"{alarm_update(row.state_updated_at, self.report.generated_at)}",
                f"Type: {ALARM_TYPES.get(row.alarm_type, row.alarm_type)} | Region: {row.region}",
            ]
            if row.name == self.history_alarm:
                lines.extend(self.history_details())
            elif self.load_view is not None:
                lines.append("Enter: alarm history")
        elif isinstance(row, CloudFormationStack):
            lines = [
                row.name,
                f"Status: {stack_status(row.status)}",
                f"Last change: {row.changed_at}",
                f"Stack ID: {field_value(row.stack_id)}",
                f"Parent stack ID: {field_value(row.parent_id)}",
            ]
        elif isinstance(row, CloudFormationResource):
            lines = [
                f"Stack: {self.stack_path[-1].split('/')[1]}",
                f"{row.logical_id} | {row.resource_type}",
                f"Recorded status: {stack_status(row.status)}",
                f"Physical ID: {row.physical_id or 'Unavailable'}",
            ]
            nested_id = stack_to_open(row)
            if nested_id is not None and nested_id not in self.stack_path:
                lines.insert(1, "Enter: open nested stack")
        elif isinstance(row, DynamoDbTable):
            lines = self.table_details(row)
        elif isinstance(row, AppSyncApi):
            lines = self.appsync_details(row)
        elif isinstance(row, Ec2Instance):
            system = EC2_CHECK_STATES.get(row.system_status or "", "Unknown")
            instance = EC2_CHECK_STATES.get(row.instance_status or "", "Unknown")
            if row.state == "stopped":
                system = instance = "Not applicable"
            lines = [
                row.name or row.instance_id,
                f"State: {(row.state or 'Unknown').capitalize()} | Owner: {row.owner or 'Unknown'}",
                f"System check: {system} | Instance check: {instance}",
                f"Instance ID: {row.instance_id} | Region: {row.region}",
                f"Type: {field_value(row.instance_type)} | "
                f"Environment: {field_value(row.environment)}",
                f"Auto Scaling group: {field_value(row.auto_scaling_group)}",
                f"Attached volumes: {field_value(row.volume_ids)}",
            ]
            if self.report is not None:
                lines.extend(self.report.observations)
        else:
            lines = [
                f"{field_label(field.name)}: {field_value(getattr(row, field.name))}"
                for field in fields(row)
            ]
            if self.report is not None:
                lines.extend(self.report.observations)
        self.set_details(lines)

    def table_details(self, row: DynamoDbTable) -> list[str]:
        if self.pending_detail == row.name:
            return [row.name, "Loading table metadata…"]
        report = self.detail_reports.get((View.DYNAMODB, row.name))
        if report is None:
            return [row.name, "Press Enter to load table metadata."]
        table = next((item for item in report.rows if isinstance(item, DynamoDbTable)), None)
        if table is None:
            return [row.name, "Table metadata unavailable. Press Enter to retry."]
        size = decimal(table.size_bytes) if table.size_bytes is not None else "Unknown"
        items = f"{table.item_count:,}" if table.item_count is not None else "Unknown"
        billing = BILLING_MODES.get(table.billing_mode or "", "Unknown")
        status = stack_status(table.status) if table.status else "Unknown"
        return [
            table.name,
            self.managing_stack(table, report),
            f"Status: {status} | Billing: {billing}",
            *self.configured_consumers(table, report),
            f"Deletion protection: {ACTION_LABELS[table.deletion_protection]}",
            f"Approx. size: {size} | Approx. items: {items}",
            f"Table ARN: {field_value(table.arn)}",
        ]

    def appsync_details(self, api: AppSyncApi) -> list[str]:
        if self.pending_detail == api.api_id:
            return [api.name, "Loading data sources…"]
        report = self.detail_reports.get((View.APPSYNC, api.api_id))
        if report is None:
            return [api.name, "Press Enter to load DynamoDB data sources."]
        lines = [api.name, "Configured DynamoDB targets"]
        if not report.complete:
            lines.append("Partial · Press Enter to retry")
        if not report.rows:
            lines.append("No DynamoDB targets retrieved.")
        for row in report.rows:
            if isinstance(row, AppSyncTableSource):
                name = f"{row.name} (delta sync)" if row.delta_sync else row.name
                lines.append(f"{name} → {row.table_name} · {row.table_region}")
                if row.table_arn is None:
                    lines.append("  Target account unverified")
        return lines

    def configured_consumers(self, table: DynamoDbTable, report: Report) -> list[str]:
        apis = self.appsync_apis
        scope = (report.identity.account_id, report.regions)
        if table.arn is None or apis is None or (apis.identity.account_id, apis.regions) != scope:
            return ["AppSync lookup incomplete · Open AppSync data sources"]
        matches = []
        complete = apis.complete
        for api in apis.rows:
            if not isinstance(api, AppSyncApi):
                continue
            sources = self.detail_reports.get((View.APPSYNC, api.api_id))
            if sources is None or (sources.identity.account_id, sources.regions) != scope:
                complete = False
                continue
            complete = complete and sources.complete
            for row in sources.rows:
                if not isinstance(row, AppSyncTableSource):
                    continue
                if row.table_arn == table.arn:
                    suffix = " (delta sync)" if row.delta_sync else ""
                    matches.append(f"Configured AppSync: {api.name} / {row.name}{suffix}")
                elif (
                    row.table_arn is None
                    and row.table_name == table.name
                    and row.table_region in report.regions
                ):
                    complete = False
        if matches:
            return matches
        return ["No configured AppSync match found" if complete else "AppSync lookup incomplete"]

    def managing_stack(self, table: DynamoDbTable, report: Report) -> str:
        stacks = self.stack_reports.get(None)
        if (
            not table.arn
            or not table.created_at
            or stacks is None
            or stacks.identity.account_id != report.identity.account_id
            or stacks.regions != report.regions
        ):
            return "Stack lookup incomplete"

        complete = stacks.complete
        matches: list[str] = []
        created_at = datetime.fromisoformat(table.created_at)
        for stack in stacks.rows:
            if not isinstance(stack, CloudFormationStack):
                continue
            resources = self.stack_reports.get(stack.stack_id) if stack.stack_id else None
            if (
                resources is None
                or resources.identity.account_id != report.identity.account_id
                or resources.regions != report.regions
            ):
                complete = False
                continue
            complete = complete and resources.complete
            for resource in resources.rows:
                if (
                    not isinstance(resource, CloudFormationResource)
                    or resource.resource_type not in TABLE_RESOURCE_TYPES
                    or resource.physical_id not in (table.name, table.arn)
                    or resource.status in ("DELETE_COMPLETE", "DELETE_SKIPPED")
                ):
                    continue
                if (
                    stack.status.startswith("DELETE_")
                    or resource.status not in TABLE_MEMBERSHIP_STATES
                    or not resource.changed_at
                    or datetime.fromisoformat(resource.changed_at) < created_at
                ):
                    complete = False
                    continue
                matches.append(stack.name)
                break

        if len(matches) == 1:
            return f"Managing stack (recorded): {matches[0]}"
        if matches:
            return "Stack match ambiguous"
        return "No stack match found" if complete else "Stack lookup incomplete"

    def history_details(self) -> list[str]:
        if self.alarm_history is None:
            return ["", self.empty_message]
        changes = [
            f"{row.timestamp}  {alarm_status(row.previous_state)[0]} → "
            f"{alarm_status(row.new_state)[0]}"
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
        picker = self.query_one(Select)
        if picker.expanded:
            picker.expanded = False
            picker.focus()
            return
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()

    def current_stack_id(self) -> str | None:
        return self.stack_path[-1] if self.stack_path else None

    def show_stack_level(self) -> None:
        stack_id = self.current_stack_id()
        self.set_columns()
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()
        self.refresh_bindings()
        if self.load_view is None:
            self.report = demo_stacks(stack_id)
            self.stack_reports[stack_id] = self.report
            self.populate("")
            return
        self.report = self.stack_reports.get(stack_id)
        if self.report is None:
            self.start_scan(stack_id)
        else:
            self.show_status(self.report, cached=True)
            self.populate("")

    def action_back_stack(self) -> None:
        self.stack_path.pop()
        self.show_stack_level()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "open_views":
            return None if self.scanning or self.identity_failed else True
        if action == "back_stack":
            if self.view is not View.STACKS or not self.stack_path:
                return False
            return None if self.scanning or self.identity_failed else True
        if action == "refresh_costs":
            if self.load_view is None or self.view is not View.COSTS:
                return False
            return None if self.scanning or self.identity_failed else True
        if action == "reset_demo" and self.load_view is not None:
            return False
        return super().check_action(action, parameters)

    async def action_quit(self) -> None:
        self.exit(return_code=self.scan_exit_code)

    def action_refresh_costs(self) -> None:
        self.start_scan()

    def action_reset_demo(self) -> None:
        if self.view is View.STACKS:
            self.stack_path.clear()
            self.show_stack_level()
            return
        self.apps = demo_apps() if self.view is View.AMPLIFY else []
        if self.view is View.CLOUDWATCH:
            self.report = demo_alarms()
        elif self.view is View.EC2:
            self.report = demo_instances()
        elif self.view is View.DYNAMODB:
            self.report = demo_tables(None)
            self.detail_reports = {
                key: report
                for key, report in self.detail_reports.items()
                if key[0] is not View.DYNAMODB
            }
        elif self.view is View.APPSYNC:
            self.report = self.appsync_apis = demo_appsync(None)
        else:
            self.report = None
        self.query_one(Input).value = ""
        self.populate("")
        self.query_one(DataTable).focus()
