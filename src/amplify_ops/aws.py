"""AWS boundary: explicit profile, verified identity, and safe error translation."""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.paginate import Paginator

from amplify_ops.models import Identity, ScanError

SDK_CONFIG = Config(
    retries={"mode": "standard", "total_max_attempts": 3},
    connect_timeout=5,
    read_timeout=20,
    ignore_configured_endpoint_urls=True,
    user_agent_extra="amplify-ops/0.1.0",
)

AUTH_CODES = {
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
    "InvalidSignatureException",
    "SignatureDoesNotMatch",
    "AuthFailure",
    "RequestExpired",
    "TokenRefreshRequired",
}
ACCESS_CODES = {"AccessDenied", "AccessDeniedException", "UnauthorizedException"}


class AuthenticationFailure(Exception):
    """Identity cannot be trusted; no subsequent inventory calls are allowed."""


@dataclass
class ResourceFailure(Exception):
    error: ScanError


def _translate(error: BotoCoreError | ClientError, context: ScanError) -> ResourceFailure:
    """Do not expose service messages, raw responses, or credential-provider errors."""
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "Unknown")
        if code in AUTH_CODES:
            raise AuthenticationFailure(
                f"AWS authentication failed ({code}); scan stopped."
            ) from None
        category = "access_denied" if code in ACCESS_CODES else "service"
    else:
        code = type(error).__name__
        # Credential/provider failures must abort, transport failures can be regional.
        if any(word in code for word in ("Credential", "Token", "SSO", "Login", "Profile")):
            raise AuthenticationFailure(
                f"AWS authentication failed ({code}); scan stopped."
            ) from None
        category = "connection"
    return ResourceFailure(
        ScanError(
            context.region, context.operation, code, category, context.app_id, context.branch_name
        )
    )


class AwsAccess:
    def __init__(self, session: boto3.Session, identity: Identity) -> None:
        self._session = session
        self.identity = identity

    @classmethod
    def connect(cls, profile: str, expected_account: str, region: str) -> AwsAccess:
        try:
            session = boto3.Session(profile_name=profile, region_name=region)
            with closing(session.client("sts", region_name=region, config=SDK_CONFIG)) as sts:
                response = sts.get_caller_identity()
        except (BotoCoreError, ClientError) as error:
            # All STS failures prevent verification, including access and transport errors.
            code = (
                error.response.get("Error", {}).get("Code", "Unknown")
                if isinstance(error, ClientError)
                else type(error).__name__
            )
            raise AuthenticationFailure(
                f"Identity verification failed ({code}); check the selected profile and session."
            ) from None
        account = response.get("Account")
        arn = response.get("Arn")
        if account != expected_account:
            raise AuthenticationFailure(
                f"Account mismatch: expected {expected_account}, received {account}; scan blocked."
            )
        if not arn:
            raise AuthenticationFailure("Identity verification failed: caller ARN is missing.")
        return cls(session, Identity(account, arn))

    def amplify(self, region: str) -> AmplifyReader:
        try:
            client = self._session.client("amplify", region_name=region, config=SDK_CONFIG)
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, ScanError(region, "create_client", "", "")) from None
        return AmplifyReader(client, region)

    def service(self, service: str, region: str, *, write: bool = False) -> ServiceReader:
        config = (
            SDK_CONFIG.merge(Config(retries={"mode": "standard", "total_max_attempts": 1}))
            if write
            else SDK_CONFIG
        )
        try:
            client = self._session.client(service, region_name=region, config=config)
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, ScanError(region, "create_client", "", "")) from None
        return ServiceReader(client, region)


class ServiceReader:
    """Shared SDK boundary for reporting services; writes require an explicit client."""

    def __init__(self, client: Any, region: str) -> None:
        self.client = client
        self.region = region

    def close(self) -> None:
        self.client.close()

    def call(self, operation: str, **params: Any) -> dict[str, Any]:
        try:
            return getattr(self.client, operation)(**params)
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, ScanError(self.region, operation, "", "")) from None

    def pages(self, operation: str, **params: Any) -> Iterator[dict[str, Any]]:
        try:
            if self.client.can_paginate(operation):
                paginator = self.client.get_paginator(operation)
            elif operation == "get_cost_and_usage":
                # CE publishes a token but ships no SDK paginator. Use the SDK's
                # paginator engine with its documented token/result fields.
                paginator = Paginator(
                    self.client.get_cost_and_usage,
                    {
                        "input_token": "NextPageToken",
                        "output_token": "NextPageToken",
                        "result_key": "ResultsByTime",
                    },
                    self.client.meta.service_model.operation_model("GetCostAndUsage"),
                )
            else:
                raise ValueError("Unsupported paginated operation")
            yield from paginator.paginate(**params)
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, ScanError(self.region, operation, "", "")) from None


class AmplifyReader:
    """One client per region; all implemented operations are read-only."""

    def __init__(self, client: Any, region: str) -> None:
        self.client = client
        self.region = region

    def close(self) -> None:
        self.client.close()

    def get_app(self, app_id: str) -> dict[str, Any]:
        context = ScanError(self.region, "get_app", "", "", app_id)
        try:
            return self.client.get_app(appId=app_id)["app"]
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, context) from None

    def get_branch(self, app_id: str, branch_name: str) -> dict[str, Any]:
        context = ScanError(self.region, "get_branch", "", "", app_id, branch_name)
        try:
            return self.client.get_branch(appId=app_id, branchName=branch_name)["branch"]
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, context) from None

    def get_job(self, app_id: str, branch_name: str, job_id: str) -> dict[str, Any]:
        context = ScanError(self.region, "get_job", "", "", app_id, branch_name)
        try:
            return self.client.get_job(appId=app_id, branchName=branch_name, jobId=job_id)["job"]
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, context) from None

    def items(
        self,
        operation: str,
        result_key: str,
        *,
        app_id: str | None = None,
        branch_name: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        params = {}
        if app_id is not None:
            params["appId"] = app_id
        if branch_name is not None:
            params["branchName"] = branch_name
        context = ScanError(self.region, operation, "", "", app_id, branch_name)
        try:
            for page in self.client.get_paginator(operation).paginate(**params):
                yield from page.get(result_key, [])
        except (BotoCoreError, ClientError) as error:
            raise _translate(error, context) from None
