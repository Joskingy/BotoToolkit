"""Explain job/step evidence without exporting free-form AWS or log content."""

from datetime import UTC, datetime

from amplify_ops.aws import AmplifyReader, AwsAccess, ResourceFailure
from amplify_ops.inventory import job_key, timestamp
from amplify_ops.logs import MAX_LOGS, LogReadFailure, inspect_log
from amplify_ops.models import Deployment, Investigation, JobStep, LogReview, ScanError

STEP_NAMES = {"PROVISION", "BUILD", "DEPLOY", "VERIFY", "TEST", "RELEASE"}


def select_failed_job(reader: AmplifyReader, app_id: str, branch: str) -> str | None:
    latest = None
    for job in reader.items("list_jobs", "jobSummaries", app_id=app_id, branch_name=branch):
        if job["status"] == "FAILED" and (latest is None or job_key(job) > job_key(latest)):
            latest = job
    return latest["jobId"] if latest else None


def review_step_log(
    url: str | None,
    report: Investigation,
    step: JobStep,
    inspected: int,
) -> None:
    if not url:
        code = "LogUnavailable"
    elif inspected >= MAX_LOGS:
        code = "LogCountLimit"
    else:
        try:
            step.log = inspect_log(url)
            if step.log.truncated:
                report.add_error(
                    ScanError(
                        report.region,
                        "inspect_log",
                        "LogInspectionLimit",
                        "limit",
                        report.app_id,
                        report.branch_name,
                    )
                )
            return
        except LogReadFailure as error:
            code = str(error)
    step.log = LogReview(state="unavailable")
    report.add_error(
        ScanError(
            report.region,
            "inspect_log",
            code,
            "log_unavailable",
            report.app_id,
            report.branch_name,
        )
    )


def investigate_job(
    access: AwsAccess,
    region: str,
    app_id: str,
    branch: str,
    job_id: str | None,
    inspect_logs: bool = False,
) -> Investigation:
    report = Investigation(
        access.identity,
        region,
        app_id,
        branch,
        "explicit_job" if job_id else "latest_failed",
        timestamp(datetime.now(UTC)),
    )
    reader = None
    try:
        reader = access.amplify(region)
        selected = job_id or select_failed_job(reader, app_id, branch)
        if selected is None:
            report.observations.append("No failed jobs found in the complete branch job history.")
            return report
        raw = reader.get_job(app_id, branch, selected)
        summary = raw["summary"]
        report.job = Deployment(
            summary["jobId"],
            summary["status"],
            timestamp(summary["startTime"]),
            timestamp(summary["endTime"]) if summary.get("endTime") else None,
        )
        inspected = 0
        for raw_step in raw["steps"]:
            name = raw_step["stepName"].upper()
            step = JobStep(
                name if name in STEP_NAMES else "OTHER",
                raw_step["status"],
                timestamp(raw_step["startTime"]) if raw_step.get("startTime") else None,
                timestamp(raw_step["endTime"]) if raw_step.get("endTime") else None,
                bool(raw_step.get("statusReason")),
            )
            report.steps.append(step)
            if inspect_logs and step.status == "FAILED":
                review_step_log(raw_step.get("logUrl"), report, step, inspected)
                inspected += 1
            elif inspect_logs:
                step.log.state = "not_applicable"
        failed = [step.name for step in report.steps if step.status == "FAILED"]
        if failed:
            report.observations.append("Failed steps reported by AWS: " + ", ".join(failed) + ".")
        elif report.job.status == "FAILED":
            report.observations.append(
                "AWS reports a failed job without a failed step in its details."
            )
        else:
            report.observations.append(
                "The selected job's current status is " + report.job.status + "."
            )
        report.observations.append(
            "Step status identifies where execution failed; log signatures are clues, "
            "not a verified root cause. Free-form status reasons and log text are withheld."
        )
    except ResourceFailure as error:
        report.add_error(error.error)
    finally:
        if reader is not None:
            reader.close()
    return report
