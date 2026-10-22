"""Explicit retry deployment plans, fresh preflight, and local at-most-once claims."""

import json
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from amplify_ops.aws import AwsAccess, ResourceFailure
from amplify_ops.inventory import timestamp
from amplify_ops.models import DeploymentPlan, DeploymentReceipt, Report
from amplify_ops.stale import ACTIVE


class DeploymentBlocked(Exception):
    """A safe, operator-facing refusal before submitting a deployment."""


def plan_digest(data: dict) -> str:
    content = {key: value for key, value in data.items() if key != "plan_id"}
    return sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_plan(plan: DeploymentPlan, now: datetime) -> None:
    try:
        data = asdict(plan)
        if any(
            not isinstance(value, str) for key, value in data.items() if key != "production"
        ) or not isinstance(plan.production, bool):
            raise ValueError
        patterns = {
            "account_id": r"[0-9]{12}",
            "region": r"[a-z]{2}(?:-[a-z]+)+-[0-9]+",
            "app_id": r"d[a-z0-9]{1,19}",
            "source_job_id": r"[0-9]{1,255}",
            "plan_id": r"[0-9a-f]{64}",
        }
        if (
            any(not re.fullmatch(pattern, data[key]) for key, pattern in patterns.items())
            or plan.stage
            not in {"PRODUCTION", "DEVELOPMENT", "BETA", "EXPERIMENTAL", "PULL_REQUEST"}
            or not plan.branch.strip()
            or len(plan.branch) > 255
            or any(ord(char) < 32 or ord(char) == 127 or char in "<>" for char in plan.branch)
            or not plan.source_commit_id.strip()
            or len(plan.source_commit_id) > 255
        ):
            raise ValueError
        expiry = datetime.fromisoformat(plan.expires_at)
        created = datetime.fromisoformat(plan.created_at)
        updated = datetime.fromisoformat(plan.branch_updated_at)
        if (
            any(moment.utcoffset() is None for moment in (created, expiry, updated))
            or plan.plan_id != plan_digest(data)
            or plan.action != "RETRY"
            or not created <= now < expiry
            or expiry - created > timedelta(minutes=15)
        ):
            raise ValueError
    except ValueError, TypeError:
        raise DeploymentBlocked(
            "Plan is invalid, modified, or expired; create a fresh plan."
        ) from None


def create_plan(
    access: AwsAccess,
    region: str,
    app_id: str,
    branch: str,
    job_id: str,
    *,
    now: datetime | None = None,
) -> DeploymentPlan:
    now = now or datetime.now(UTC)
    reader = access.amplify(region)
    try:
        app = reader.get_app(app_id)
        config = reader.get_branch(app_id, branch)
        job = reader.get_job(app_id, branch, job_id)["summary"]
        if job["status"] not in {"FAILED", "SUCCEED", "CANCELLED"}:
            raise DeploymentBlocked("Only completed jobs can be planned for retry.")
        for existing in reader.items(
            "list_jobs", "jobSummaries", app_id=app_id, branch_name=branch
        ):
            if existing["status"] in ACTIVE:
                raise DeploymentBlocked(
                    "The branch has an active job; wait and create a fresh plan."
                )
        if (
            not config.get("updateTime")
            or not job.get("commitId")
            or config.get("stage")
            not in {"PRODUCTION", "DEVELOPMENT", "BETA", "EXPERIMENTAL", "PULL_REQUEST"}
        ):
            raise DeploymentBlocked("Required branch/commit metadata is unavailable.")
        production = (
            branch == "main"
            or config.get("stage") == "PRODUCTION"
            or (app.get("productionBranch", {}).get("branchName") == branch)
        )
        plan = DeploymentPlan(
            access.identity.account_id,
            region,
            app_id,
            branch,
            config.get("stage"),
            "RETRY",
            job_id,
            job["commitId"],
            timestamp(config["updateTime"]),
            production,
            timestamp(now),
            timestamp(now + timedelta(minutes=15)),
            "",
        )
        return DeploymentPlan(**{**asdict(plan), "plan_id": plan_digest(asdict(plan))})
    finally:
        reader.close()


def load_plan(path: Path, *, now: datetime | None = None) -> DeploymentPlan:
    try:
        if path.stat().st_size > 65536:
            raise ValueError
        content = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(content, dict)
            or content["report_type"] != "deployment_plan"
            or type(content["schema_version"]) is not int
            or content["schema_version"] != 1
            or content["complete"] is not True
            or not isinstance(content["rows"], list)
            or len(content["rows"]) != 1
            or not isinstance(content["rows"][0], dict)
        ):
            raise ValueError
        plan = DeploymentPlan(**content["rows"][0])
        validate_plan(plan, now or datetime.now(UTC))
        return plan
    except OSError, ValueError, TypeError, KeyError, RecursionError:
        raise DeploymentBlocked(
            "Plan is invalid, modified, unreadable, or expired; create a fresh plan."
        ) from None


def audit_event(handle, event: str, plan: DeploymentPlan, access: AwsAccess, **extra) -> None:
    handle.write(
        json.dumps(
            {
                "at": timestamp(datetime.now(UTC)),
                "event": event,
                "plan_id": plan.plan_id,
                "account_id": access.identity.account_id,
                "caller_arn": access.identity.caller_arn,
                "region": plan.region,
                "app_id": plan.app_id,
                "branch": plan.branch,
                "source_job_id": plan.source_job_id,
                **extra,
            }
        )
        + "\n"
    )
    handle.flush()
    os.fsync(handle.fileno())


def execute_plan(
    access: AwsAccess,
    plan: DeploymentPlan,
    confirmation: str,
    production_confirmation: str | None,
    audit_dir: Path,
) -> Report:
    validate_plan(plan, datetime.now(UTC))
    if confirmation != plan.plan_id:
        raise DeploymentBlocked("--confirm-plan must match the reviewed plan ID.")
    if access.identity.account_id != plan.account_id:
        raise DeploymentBlocked("The plan account differs from the verified account.")
    if plan.production and production_confirmation != plan.branch:
        raise DeploymentBlocked(
            "Production retry requires --confirm-production with the branch name."
        )
    fresh = create_plan(access, plan.region, plan.app_id, plan.branch, plan.source_job_id)
    snapshot = (
        "account_id",
        "region",
        "app_id",
        "branch",
        "stage",
        "action",
        "source_job_id",
        "source_commit_id",
        "branch_updated_at",
        "production",
    )
    if any(getattr(plan, key) != getattr(fresh, key) for key in snapshot):
        raise DeploymentBlocked("Target configuration/commit changed; review a fresh plan.")
    if datetime.now(UTC) >= datetime.fromisoformat(plan.expires_at):
        raise DeploymentBlocked("Plan expired during preflight; create a fresh plan.")
    report = Report(
        access.identity, "deployment_submission", timestamp(datetime.now(UTC)), [plan.region]
    )
    # Claim before the only write. Even uncertain failures consume the local plan.
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        handle = (audit_dir / (plan.plan_id + ".jsonl")).open("x", encoding="utf-8")
    except OSError:
        raise DeploymentBlocked(
            "Audit claim unavailable or plan already consumed; no write was attempted."
        ) from None
    with handle:
        try:
            audit_event(handle, "submitting", plan, access)
        except OSError:
            raise DeploymentBlocked(
                "Cannot persist audit intent; no write was attempted."
            ) from None
        writer = None
        try:
            writer = access.service("amplify", plan.region, write=True)
            result = writer.call(
                "start_job",
                appId=plan.app_id,
                branchName=plan.branch,
                jobId=plan.source_job_id,
                jobType="RETRY",
            )["jobSummary"]
            report.rows.append(
                DeploymentReceipt(
                    plan.plan_id,
                    plan.app_id,
                    plan.branch,
                    result["jobId"],
                    result["status"],
                    "submitted",
                )
            )
            audit_event(
                handle, "submitted", plan, access, job_id=result["jobId"], status=result["status"]
            )
        except ResourceFailure as error:
            report.add_error(error.error)
            report.observations.append(
                "Submission outcome may be unknown. Do not retry this plan; "
                "inspect AWS job history."
            )
            try:
                audit_event(handle, "failed_or_unknown", plan, access, code=error.error.code)
            except OSError:
                report.observations.append(
                    "Could not persist the final audit event; intent claim remains."
                )
        except OSError:
            report.complete = False
            report.observations.append(
                "AWS may have accepted the job but final audit persistence failed. "
                "Inspect job history."
            )
        finally:
            if writer is not None:
                writer.close()
    report.observations.append(
        "No automatic rollback or retry. A retry re-executes an existing job and may use current "
        "configuration/backend state. Check job status with investigate. Local claims are not "
        "a distributed idempotency or tamper-proof audit service."
    )
    return report
