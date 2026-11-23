"""Fixed fictional examples; no configuration, filesystem, SDK, or network access."""

from amplify_ops.models import App, Branch, CloudWatchAlarm, Deployment, Identity, Report


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
