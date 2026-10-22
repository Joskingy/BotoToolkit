"""Conservative stale Hosting branch candidates; no resource cleanup commands."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from amplify_ops.aws import AwsAccess, ResourceFailure
from amplify_ops.github import GitHubReadFailure, repository_evidence
from amplify_ops.inventory import timestamp
from amplify_ops.models import Report, ScanError, StaleEnvironment

ACTIVE = {"CREATED", "PENDING", "PROVISIONING", "RUNNING", "CANCELLING"}


def stale_environments(
    access: AwsAccess,
    region: str,
    app_id: str,
    repository: str,
    older_than: int,
    *,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    report = Report(access.identity, "stale_environments", timestamp(now), [region])
    report.observations = [
        "Scope: Amplify Hosting branch/job metadata plus mapped GitHub repository evidence. "
        "Backend associations are noted; individual backend resources are not inventoried "
        "or judged unused.",
        "main, dev, AWS PRODUCTION stages, and the app's configured production branch "
        "are protected. Only old feature/* branches "
        "absent from a completely read GitHub branch list, without open same-repository PRs "
        "or active AWS jobs, "
        "are medium-confidence review candidates. Nothing is deleted.",
        "GitHub missing/denied evidence is unknown, never proof of deletion. Observations are not "
        "atomic snapshots and branch names can be reused.",
    ]
    reader = None
    try:
        reader = access.amplify(region)
        app = reader.get_app(app_id)
        url = urlsplit(app.get("repository", ""))
        mapped = url.path.strip("/").removesuffix(".git")
        if url.hostname != "github.com" or mapped.casefold() != repository.casefold():
            report.add_error(
                ScanError(region, "repository_mapping", "RepositoryMismatch", "mapping", app_id)
            )
            return report
        github = None
        checked = None
        try:
            github = repository_evidence(repository)
            checked = timestamp(datetime.now(UTC))
        except GitHubReadFailure as error:
            report.add_error(
                ScanError(region, "github_evidence", str(error), "github_unavailable", app_id)
            )
            report.observations.append(
                "GitHub evidence is incomplete. See docs/security.md for the reported "
                "GitHub error code; check local gh authentication and repository read access. "
                "Rate limits require a later rerun; this command does not retry them."
            )
        for raw in reader.items("list_branches", "branches", app_id=app_id):
            branch = raw["branchName"]
            evidence = []
            times = [
                raw[key].astimezone(UTC) for key in ("createTime", "updateTime") if raw.get(key)
            ]
            active = False
            jobs_complete = True
            try:
                for job in reader.items(
                    "list_jobs", "jobSummaries", app_id=app_id, branch_name=branch
                ):
                    active |= job["status"] in ACTIVE
                    times.extend(
                        job[key].astimezone(UTC) for key in ("startTime", "endTime") if job.get(key)
                    )
            except ResourceFailure as error:
                jobs_complete = False
                report.add_error(error.error)
            last = max(times) if times else None
            exists = branch in github.branches if github is not None else None
            prs = github.open_pr_heads.count(branch) if github is not None else None
            protected = (
                branch in {"main", "dev"}
                or raw.get("stage") == "PRODUCTION"
                or app.get("productionBranch", {}).get("branchName") == branch
            )
            old = last is not None and last <= now - timedelta(days=older_than)
            if protected:
                classification, confidence = "protected", "high"
                evidence.append(
                    "Protected branch name, production stage, or app production mapping."
                )
            elif active or (prs is not None and prs > 0):
                classification, confidence = "active", "high"
                evidence.append(
                    "An active deployment job or open same-repository pull request exists."
                )
            elif not jobs_complete or github is None or last is None:
                classification, confidence = "unknown", "unknown"
            elif old and not exists and branch.startswith("feature/"):
                classification, confidence = "review_candidate", "medium"
                evidence.append(
                    "Older than the threshold, branch absent on GitHub, "
                    "no open PRs, no active jobs."
                )
            elif old:
                classification, confidence = "old_but_unproven", "low"
                evidence.append(
                    "Old activity alone does not establish that an environment is unused."
                )
            else:
                classification, confidence = "recent", "high"
            backend = bool(
                raw.get("backendEnvironmentArn")
                or raw.get("backend")
                or raw.get("associatedResources")
            )
            if backend:
                evidence.append(
                    "AWS backend/resource association observed; resource usage is not assessed."
                )
            report.rows.append(
                StaleEnvironment(
                    branch,
                    classification,
                    confidence,
                    timestamp(last) if last else None,
                    "present" if exists else ("absent" if exists is False else "unknown"),
                    prs,
                    checked,
                    backend,
                    evidence,
                )
            )
    except ResourceFailure as error:
        report.add_error(error.error)
    finally:
        if reader is not None:
            reader.close()
    return report
