"""Fixed fictional examples; no configuration, filesystem, SDK, or network access."""

from amplify_ops.models import (
    App,
    AppSyncApi,
    AppSyncTableSource,
    Branch,
    CloudFormationResource,
    CloudFormationStack,
    CloudWatchAlarm,
    Deployment,
    DynamoDbTable,
    Ec2Instance,
    Identity,
    Report,
)


def demo_apps() -> list[App]:
    """Return fresh report objects so one browser cannot change another's fixtures."""
    return [
        App(
            region="us-east-1",
            app_id="APP_ID_DEMO_STORE",
            name="Demo storefront",
            repository=None,
            default_domain=None,
            branches_complete=True,
            branches=[
                Branch(
                    "main",
                    "PRODUCTION",
                    Deployment(
                        "demo-101", "SUCCEED", "2026-01-15T10:00:00Z", "2026-01-15T10:04:00Z"
                    ),
                    True,
                ),
                Branch(
                    "dev",
                    "DEVELOPMENT",
                    Deployment(
                        "demo-102", "FAILED", "2026-01-15T10:10:00Z", "2026-01-15T10:12:00Z"
                    ),
                    True,
                ),
                Branch(
                    "feature/cart",
                    "DEVELOPMENT",
                    Deployment("demo-103", "RUNNING", "2026-01-15T10:15:00Z", None),
                    True,
                ),
            ],
        ),
        App(
            region="us-west-2",
            app_id="APP_ID_DEMO_DOCS",
            name="Demo documentation",
            repository=None,
            default_domain=None,
            branches_complete=True,
            branches=[Branch("dev", "DEVELOPMENT", deployments_complete=True)],
        ),
        App(
            region="us-east-1",
            app_id="APP_ID_DEMO_PARTIAL",
            name="Demo partial scan",
            repository=None,
            default_domain=None,
            branches=[Branch("preview", "DEVELOPMENT")],
        ),
        App(
            region="us-west-2",
            app_id="APP_ID_DEMO_EMPTY",
            name="Demo empty app",
            repository=None,
            default_domain=None,
            branches_complete=True,
        ),
    ]


def demo_alarms() -> Report:
    region = "us-east-1"
    return Report(
        Identity("DEMO", ""),
        "cloudwatch_alarms",
        "2026-01-15T10:30:00Z",
        [region],
        rows=[
            CloudWatchAlarm(
                region, "Checkout error rate", "MetricAlarm", "ALARM", True, "2026-01-15T10:23:00Z"
            ),
            CloudWatchAlarm(
                region, "Worker queue depth", "MetricAlarm", "INSUFFICIENT_DATA", False, None
            ),
            CloudWatchAlarm(
                region, "Storefront health", "CompositeAlarm", "OK", True, "2026-01-15T08:30:00Z"
            ),
            CloudWatchAlarm(region, "Batch job heartbeat", "LogAlarm", None, None, None),
        ],
    )


def demo_instances() -> Report:
    region = "us-east-1"
    examples = [
        ("Demo dashboard", "running", "Platform", "ok", "ok"),
        ("Demo checkout API", "running", "Platform", "ok", "impaired"),
        ("Demo worker", "running", "Operations", "impaired", "ok"),
        ("Demo indexer", "running", "Data", "insufficient-data", "ok"),
        ("Demo batch runner", "stopped", "Data", None, None),
    ]
    return Report(
        Identity("DEMO", ""),
        "ec2_inventory",
        "2026-01-15T10:30:00Z",
        [region],
        rows=[
            Ec2Instance(
                region=region,
                instance_id=f"i-{index:017x}",
                name=name,
                state=state,
                instance_type="t3.micro",
                owner=owner,
                environment="demo",
                auto_scaling_group=None,
                instance_status=instance,
                system_status=system,
                volume_ids=[],
            )
            for index, (name, state, owner, instance, system) in enumerate(examples, start=1)
        ],
    )


def demo_stacks(stack_id: str | None) -> Report:
    region = "us-east-1"
    arn = "arn:aws:cloudformation:us-east-1:ACCOUNT_ID:stack"
    app = f"{arn}/Demo-storefront/demo-store"
    backend = f"{arn}/Demo-data/demo-data"
    other = f"{arn}/Demo-monitoring/demo-monitor"
    created_at = "2026-01-15T08:00:00Z"
    if stack_id is None:
        rows = [
            CloudFormationStack("Demo-storefront", app, "UPDATE_COMPLETE", created_at, None),
            CloudFormationStack("Demo-data", backend, "CREATE_COMPLETE", created_at, app),
            CloudFormationStack("Demo-monitoring", other, "CREATE_COMPLETE", created_at, None),
        ]
    elif stack_id == app:
        rows = [
            CloudFormationResource(
                "DataStack", "AWS::CloudFormation::Stack", backend, "CREATE_COMPLETE"
            ),
            CloudFormationResource(
                "Api", "AWS::AppSync::GraphQLApi", "demo-graphql-api", "CREATE_COMPLETE"
            ),
            CloudFormationResource(
                "OrderHandler", "AWS::Lambda::Function", "demo-order-handler", "CREATE_COMPLETE"
            ),
            CloudFormationResource(
                "OrderWorker", "AWS::Lambda::Function", "demo-order-worker", "CREATE_COMPLETE"
            ),
        ]
    elif stack_id == backend:
        rows = [
            CloudFormationResource(
                "Orders", "AWS::DynamoDB::Table", "demo-orders", "CREATE_COMPLETE", created_at
            ),
        ]
    else:
        rows = [
            CloudFormationResource(
                "ErrorAlarm", "AWS::CloudWatch::Alarm", "demo-errors", "CREATE_COMPLETE"
            ),
        ]
    return Report(
        Identity("DEMO", ""),
        "stack_resources" if stack_id else "cloudformation_stacks",
        "2026-01-15T10:30:00Z",
        [region],
        rows=rows,
    )


def demo_tables(name: str | None) -> Report:
    region = "us-east-1"
    rows = [
        DynamoDbTable(
            "demo-orders",
            arn=f"arn:aws:dynamodb:{region}:ACCOUNT_ID:table/demo-orders",
            status="ACTIVE",
            billing_mode="PAY_PER_REQUEST",
            size_bytes=2_000_000,
            item_count=1800,
            deletion_protection=True,
            created_at="2026-01-15T07:55:00Z",
        ),
        DynamoDbTable(
            "demo-sessions",
            arn=f"arn:aws:dynamodb:{region}:ACCOUNT_ID:table/demo-sessions",
            status="UPDATING",
            billing_mode="PROVISIONED",
            size_bytes=0,
            item_count=0,
            deletion_protection=False,
            created_at="2026-01-15T08:10:00Z",
        ),
    ]
    return Report(
        Identity("DEMO", ""),
        "dynamodb_table" if name else "dynamodb_tables",
        "2026-01-15T10:30:00Z",
        [region],
        rows=[
            DynamoDbTable(table.name) if name is None else table
            for table in rows
            if name is None or table.name == name
        ],
    )


def demo_appsync(api_id: str | None) -> Report:
    region = "us-east-1"
    return Report(
        Identity("DEMO", ""),
        "appsync_table_sources" if api_id else "appsync_apis",
        "2026-01-15T10:30:00Z",
        [region],
        rows=[
            AppSyncTableSource(
                "Orders",
                "demo-orders",
                region,
                f"arn:aws:dynamodb:{region}:ACCOUNT_ID:table/demo-orders",
            ),
            AppSyncTableSource("SharedSessions", "demo-sessions", "us-west-2", None),
        ]
        if api_id
        else [AppSyncApi("Demo storefront API", "demostorefront")],
    )
