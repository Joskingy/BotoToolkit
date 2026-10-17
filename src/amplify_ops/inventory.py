"""Inventory collection and latest-job selection, independent of terminal output."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from amplify_ops.aws import AmplifyReader, AwsAccess, ResourceFailure
from amplify_ops.models import App, Branch, Deployment, Inventory


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def safe_repository(value: str | None) -> str | None:
    """Remove embedded userinfo, query strings, and fragments from repository URLs."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"https", "http", "ssh", "git"} or not parts.hostname:
            return "[unsupported repository URL redacted]"
        host = parts.hostname
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return "[invalid repository URL redacted]"


def job_key(job: dict[str, Any]) -> tuple[datetime, int, str]:
    """Start time defines latest; numeric ID breaks ties deterministically."""
    job_id = job["jobId"]
    return job["startTime"].astimezone(UTC), int(job_id) if job_id.isdigit() else -1, job_id


def collect_deployment(reader: AmplifyReader, app: App, branch: Branch, report: Inventory) -> None:
    latest = None
    try:
        for job in reader.items(
            "list_jobs", "jobSummaries", app_id=app.app_id, branch_name=branch.name
        ):
            if latest is None or job_key(job) > job_key(latest):
                latest = job
        branch.deployments_complete = True
    except ResourceFailure as error:
        report.add_error(error.error)
        # A later page may hold the actual latest deployment. Leave it unknown.
        return
    if latest is not None:
        branch.latest_deployment = Deployment(
            job_id=latest["jobId"],
            status=latest["status"],
            start_time=timestamp(latest["startTime"]),
            end_time=timestamp(latest["endTime"]) if latest.get("endTime") else None,
        )


def collect_branches(reader: AmplifyReader, app: App, report: Inventory) -> None:
    try:
        for raw in reader.items("list_branches", "branches", app_id=app.app_id):
            branch = Branch(name=raw["branchName"], stage=raw.get("stage"))
            app.branches.append(branch)
            collect_deployment(reader, app, branch, report)
        app.branches_complete = True
    except ResourceFailure as error:
        report.add_error(error.error)


def collect_inventory(access: AwsAccess, regions: list[str]) -> Inventory:
    report = Inventory(access.identity, list(regions), timestamp(datetime.now(UTC)))
    for region in regions:
        reader = None
        try:
            reader = access.amplify(region)
            for raw in reader.items("list_apps", "apps"):
                app = App(
                    region=region,
                    app_id=raw["appId"],
                    name=raw["name"],
                    repository=safe_repository(raw.get("repository")),
                    default_domain=raw.get("defaultDomain"),
                )
                report.apps.append(app)
                collect_branches(reader, app, report)
        except ResourceFailure as error:
            report.add_error(error.error)
        finally:
            if reader is not None:
                reader.close()
    return report
