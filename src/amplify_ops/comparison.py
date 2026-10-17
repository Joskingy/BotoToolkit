"""Compare values in memory; export only key names, presence, origin, and relations."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from amplify_ops.aws import AwsAccess, ResourceFailure
from amplify_ops.inventory import timestamp
from amplify_ops.models import Comparison, ConfigEntry

# Runtime/deployment counters, timestamps, URLs, descriptions, and tags are not config.
BRANCH_FIELDS = (
    "stage",
    "framework",
    "enableAutoBuild",
    "enableNotification",
    "enableBasicAuth",
    "basicAuthCredentials",
    "enablePerformanceMode",
    "enableSkewProtection",
    "ttl",
    "buildSpec",
    "customDomains",
    "enablePullRequestPreview",
    "pullRequestEnvironmentName",
    "backendEnvironmentArn",
    "backend",
    "computeRoleArn",
)
APP_FIELDS = (
    "platform",
    "iamServiceRoleArn",
    "computeRoleArn",
    "buildSpec",
    "customRules",
    "customHeaders",
    "enableBranchAutoBuild",
    "enableBranchAutoDeletion",
    "enableBasicAuth",
    "basicAuthCredentials",
    "enableAutoBranchCreation",
    "autoBranchCreationPatterns",
    "autoBranchCreationConfig",
    "cacheConfig",
    "jobConfig",
)
ABSENT = object()
UNAVAILABLE = object()


def read_config(read: Callable[[], dict[str, Any]], report: Comparison) -> dict[str, Any] | None:
    try:
        return read()
    except ResourceFailure as error:
        report.add_error(error.error)
        return None


def field_value(config: dict[str, Any] | None, key: str, origin: str) -> tuple[Any, str]:
    if config is None:
        return UNAVAILABLE, "unknown"
    if key not in config:
        return ABSENT, "absent"
    return config[key], origin


def environment_value(
    app: dict[str, Any] | None,
    branch: dict[str, Any] | None,
    key: str,
) -> tuple[Any, str]:
    if branch is None:
        # Even a known app value may be overridden in the unread branch.
        return UNAVAILABLE, "unknown"
    overrides = branch.get("environmentVariables", {})
    if key in overrides:
        return overrides[key], "branch"
    if app is None:
        return UNAVAILABLE, "unknown"
    return field_value(app.get("environmentVariables", {}), key, "app")


def entry(
    section: str,
    key: str,
    source: tuple[Any, str],
    target: tuple[Any, str],
) -> ConfigEntry:
    left, left_origin = source
    right, right_origin = target

    def state(value: Any) -> str:
        if value is UNAVAILABLE:
            return "unavailable"
        return "absent" if value is ABSENT else "present_redacted"

    if left is UNAVAILABLE or right is UNAVAILABLE:
        result = "unavailable"
        origin_differs = None
    else:
        origin_differs = left_origin != right_origin
        if left is ABSENT and right is ABSENT:
            result = "absent_both"
        elif left is ABSENT:
            result = "missing_source"
        elif right is ABSENT:
            result = "missing_target"
        elif section == "shared_app":
            result = "shared"
        else:
            result = "equal" if left == right else "different"
    return ConfigEntry(
        section,
        key,
        state(left),
        state(right),
        left_origin,
        right_origin,
        result,
        origin_differs,
    )


def compare_configuration(
    access: AwsAccess,
    region: str,
    app_id: str,
    source: str,
    target: str,
) -> Comparison:
    report = Comparison(
        access.identity, region, app_id, source, target, timestamp(datetime.now(UTC))
    )
    reader = None
    try:
        reader = access.amplify(region)
        app = read_config(lambda: reader.get_app(app_id), report)
        left = read_config(lambda: reader.get_branch(app_id, source), report)
        right = read_config(lambda: reader.get_branch(app_id, target), report)
        keys = set()
        for config in (app, left, right):
            if config is not None:
                keys.update(config.get("environmentVariables", {}))
        for key in sorted(keys):
            report.entries.append(
                entry(
                    "environment",
                    key,
                    environment_value(app, left, key),
                    environment_value(app, right, key),
                )
            )
        for key in BRANCH_FIELDS:
            report.entries.append(
                entry(
                    "branch",
                    key,
                    field_value(left, key, "branch"),
                    field_value(right, key, "branch"),
                )
            )
        for key in APP_FIELDS:
            value = field_value(app, key, "app")
            report.entries.append(entry("shared_app", key, value, value))
    except ResourceFailure as error:
        report.add_error(error.error)
    finally:
        if reader is not None:
            reader.close()
    report.differences_found = sum(
        item.result in {"different", "missing_source", "missing_target"}
        or item.origin_differs is True
        for item in report.entries
    )
    report.has_differences = (
        True if report.differences_found else (False if report.complete else None)
    )
    report.observations = [
        "All configuration values are withheld; no value hashes or lengths are exported.",
        "Environment keys use app defaults with branch overrides. Equal values with different "
        "origins count as a configuration difference.",
        "Shared app fields are context for both branches, not independently compared settings. "
        "Branch settings are compared as stored; basic-auth and build-spec inheritance "
        "are not inferred.",
        "Scope is the declared AWS field allowlist. Repository amplify.yml, build scripts, backend "
        "secrets, and automatically injected runtime variables are not inspected.",
    ]
    if not report.complete:
        report.observations.append(
            "Unread configuration is unknown, not absent. Environment keys on unread resources "
            "may be missing from this partial report. Known differences can still be reported."
        )
    return report
