"""Optional terminal browser for offline demo and read-only Amplify inventory."""

import unicodedata
from collections.abc import Callable

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static
from textual.worker import Worker, WorkerState, get_current_worker

from amplify_ops.aws import AuthenticationFailure
from amplify_ops.models import App as ReportApp
from amplify_ops.models import Branch, Inventory
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


class InventoryBrowser(App[None]):
    TITLE = "BotoToolkit"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $surface; }
    #banner { height: auto; padding: 0 1; background: $primary; text-style: bold; }
    #search { margin: 1 1 0 1; }
    #summary { height: 1; margin: 0 1; }
    #resources { height: 1fr; min-height: 5; margin: 0 1; border: round $primary; }
    #detail-scroll { height: 1fr; min-height: 5; max-height: 11;
                     margin: 0 1; border: round $accent; }
    #details { height: auto; padding: 0 1; }
    """
    BINDINGS = [
        Binding("slash", "search", "Search"),
        Binding("escape", "reset_search", "Clear search", priority=True),
        Binding("ctrl+r", "reset_demo", "Reset demo", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self, load_inventory: Callable[[Callable[[], bool]], Inventory] | None = None
    ) -> None:
        super().__init__()
        self.load_inventory = load_inventory
        self.sub_title = "Offline demo" if load_inventory is None else "Amplify inventory"
        self.apps = demo_apps() if load_inventory is None else []
        self.empty_message = "Loading Amplify inventory…" if load_inventory else ""
        self.scan_exit_code = 0
        self.rows: dict[str, tuple[ReportApp, Branch | None]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        banner = (
            "OFFLINE DEMO | Synthetic data | AWS not connected | No write actions"
            if self.load_inventory is None
            else "LIVE | Read-only | Loading Amplify inventory"
        )
        yield Static(banner, id="banner", markup=False)
        yield Input(placeholder="Search app, branch, region or status…", id="search")
        yield Static(id="summary")
        yield DataTable(id="resources", cursor_type="row", zebra_stripes=True)
        with VerticalScroll(id="detail-scroll"):
            yield Static(id="details", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("App", "Branch", "Region", "Deployment")
        self.populate("")
        table.focus()
        if self.load_inventory is not None:
            self.scan(self.load_inventory)

    @work(thread=True)
    def scan(self, load_inventory: Callable[[Callable[[], bool]], Inventory]) -> Inventory | str:
        worker = get_current_worker()
        try:
            return load_inventory(lambda: worker.is_cancelled)
        except AuthenticationFailure as error:
            return str(error)
        except Exception:
            # Avoid rendering tracebacks that could include live service data.
            return "Amplify inventory scan failed."

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state is not WorkerState.SUCCESS:
            return
        result = event.worker.result
        banner = self.query_one("#banner", Static)
        if isinstance(result, str):
            self.scan_exit_code = 1
            banner.update("LIVE | Read-only | Scan failed")
            self.empty_message = plain(result)
        elif isinstance(result, Inventory):
            self.apps = result.apps
            status = "Complete"
            self.empty_message = "No Amplify apps in this region."
            if not result.complete:
                self.scan_exit_code = 3
                limits = {
                    "PageLimit": "page limit reached",
                    "TimeLimit": "time limit reached",
                    "Cancelled": "scan cancelled",
                }
                limit = next((error for error in result.errors if error.category == "limit"), None)
                reason = limits[limit.code] if limit else "some AWS data could not be read"
                status = f"PARTIAL ({reason})"
                self.empty_message = "No apps collected. Inventory is incomplete."
            banner.update(
                plain(
                    f"LIVE | Read-only | Account {result.identity.account_id} | "
                    f"{result.regions[0]} | {status} | Started {result.generated_at}"
                )
            )
        self.populate(self.query_one(Input).value)

    def populate(self, query: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.rows.clear()
        needle = query.strip().casefold()
        for app_index, app in enumerate(self.apps):
            for branch_index, branch in enumerate(app.branches or [None]):
                values = (
                    app.name,
                    branch.name if branch else "—",
                    app.region,
                    deployment_status(branch, app),
                )
                if needle not in " ".join(values).casefold():
                    continue
                key = f"{app_index}:{branch_index}"
                self.rows[key] = app, branch
                table.add_row(*(Text(plain(value)) for value in values), key=key)
        sample = " | Sample: 2026-01-15" if self.load_inventory is None else ""
        self.query_one("#summary", Static).update(
            f"{len(self.rows)} matching rows{sample} | Tab: change panel"
        )
        if self.rows:
            table.move_cursor(row=0, column=0)
            self.show_details(next(iter(self.rows)))
        else:
            message = self.empty_message if not self.apps else ""
            self.query_one("#details", Static).update(
                message or "No matches. Change the search or press Esc."
            )

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

    def show_details(self, key: str) -> None:
        app, branch = self.rows[key]
        job = branch.latest_deployment if branch and branch.deployments_complete else None
        listing = "Complete" if app.branches_complete else "PARTIAL — branches may be missing"
        app_label = "Synthetic app" if self.load_inventory is None else "App ID"
        lines = [
            f"{app.name} / {branch.name if branch else '(no branch)'}",
            f"{app_label}: {app.app_id} | Region: {app.region}",
            f"Stage: {branch.stage or 'Unknown' if branch else 'Not applicable'}",
            f"Deployment: {deployment_status(branch, app)}",
            f"Branch listing: {listing}",
            f"Job: {job.job_id if job else 'Not available'}",
            f"Started: {job.start_time if job else 'Not available'}",
            f"Ended: {job.end_time or 'Not recorded' if job else 'Not available'}",
        ]
        self.query_one("#details", Static).update(Text("\n".join(plain(line) for line in lines)))
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_reset_search(self) -> None:
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "reset_demo" and self.load_inventory is not None:
            return False
        return super().check_action(action, parameters)

    async def action_quit(self) -> None:
        self.exit(return_code=self.scan_exit_code)

    def action_reset_demo(self) -> None:
        self.apps = demo_apps()
        self.query_one(Input).value = ""
        self.populate("")
        self.query_one(DataTable).focus()
