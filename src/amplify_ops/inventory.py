"""Inventory collection and latest-job selection, independent of terminal output."""

import json
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from amplify_ops.aws import (
    AmplifyReader,
    AwsAccess,
    InventoryBudget,
    InventoryLimitReached,
    ResourceFailure,
    ServiceReader,
)
from amplify_ops.models import (
    AlarmStateChange,
    App,
    Branch,
    CloudTrailChange,
    CloudWatchAlarm,
    Deployment,
    DiscoveredResource,
    EbsCandidate,
    Ec2Instance,
    Inventory,
    Report,
    ResourceCount,
    ScanError,
)


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


def collect_inventory(
    access: AwsAccess, regions: list[str], *, budget: InventoryBudget | None = None
) -> Inventory:
    report = Inventory(access.identity, list(regions), timestamp(datetime.now(UTC)))
    for region in regions:
        reader = None
        try:
            reader = access.amplify(region, budget=budget)
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
        except InventoryLimitReached as error:
            report.add_error(error.error)
            break
        except ResourceFailure as error:
            report.add_error(error.error)
        finally:
            if reader is not None:
                reader.close()
    return report


def collect_ec2_inventory(
    access: AwsAccess, regions: list[str], owner: str | None, environment: str | None
) -> Report:
    report = Report(access.identity, "ec2_inventory", timestamp(datetime.now(UTC)), regions)
    report.observations.append(
        "Missing health checks are unknown. Auto Scaling group comes from the AWS-managed tag."
    )
    filters = [
        {"Name": f"tag:{key}", "Values": [value]}
        for key, value in (("Owner", owner), ("Environment", environment))
        if value is not None
    ]
    for region in regions:
        instances: list[dict[str, Any]] = []
        statuses: dict[str, dict[str, Any]] = {}
        try:
            with closing(access.service("ec2", region)) as reader:
                for page in reader.pages(
                    "describe_instances", **({"Filters": filters} if filters else {})
                ):
                    for reservation in page.get("Reservations", []):
                        instances.extend(reservation.get("Instances", []))
                for ids in batched(
                    (instance["InstanceId"] for instance in instances), 100, strict=False
                ):
                    for page in reader.pages(
                        "describe_instance_status", InstanceIds=list(ids), IncludeAllInstances=True
                    ):
                        for status in page.get("InstanceStatuses", []):
                            statuses[status["InstanceId"]] = status
        except ResourceFailure as error:
            report.add_error(error.error)
        for instance in instances:
            tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
            status = statuses.get(instance["InstanceId"], {})
            report.rows.append(
                Ec2Instance(
                    region,
                    instance["InstanceId"],
                    tags.get("Name"),
                    instance.get("State", {}).get("Name"),
                    instance.get("InstanceType"),
                    tags.get("Owner"),
                    tags.get("Environment"),
                    tags.get("aws:autoscaling:groupName"),
                    status.get("InstanceStatus", {}).get("Status"),
                    status.get("SystemStatus", {}).get("Status"),
                    [
                        mapping["Ebs"]["VolumeId"]
                        for mapping in instance.get("BlockDeviceMappings", [])
                        if mapping.get("Ebs", {}).get("VolumeId")
                    ],
                )
            )
    return report


_ALARM_STATES = ("OK", "ALARM", "INSUFFICIENT_DATA")
_ALARM_TYPES = ("MetricAlarm", "CompositeAlarm", "LogAlarm")


def _alarm_states(history_data: str) -> tuple[str | None, str | None]:
    try:
        data = json.loads(history_data)
    except ValueError, RecursionError:
        return None, None
    if not isinstance(data, dict):
        return None, None

    def state(key: str) -> str | None:
        details = data.get(key)
        value = details.get("stateValue") if isinstance(details, dict) else None
        return value if value in _ALARM_STATES else None

    return state("oldState"), state("newState")


def collect_cloudwatch_alarms(
    access: AwsAccess, regions: list[str], state: str | None, alarm_name: str | None
) -> Report:
    report = Report(access.identity, "cloudwatch_alarms", timestamp(datetime.now(UTC)), regions)
    params: dict[str, Any] = {"AlarmTypes": list(_ALARM_TYPES)}
    if state is not None:
        params["StateValue"] = state
    if alarm_name is not None:
        params["AlarmNames"] = [alarm_name]
        report.observations.append(
            "History includes up to 20 recent state updates per matching alarm."
        )
    for region in regions:
        matched: list[CloudWatchAlarm] = []
        try:
            with closing(access.service("cloudwatch", region)) as reader:
                for page in reader.pages("describe_alarms", **params):
                    for alarm_type in _ALARM_TYPES:
                        for alarm in page.get(f"{alarm_type}s", []):
                            updated = alarm.get("StateUpdatedTimestamp")
                            row = CloudWatchAlarm(
                                region,
                                alarm["AlarmName"],
                                alarm_type,
                                alarm.get("StateValue"),
                                alarm.get("ActionsEnabled"),
                                timestamp(updated) if updated is not None else None,
                            )
                            report.rows.append(row)
                            if alarm_name is not None:
                                matched.append(row)
                for row in matched:
                    for page in reader.pages(
                        "describe_alarm_history",
                        AlarmName=row.name,
                        AlarmTypes=[row.alarm_type],
                        HistoryItemType="StateUpdate",
                        ScanBy="TimestampDescending",
                        PaginationConfig={"MaxItems": 20},
                    ):
                        for item in page.get("AlarmHistoryItems", []):
                            old, new = _alarm_states(item.get("HistoryData", ""))
                            report.rows.append(
                                AlarmStateChange(
                                    region, row.name, timestamp(item["Timestamp"]), old, new
                                )
                            )
        except ResourceFailure as error:
            report.add_error(error.error)
    return report


def collect_cloudtrail_changes(
    access: AwsAccess,
    regions: list[str],
    hours: int,
    limit: int,
    resource: str | None,
    *,
    now: datetime | None = None,
) -> Report:
    end = now or datetime.now(UTC)
    start = end - timedelta(hours=hours)
    report = Report(access.identity, "cloudtrail_changes", timestamp(end), regions)
    report.observations.append(
        f"Management write events from {timestamp(start)} to {timestamp(end)}. "
        f"At most {limit} events per region before resource filtering."
    )
    for region in regions:
        seen = 0
        try:
            with closing(access.service("cloudtrail", region)) as reader:
                for page in reader.pages(
                    "lookup_events",
                    LookupAttributes=[{"AttributeKey": "ReadOnly", "AttributeValue": "false"}],
                    StartTime=start,
                    EndTime=end,
                    PaginationConfig={"MaxItems": limit + 1, "PageSize": min(50, limit + 1)},
                ):
                    events = page.get("Events", [])
                    for event in events[: limit - seen]:
                        resources = [
                            item["ResourceName"]
                            for item in event.get("Resources", [])
                            if item.get("ResourceName")
                        ]
                        if resource is None or resource in resources:
                            report.rows.append(
                                CloudTrailChange(
                                    region,
                                    event["EventId"],
                                    timestamp(event["EventTime"]),
                                    event.get("EventSource"),
                                    event.get("EventName"),
                                    event.get("Username"),
                                    resources,
                                )
                            )
                    seen += len(events)
                    if seen > limit:
                        report.add_error(
                            ScanError(region, "lookup_events", "EventLimitReached", "limit")
                        )
                        break
        except ResourceFailure as error:
            report.add_error(error.error)
    return report


def _resource_explorer_coverage(reader: ServiceReader, report: Report, view_arn: str) -> None:
    try:
        view = reader.call("get_view", ViewArn=view_arn)["View"]
        scope = view.get("Scope", "unknown")
        tags = any(prop.get("Name") == "tags" for prop in view.get("IncludedProperties", []))
        view_filter = bool(view.get("Filters", {}).get("FilterString"))
        report.observations.append(
            f"View scope: {scope}. View filter configured: {view_filter}. Tag data enabled: {tags}."
        )
    except ResourceFailure as error:
        report.add_error(error.error)
        report.observations.append("Resource Explorer view coverage is unknown.")
    try:
        index = reader.call("get_index")
        state = index.get("State", "unknown")
        regions = ", ".join(sorted({reader.region, *index.get("ReplicatingFrom", [])}))
        report.observations.append(
            f"Index: {index.get('Type', 'unknown')} ({state}). Index regions: {regions}."
        )
        if state != "ACTIVE":
            report.add_error(ScanError(reader.region, "get_index", "IndexNotActive", "coverage"))
    except ResourceFailure as error:
        report.add_error(error.error)
        report.observations.append("Resource Explorer index coverage is unknown.")


def collect_resources(
    access: AwsAccess,
    region: str,
    view_arn: str,
    resource_filter: str | None,
    *,
    summary: bool,
) -> Report:
    report = Report(
        access.identity,
        "resources_summary" if summary else "resources_list",
        timestamp(datetime.now(UTC)),
        [region],
    )
    report.observations.extend(
        [
            f"Resource Explorer view: {view_arn}. Results are restricted to the verified account.",
            "Coverage depends on the view, indexed regions, and supported resource types.",
        ]
    )
    counts: Counter[tuple[str, str]] = Counter()
    seen: set[str] = set()
    unknown_owner = False
    params: dict[str, Any] = {"ViewArn": view_arn, "PaginationConfig": {"PageSize": 100}}
    if resource_filter is not None:
        params["Filters"] = {"FilterString": resource_filter}
    try:
        with closing(access.service("resource-explorer-2", region)) as reader:
            _resource_explorer_coverage(reader, report, view_arn)
            for page in reader.pages("list_resources", **params):
                for resource in page.get("Resources", []):
                    account = resource.get("OwningAccountId")
                    if not account:
                        unknown_owner = True
                    if account != access.identity.account_id or resource["Arn"] in seen:
                        continue
                    arn = resource["Arn"]
                    seen.add(arn)
                    service = resource.get("Service") or "unknown"
                    resource_region = resource.get("Region") or "unknown"
                    if summary:
                        counts[service, resource_region] += 1
                    else:
                        reported_at = resource.get("LastReportedAt")
                        report.rows.append(
                            DiscoveredResource(
                                arn,
                                service,
                                resource.get("ResourceType") or "unknown",
                                resource_region,
                                timestamp(reported_at) if reported_at is not None else None,
                            )
                        )
    except ResourceFailure as error:
        report.add_error(error.error)
    if unknown_owner:
        report.add_error(ScanError(region, "list_resources", "UnknownResourceOwner", "coverage"))
    if summary:
        report.rows.extend(
            ResourceCount(service, resource_region, count)
            for (service, resource_region), count in sorted(counts.items())
        )
    return report


def _completed_snapshots(
    reader: ServiceReader, report: Report, volume_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    latest: dict[str, dict[str, Any]] = {}
    checked: set[str] = set()
    for ids in batched(volume_ids, 100, strict=False):
        batch: dict[str, dict[str, Any]] = {}
        try:
            for page in reader.pages(
                "describe_snapshots",
                OwnerIds=["self"],
                Filters=[
                    {"Name": "volume-id", "Values": list(ids)},
                    {"Name": "status", "Values": ["completed"]},
                ],
            ):
                for snapshot in page.get("Snapshots", []):
                    volume_id = snapshot.get("VolumeId")
                    started = snapshot.get("StartTime")
                    if (
                        volume_id in ids
                        and snapshot.get("State") == "completed"
                        and snapshot.get("SnapshotId")
                        and started is not None
                    ):
                        previous = batch.get(volume_id)
                        if previous is None or started > previous["StartTime"]:
                            batch[volume_id] = snapshot
        except ResourceFailure as error:
            report.add_error(error.error)
        else:
            checked.update(ids)
            latest.update(batch)
    return latest, checked


def collect_ebs_candidates(access: AwsAccess, regions: list[str], owner: str | None) -> Report:
    report = Report(access.identity, "ebs_candidates", timestamp(datetime.now(UTC)), regions)
    report.observations.extend(
        [
            "Available, unattached volumes are candidates for owner review.",
            "Creation time describes volume age. Snapshot checks cover completed, owned "
            "snapshots matching the source volume ID in this region.",
        ]
    )
    filters = [{"Name": "status", "Values": ["available"]}]
    if owner is not None:
        filters.append({"Name": "tag:Owner", "Values": [owner]})
    for region in regions:
        volumes: list[dict[str, Any]] = []
        snapshots: dict[str, dict[str, Any]] = {}
        checked: set[str] = set()
        try:
            with closing(access.service("ec2", region)) as reader:
                for page in reader.pages("describe_volumes", Filters=filters):
                    volumes.extend(
                        volume
                        for volume in page.get("Volumes", [])
                        if volume.get("State") == "available" and not volume.get("Attachments")
                    )
                snapshots, checked = _completed_snapshots(
                    reader, report, [volume["VolumeId"] for volume in volumes]
                )
        except ResourceFailure as error:
            report.add_error(error.error)
        for volume in volumes:
            volume_id = volume["VolumeId"]
            tags = {tag["Key"]: tag["Value"] for tag in volume.get("Tags", [])}
            snapshot = snapshots.get(volume_id)
            created = volume.get("CreateTime")
            if snapshot is not None:
                snapshot_check = "found"
            elif volume_id in checked:
                snapshot_check = "none_found"
            else:
                snapshot_check = "unknown"
            report.rows.append(
                EbsCandidate(
                    region,
                    volume_id,
                    volume.get("Size"),
                    volume.get("VolumeType"),
                    tags.get("Owner"),
                    timestamp(created) if created is not None else None,
                    snapshot_check,
                    snapshot["SnapshotId"] if snapshot is not None else None,
                    timestamp(snapshot["StartTime"]) if snapshot is not None else None,
                )
            )
    return report
