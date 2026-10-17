"""Render only the allowlisted report model."""

import json
from dataclasses import asdict, fields

from rich.console import Console
from rich.table import Table

from amplify_ops.models import Comparison, Inventory, Investigation, Report


def json_report(report: Inventory | Investigation | Comparison | Report) -> str:
    return json.dumps(asdict(report), indent=2, ensure_ascii=True) + "\n"


def render_table(report: Inventory, console: Console) -> None:
    console.print("COMPLETE scan" if report.complete else "PARTIAL scan (incomplete)")
    # Two linked tables keep repository URLs readable without squeezing branch data.
    apps = Table(title="Amplify Hosting apps", show_lines=True)
    for name in ("Region", "App ID", "Name", "Repository", "Default domain", "Branches read"):
        apps.add_column(name, overflow="fold")
    branches = Table(title="Branches and latest deployments", show_lines=True)
    for name in ("Region", "App ID", "Branch", "Configured stage", "Status", "Started (UTC)"):
        branches.add_column(name, overflow="fold")
    for app in report.apps:
        apps.add_row(
            app.region,
            app.app_id,
            app.name,
            app.repository or "-",
            app.default_domain or "-",
            str(len(app.branches)) + ("" if app.branches_complete else " (incomplete)"),
        )
        if not app.branches:
            branches.add_row(
                app.region,
                app.app_id,
                "(no branches)" if app.branches_complete else "(unknown)",
                "-",
                "-",
                "-",
            )
        for branch in app.branches:
            job = branch.latest_deployment
            status = (
                job.status
                if job
                else ("No deployments" if branch.deployments_complete else "Unknown (incomplete)")
            )
            branches.add_row(
                app.region,
                app.app_id,
                branch.name,
                branch.stage or "-",
                status,
                job.start_time if job else "-",
            )
    console.print(apps)
    console.print(branches)
    if not report.apps:
        console.print(
            "No apps found." if report.complete else "No apps retrieved; see scan errors."
        )


def render_investigation(report: Investigation, console: Console) -> None:
    console.print(
        "COMPLETE investigation" if report.complete else "PARTIAL investigation (incomplete)"
    )
    console.print(f"Target: {report.region} / {report.app_id} / {report.branch_name}")
    if report.job is not None:
        console.print(
            f"Job {report.job.job_id}: {report.job.status}; started {report.job.start_time}"
        )
        table = Table(title="Execution steps", show_lines=True)
        for name in ("Step", "Status", "Started (UTC)", "Ended (UTC)", "Log review"):
            table.add_column(name, overflow="fold")
        for step in report.steps:
            table.add_row(
                step.name, step.status, step.start_time or "-", step.end_time or "-", step.log.state
            )
        console.print(table)
        for step in report.steps:
            for evidence in step.log.findings:
                console.print(
                    f"{step.name}, log line {evidence.line}: {evidence.category}. "
                    f"{evidence.suggestion}"
                )
    for observation in report.observations:
        console.print(observation)


def render_comparison(report: Comparison, console: Console) -> None:
    console.print("COMPLETE comparison" if report.complete else "PARTIAL comparison (incomplete)")
    console.print(f"Target: {report.region} / {report.app_id}")
    console.print(f"Source: {report.source_branch}; target: {report.target_branch}")
    console.print(f"Configuration differences found: {report.differences_found}")
    table = Table(title="Configuration comparison (all values redacted)", show_lines=True)
    for name in ("Section", "Key", "Source origin", "Target origin", "Result"):
        table.add_column(name, overflow="fold")
    for item in report.entries:
        if item.result != "absent_both":
            table.add_row(
                item.section, item.key, item.source_origin, item.target_origin, item.result
            )
    console.print(table)
    for observation in report.observations:
        console.print(observation)


def render_report(report: Report, console: Console) -> None:
    console.print(("COMPLETE " if report.complete else "PARTIAL ") + report.report_type)
    groups = {}
    for row in report.rows:
        groups.setdefault(type(row), []).append(row)
    for row_type, rows in groups.items():
        table = Table(title=row_type.__name__, show_lines=True)
        names = [item.name for item in fields(row_type)]
        for name in names:
            table.add_column(name, overflow="fold")
        for row in rows:
            table.add_row(
                *(
                    str(getattr(row, name)) if getattr(row, name) is not None else "-"
                    for name in names
                )
            )
        console.print(table)
    if not report.rows:
        console.print(
            "No rows retrieved." if not report.complete else "No matching resources/costs found."
        )
    for observation in report.observations:
        console.print(observation)
