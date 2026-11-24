"""Read-only AppSync metadata and key expiry reports."""

import re
from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from amplify_ops.aws import AwsAccess, InventoryBudget, InventoryLimitReached, ResourceFailure
from amplify_ops.inventory import timestamp
from amplify_ops.models import (
    ApiKeyExpiry,
    ApiSummary,
    AppSyncApi,
    AppSyncTableSource,
    Report,
    ScanError,
)


def key_expirations(
    access: AwsAccess,
    regions: list[str],
    api_ids: list[str],
    app_id: str | None,
    warn_days: int,
    *,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    report = Report(access.identity, "appsync_key_expiration", timestamp(now), regions)
    report.observations = [
        "Key refs are SHA-256 fingerprints (first 16 hex digits), never API keys or key ARNs.",
        "API-to-app association is unknown unless explicitly supplied by the operator; "
        "supplied mappings are assertions, not AWS-verified backend discovery.",
        "Only GraphQL APIs and their API keys are covered. "
        "No keys are created, rotated, or deleted.",
    ]
    for region in regions:
        reader = None
        try:
            reader = access.service("appsync", region)
            ids = (
                iter(api_ids)
                if api_ids
                else (
                    api["apiId"]
                    for page in reader.pages("list_graphql_apis")
                    for api in page.get("graphqlApis", [])
                )
            )
            for api_id in ids:
                found = 0
                complete = True
                association = "operator_supplied" if app_id else "unknown"
                try:
                    for page in reader.pages("list_api_keys", apiId=api_id):
                        for key in page.get("apiKeys", []):
                            raw_id = key.get("id", "")
                            expires = key.get("expires")
                            expiry = None
                            status = "unknown"
                            if raw_id and expires is not None and not raw_id.startswith("da1-"):
                                try:
                                    expiry = datetime.fromtimestamp(expires, UTC)
                                    status = (
                                        "expired"
                                        if expiry <= now
                                        else (
                                            "expiring"
                                            if expiry <= now + timedelta(days=warn_days)
                                            else "valid"
                                        )
                                    )
                                except ValueError, OverflowError, OSError:
                                    pass
                            if not raw_id or expiry is None:
                                complete = False
                                report.add_error(
                                    ScanError(
                                        region, "list_api_keys", "UnknownKeyMetadata", "metadata"
                                    )
                                )
                            ref = (
                                "sha256:" + sha256(raw_id.encode()).hexdigest()[:16]
                                if raw_id
                                else "unknown"
                            )
                            report.rows.append(
                                ApiKeyExpiry(
                                    region,
                                    api_id,
                                    ref,
                                    timestamp(expiry) if expiry else None,
                                    status,
                                    app_id,
                                    association,
                                )
                            )
                            found += 1
                except ResourceFailure as error:
                    complete = False
                    report.add_error(error.error)
                report.rows.append(ApiSummary(region, api_id, found, complete, app_id, association))
        except ResourceFailure as error:
            report.add_error(error.error)
        finally:
            if reader is not None:
                reader.close()
    return report


def collect_appsync_tables(
    access: AwsAccess, region: str, api_id: str | None, *, budget: InventoryBudget
) -> Report:
    identity = access.identity
    partition = identity.caller_arn.split(":", 2)[1]
    report = Report(
        identity,
        "appsync_table_sources" if api_id else "appsync_apis",
        timestamp(datetime.now(UTC)),
        [region],
    )
    try:
        with closing(access.service("appsync", region, budget=budget)) as reader:
            if api_id is None:
                api_prefix = f"arn:{partition}:appsync:{region}:{identity.account_id}:apis/"
                for page in reader.pages(
                    "list_graphql_apis", apiType="GRAPHQL", owner="CURRENT_ACCOUNT"
                ):
                    for api in page.get("graphqlApis", []):
                        found_id = api.get("apiId", "")
                        expected = api_prefix + found_id
                        if not re.fullmatch(r"[a-z0-9]+", found_id) or api.get("arn") != expected:
                            report.add_error(
                                ScanError(
                                    region, "list_graphql_apis", "ApiIdentityMismatch", "metadata"
                                )
                            )
                            continue
                        report.rows.append(AppSyncApi(api.get("name") or found_id, found_id))
                return report

            role_prefix = f"arn:{partition}:iam::{identity.account_id}:role/"
            for page in reader.pages("list_data_sources", apiId=api_id):
                for source in page.get("dataSources", []):
                    if source.get("type") != "AMAZON_DYNAMODB":
                        continue
                    config = source.get("dynamodbConfig", {})
                    table_region = config.get("awsRegion", "")
                    primary = config.get("tableName")
                    delta = config.get("deltaSyncConfig", {}).get("deltaSyncTableName")
                    if (
                        not re.fullmatch(r"[a-z0-9-]+", table_region)
                        or not primary
                        or not source.get("name")
                    ):
                        report.add_error(
                            ScanError(
                                region, "list_data_sources", "SourceMetadataMissing", "metadata"
                            )
                        )
                        continue
                    # A name resolves in the credentials' account. Caller credentials
                    # or an unverified role don't prove a same-account target.
                    local_role = not config.get("useCallerCredentials", False) and source.get(
                        "serviceRoleArn", ""
                    ).startswith(role_prefix)
                    for name, delta_sync in ((primary, False), (delta, True)):
                        if name is None:
                            continue
                        table_prefix = (
                            f"arn:{partition}:dynamodb:{table_region}:{identity.account_id}:table/"
                        )
                        table_name = name.rsplit("/", 1)[-1] if name.startswith("arn:") else name
                        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", table_name):
                            report.add_error(
                                ScanError(
                                    region, "list_data_sources", "InvalidTableReference", "metadata"
                                )
                            )
                            continue
                        expected_arn = table_prefix + table_name
                        local_target = name == expected_arn or (name == table_name and local_role)
                        report.rows.append(
                            AppSyncTableSource(
                                source["name"],
                                table_name,
                                table_region,
                                expected_arn if local_target else None,
                                delta_sync,
                            )
                        )
    except (InventoryLimitReached, ResourceFailure) as error:
        report.add_error(error.error)
    return report
