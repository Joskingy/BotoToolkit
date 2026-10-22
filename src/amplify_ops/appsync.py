"""Read-only AppSync key expiry; raw API-key IDs are credentials, not report IDs."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from amplify_ops.aws import AwsAccess, ResourceFailure
from amplify_ops.inventory import timestamp
from amplify_ops.models import ApiKeyExpiry, ApiSummary, Report, ScanError


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
