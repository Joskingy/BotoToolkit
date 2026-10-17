"""CLI options, identity gate, output streams, and exit codes."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from amplify_ops.appsync import key_expirations
from amplify_ops.aws import AuthenticationFailure, AwsAccess, ResourceFailure
from amplify_ops.comparison import compare_configuration
from amplify_ops.costs import cost_report
from amplify_ops.deployments import DeploymentBlocked, create_plan, execute_plan, load_plan
from amplify_ops.inventory import collect_inventory, timestamp
from amplify_ops.investigation import investigate_job
from amplify_ops.models import Comparison, Inventory, Investigation, Report
from amplify_ops.presentation import (
    json_report,
    render_comparison,
    render_investigation,
    render_report,
    render_table,
)
from amplify_ops.stale import stale_environments

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
diagnostics = Console(stderr=True, markup=False, highlight=False)


class OutputFormat(StrEnum):
    table = "table"
    json = "json"


@dataclass(frozen=True)
class Settings:
    profile: str
    expected_account: str
    regions: list[str]


@app.callback()
def configure(
    ctx: typer.Context,
    profile: Annotated[str, typer.Option(help="Explicit local AWS profile; use brewmaster here.")],
    expected_account: Annotated[str, typer.Option(help="Expected 12-digit AWS account ID.")],
    region: Annotated[list[str], typer.Option(help="Selected AWS region; repeat for inventory.")],
) -> None:
    """Verify AWS identity, report on Amplify resources, and plan controlled job retries."""
    if not profile.strip() or "<" in profile or ">" in profile:
        raise typer.BadParameter("Provide a resolved, explicit profile.", param_hint="--profile")
    if not re.fullmatch(r"[0-9]{12}", expected_account):
        raise typer.BadParameter("Use a 12-digit account ID.", param_hint="--expected-account")
    if any(not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", item) for item in region):
        raise typer.BadParameter("Use resolved AWS region names.", param_hint="--region")
    ctx.obj = Settings(profile, expected_account, list(dict.fromkeys(region)))


def verified_access(settings: Settings) -> AwsAccess:
    access = AwsAccess.connect(settings.profile, settings.expected_account, settings.regions[0])
    diagnostics.print(f"Verified account: {access.identity.account_id}")
    diagnostics.print(f"Caller ARN: {access.identity.caller_arn}")
    diagnostics.print(f"Regions: {', '.join(settings.regions)}")
    return access


@app.command()
def identity(ctx: typer.Context) -> None:
    """Verify the selected profile's account and display its caller ARN."""
    try:
        access = verified_access(ctx.obj)
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    console = Console(markup=False, highlight=False)
    console.print(f"Account: {access.identity.account_id}")
    console.print(f"Caller ARN: {access.identity.caller_arn}")


@app.command()
def inventory(
    ctx: typer.Context,
    format: Annotated[OutputFormat, typer.Option(help="Output format.")] = OutputFormat.table,
    output: Annotated[
        Path | None, typer.Option(help="Also write the JSON report to this file.")
    ] = None,
) -> None:
    """List apps, branches, and latest deployments in explicitly selected regions."""
    try:
        access = verified_access(ctx.obj)
        report = collect_inventory(access, ctx.obj.regions)
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


def emit_report(
    report: Inventory | Investigation | Comparison | Report,
    format: OutputFormat,
    output: Path | None,
) -> None:
    document = json_report(report)
    if format == OutputFormat.json:
        typer.echo(document, nl=False)
    else:
        console = Console(markup=False, highlight=False)
        if isinstance(report, Inventory):
            render_table(report, console)
        elif isinstance(report, Investigation):
            render_investigation(report, console)
        elif isinstance(report, Comparison):
            render_comparison(report, console)
        else:
            render_report(report, console)
    if output is not None:
        try:
            # Exclusive creation prevents accidental destruction of existing files.
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(document)
        except OSError:
            diagnostics.print("Cannot write JSON output; check the path and use a new filename.")
            raise typer.Exit(1) from None
        diagnostics.print("JSON report written.")
    for error in report.errors:
        location = "/".join(filter(None, [error.region, error.app_id, error.branch_name]))
        diagnostics.print(f"{location}: {error.operation}: {error.category} ({error.code})")
    if not report.complete:
        diagnostics.print("PARTIAL report: results are incomplete.")
        raise typer.Exit(3)


@app.command()
def investigate(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Option(help="Amplify app ID.")],
    branch: Annotated[str, typer.Option(help="Branch name, including feature/ prefixes.")],
    job_id: Annotated[
        str | None, typer.Option(help="Specific job ID; default: latest failed job.")
    ] = None,
    inspect_logs: Annotated[
        bool, typer.Option(help="Inspect bounded failed-step logs for safe clues.")
    ] = False,
    format: Annotated[OutputFormat, typer.Option(help="Output format.")] = OutputFormat.table,
    output: Annotated[Path | None, typer.Option(help="Also write JSON to a new file.")] = None,
) -> None:
    """Investigate a failed deployment or explicitly selected job (read-only)."""
    validate_target(ctx.obj, app_id, [(branch, "--branch")])
    if job_id is not None and not re.fullmatch(r"[0-9]{1,255}", job_id):
        raise typer.BadParameter("Use a numeric job ID.", param_hint="--job-id")
    try:
        access = verified_access(ctx.obj)
        report = investigate_job(
            access,
            ctx.obj.regions[0],
            app_id,
            branch,
            job_id,
            inspect_logs,
        )
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


def validate_target(settings: Settings, app_id: str, branches: list[tuple[str, str]]) -> None:
    if len(settings.regions) != 1:
        raise typer.BadParameter(
            "Select exactly one region for this command.", param_hint="--region"
        )
    if not re.fullmatch(r"d[a-z0-9]{1,19}", app_id):
        raise typer.BadParameter("Use an Amplify app ID.", param_hint="--app-id")
    for branch, option in branches:
        if (
            not branch.strip()
            or len(branch) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in branch)
            or "<" in branch
            or ">" in branch
        ):
            raise typer.BadParameter("Provide a resolved branch name.", param_hint=option)


@app.command()
def compare(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Option(help="Amplify app ID.")],
    source: Annotated[str, typer.Option(help="Source branch.")] = "dev",
    target: Annotated[str, typer.Option(help="Target branch.")] = "main",
    format: Annotated[
        OutputFormat, typer.Option(help="Output format; values are always redacted.")
    ] = OutputFormat.table,
    output: Annotated[
        Path | None, typer.Option(help="Also write redacted JSON to a new file.")
    ] = None,
) -> None:
    """Compare two branches and shared app configuration without exporting values."""
    validate_target(ctx.obj, app_id, [(source, "--source"), (target, "--target")])
    if source == target:
        raise typer.BadParameter("Select two distinct branches.", param_hint="--target")
    try:
        access = verified_access(ctx.obj)
        report = compare_configuration(access, ctx.obj.regions[0], app_id, source, target)
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


@app.command("api-keys")
def api_keys(
    ctx: typer.Context,
    api_id: Annotated[
        list[str] | None, typer.Option(help="Explicit GraphQL API ID; repeat as needed.")
    ] = None,
    app_id: Annotated[
        str | None, typer.Option(help="Operator-asserted association; requires --api-id.")
    ] = None,
    warn_days: Annotated[
        int, typer.Option(min=0, max=365, help="Expiry warning window in days.")
    ] = 30,
    format: OutputFormat = OutputFormat.table,
    output: Path | None = None,
) -> None:
    """Report GraphQL API-key expiration without printing API keys."""
    if app_id:
        if not api_id:
            raise typer.BadParameter(
                "An app association requires explicitly selected --api-id values."
            )
        if not re.fullmatch(r"d[a-z0-9]{1,19}", app_id):
            raise typer.BadParameter("Use an Amplify app ID.", param_hint="--app-id")
    if any(not re.fullmatch(r"[a-zA-Z0-9-]{1,200}", value) for value in api_id or []):
        raise typer.BadParameter("Provide resolved API IDs.", param_hint="--api-id")
    try:
        access = verified_access(ctx.obj)
        report = key_expirations(
            access, ctx.obj.regions, list(dict.fromkeys(api_id or [])), app_id, warn_days
        )
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


@app.command("costs")
def costs(
    ctx: typer.Context,
    start: Annotated[str, typer.Option(help="Inclusive ISO start date.")],
    end: Annotated[str, typer.Option(help="Exclusive ISO end date; no later than today UTC.")],
    tag_key: str | None = None,
    tag_value: str | None = None,
    format: OutputFormat = OutputFormat.table,
    output: Path | None = None,
) -> None:
    """Report verified-account costs by service, optionally with a tag-based estimate."""
    if ctx.obj.regions != ["us-east-1"]:
        raise typer.BadParameter(
            "Select us-east-1 for the Cost Explorer endpoint; billing scope is all regions."
        )
    if (tag_key is None) != (tag_value is None) or tag_key == "" or tag_value == "":
        raise typer.BadParameter("Supply both nonempty --tag-key and --tag-value, or neither.")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if not first < last or last > datetime.now(UTC).date():
            raise ValueError
    except ValueError:
        raise typer.BadParameter("Use ISO dates with start < end <= today UTC.") from None
    try:
        access = verified_access(ctx.obj)
        report = cost_report(access, first, last, tag_key, tag_value)
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


@app.command("stale")
def stale(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Option(help="Amplify app ID.")],
    repository: Annotated[str, typer.Option(help="Explicit GitHub mapping: OWNER/REPO.")],
    older_than: Annotated[int, typer.Option(min=1, max=3650)] = 90,
    format: OutputFormat = OutputFormat.table,
    output: Path | None = None,
) -> None:
    """Report conservative stale Hosting branch candidates using AWS and GitHub evidence."""
    validate_target(ctx.obj, app_id, [])
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository
    ) or repository.split("/")[-1] in {".", ".."}:
        raise typer.BadParameter("Use a GitHub OWNER/REPO mapping.", param_hint="--repository")
    try:
        access = verified_access(ctx.obj)
        report = stale_environments(access, ctx.obj.regions[0], app_id, repository, older_than)
    except AuthenticationFailure as error:
        diagnostics.print(str(error))
        raise typer.Exit(1) from None
    emit_report(report, format, output)


@app.command("deploy-plan")
def deploy_plan(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Option(help="Amplify app ID.")],
    branch: Annotated[str, typer.Option(help="Explicit branch to retry.")],
    job_id: Annotated[str, typer.Option(help="Completed source job ID.")],
    output: Annotated[Path, typer.Option(help="New JSON plan file to review before execution.")],
    format: OutputFormat = OutputFormat.table,
) -> None:
    """Plan RETRY of a completed job, with read-only preflight; never deploys."""
    validate_target(ctx.obj, app_id, [(branch, "--branch")])
    if not re.fullmatch(r"[0-9]{1,255}", job_id):
        raise typer.BadParameter("Use a numeric job ID.", param_hint="--job-id")
    try:
        access = verified_access(ctx.obj)
        plan = create_plan(access, ctx.obj.regions[0], app_id, branch, job_id)
    except (AuthenticationFailure, DeploymentBlocked, ResourceFailure) as error:
        diagnostics.print(
            str(error)
            if not isinstance(error, ResourceFailure)
            else f"Preflight failed: {error.error.code}"
        )
        raise typer.Exit(1) from None
    report = Report(
        access.identity, "deployment_plan", timestamp(datetime.now(UTC)), ctx.obj.regions
    )
    report.rows.append(plan)
    report.observations = [
        "Read-only plan; no deployment submitted. Review the target and source job/commit. "
        "Plan expires in 15 minutes. Execution needs plan-ID confirmation "
        "and separate write permissions.",
        "Only RETRY is supported. No automatic rollback; "
        "backend changes/build configuration can affect a retry.",
    ]
    emit_report(report, format, output)


@app.command("deploy")
def deploy(
    ctx: typer.Context,
    plan: Annotated[Path, typer.Option(help="Reviewed JSON plan file.")],
    confirm_plan: Annotated[
        str, typer.Option(help="Exact reviewed plan ID; this authorizes a write.")
    ],
    confirm_production: str | None = None,
    audit_dir: Path = Path(".amplify-ops/audit"),
    format: OutputFormat = OutputFormat.table,
    output: Path | None = None,
) -> None:
    """Execute a reviewed retry plan (WRITES AWS); no automatic retry or rollback."""
    try:
        selected = load_plan(plan)
        validate_target(ctx.obj, selected.app_id, [(selected.branch, "--branch")])
        if ctx.obj.regions != [selected.region] or ctx.obj.expected_account != selected.account_id:
            raise DeploymentBlocked("CLI account/region must match the reviewed plan.")
        if confirm_plan != selected.plan_id:
            raise DeploymentBlocked("--confirm-plan must match the reviewed plan ID.")
        if selected.production and confirm_production != selected.branch:
            raise DeploymentBlocked(
                "Production requires --confirm-production with the branch name."
            )
        access = verified_access(ctx.obj)
        report = execute_plan(access, selected, confirm_plan, confirm_production, audit_dir)
    except (AuthenticationFailure, DeploymentBlocked, ResourceFailure) as error:
        diagnostics.print(
            str(error)
            if not isinstance(error, ResourceFailure)
            else f"Deployment preflight failed: {error.error.code}"
        )
        raise typer.Exit(1) from None
    emit_report(report, format, output)
