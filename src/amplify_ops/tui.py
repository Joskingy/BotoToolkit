"""Optional offline terminal browser over synthetic, allowlisted report models."""

import unicodedata

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static

from amplify_ops.models import App as ReportApp
from amplify_ops.models import Branch
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


class DemoBrowser(App[None]):
    """An explicitly offline prototype; no live-data provider or write actions."""

    TITLE = "BotoToolkit"
    SUB_TITLE = "Offline prototype"
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

    def __init__(self) -> None:
        super().__init__()
        self.apps = demo_apps()
        self.rows: dict[str, tuple[ReportApp, Branch | None]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "OFFLINE DEMO | Synthetic data | AWS not connected | No write actions", id="banner"
        )
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
        self.query_one("#summary", Static).update(
            f"{len(self.rows)} matching rows | Sample: 2026-01-15 | Tab: change panel"
        )
        if self.rows:
            table.move_cursor(row=0, column=0)
            self.show_details(next(iter(self.rows)))
        else:
            self.query_one("#details", Static).update("No matches. Change the search or press Esc.")

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
        lines = [
            f"{app.name} / {branch.name if branch else '(no branch)'}",
            f"Synthetic app: {app.app_id} | Region: {app.region}",
            f"Stage: {branch.stage or 'Unknown' if branch else 'Not applicable'}",
            f"Deployment: {deployment_status(branch, app)}",
            f"Branch listing: {listing}",
            f"Job: {job.job_id if job else 'Not available'}",
            f"Started: {job.start_time if job else 'Not available'}",
            f"Ended: {job.end_time or 'Not recorded' if job else 'Not available'}",
            "Sample only. Investigation, comparison, AWS refresh and deployment are not enabled.",
        ]
        self.query_one("#details", Static).update(Text("\n".join(plain(line) for line in lines)))
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_reset_search(self) -> None:
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()

    def action_reset_demo(self) -> None:
        self.apps = demo_apps()
        self.query_one(Input).value = ""
        self.populate("")
        self.query_one(DataTable).focus()
