"""The report schema is an explicit allowlist; never store raw AWS objects here."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    account_id: str
    caller_arn: str


@dataclass(frozen=True)
class Deployment:
    job_id: str
    status: str
    start_time: str
    end_time: str | None


@dataclass
class Branch:
    name: str
    stage: str | None
    latest_deployment: Deployment | None = None
    deployments_complete: bool = False


@dataclass
class App:
    region: str
    app_id: str
    name: str
    repository: str | None
    default_domain: str | None
    branches: list[Branch] = field(default_factory=list)
    branches_complete: bool = False


@dataclass(frozen=True)
class ScanError:
    region: str
    operation: str
    code: str
    category: str
    app_id: str | None = None
    branch_name: str | None = None


@dataclass
class Inventory:
    identity: Identity
    regions: list[str]
    generated_at: str
    schema_version: int = 1
    scope: str = "Amplify Hosting apps, branches, and deployment job summaries"
    complete: bool = True
    apps: list[App] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)

    def add_error(self, error: ScanError) -> None:
        self.complete = False
        self.errors.append(error)


@dataclass(frozen=True)
class LogEvidence:
    line: int
    category: str
    suggestion: str


@dataclass
class LogReview:
    state: str = "not_requested"
    bytes_read: int = 0
    lines_scanned: int = 0
    truncated: bool = False
    findings: list[LogEvidence] = field(default_factory=list)


@dataclass
class JobStep:
    name: str
    status: str
    start_time: str | None
    end_time: str | None
    status_reason_available: bool
    log: LogReview = field(default_factory=LogReview)


@dataclass
class Investigation:
    identity: Identity
    region: str
    app_id: str
    branch_name: str
    selection: str
    generated_at: str
    schema_version: int = 1
    report_type: str = "deployment_investigation"
    complete: bool = True
    job: Deployment | None = None
    steps: list[JobStep] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)

    def add_error(self, error: ScanError) -> None:
        self.complete = False
        self.errors.append(error)


@dataclass(frozen=True)
class ConfigEntry:
    section: str
    key: str
    source_state: str
    target_state: str
    source_origin: str
    target_origin: str
    result: str
    origin_differs: bool | None


@dataclass
class Comparison:
    identity: Identity
    region: str
    app_id: str
    source_branch: str
    target_branch: str
    generated_at: str
    schema_version: int = 1
    report_type: str = "configuration_comparison"
    complete: bool = True
    differences_found: int = 0
    has_differences: bool | None = None
    entries: list[ConfigEntry] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)

    def add_error(self, error: ScanError) -> None:
        self.complete = False
        self.errors.append(error)


type ReportRow = (
    ApiKeyExpiry
    | ApiSummary
    | CostRow
    | StaleEnvironment
    | DeploymentPlan
    | DeploymentReceipt
    | Ec2Instance
    | CloudWatchAlarm
    | AlarmStateChange
    | CloudTrailChange
    | DiscoveredResource
    | ResourceCount
    | EbsCandidate
)


@dataclass
class Report:
    """Common envelope for the remaining reports; rows are typed allowlist models."""

    identity: Identity
    report_type: str
    generated_at: str
    regions: list[str]
    schema_version: int = 1
    complete: bool = True
    rows: list[ReportRow] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)

    def add_error(self, error: ScanError) -> None:
        self.complete = False
        self.errors.append(error)


@dataclass(frozen=True)
class Ec2Instance:
    region: str
    instance_id: str
    name: str | None
    state: str | None
    instance_type: str | None
    owner: str | None
    environment: str | None
    auto_scaling_group: str | None
    instance_status: str | None
    system_status: str | None
    volume_ids: list[str]


@dataclass(frozen=True)
class CloudWatchAlarm:
    region: str
    name: str
    alarm_type: str
    state: str | None
    actions_enabled: bool | None
    state_updated_at: str | None


@dataclass(frozen=True)
class AlarmStateChange:
    region: str
    name: str
    timestamp: str
    previous_state: str | None
    new_state: str | None


@dataclass(frozen=True)
class CloudTrailChange:
    region: str
    event_id: str
    timestamp: str
    event_source: str | None
    event_name: str | None
    username: str | None
    resources: list[str]


@dataclass(frozen=True)
class DiscoveredResource:
    arn: str
    service: str
    resource_type: str
    region: str
    last_reported_at: str | None


@dataclass(frozen=True)
class ResourceCount:
    service: str
    region: str
    count: int


@dataclass(frozen=True)
class EbsCandidate:
    region: str
    volume_id: str
    size_gib: int | None
    volume_type: str | None
    owner: str | None
    created_at: str | None
    snapshot_check: str
    snapshot_id: str | None
    snapshot_started_at: str | None


@dataclass(frozen=True)
class ApiKeyExpiry:
    region: str
    api_id: str
    key_ref: str
    expires_at: str | None
    status: str
    app_id: str | None
    association_evidence: str


@dataclass(frozen=True)
class ApiSummary:
    region: str
    api_id: str
    keys_found: int
    keys_complete: bool
    app_id: str | None
    association_evidence: str


@dataclass(frozen=True)
class CostRow:
    service: str
    currency: str
    account_cost: str | None
    tag_attributed_estimate: str | None
    outside_tag_scope: str | None
    estimated_by_aws: bool
    start: str
    end_exclusive: str


@dataclass(frozen=True)
class StaleEnvironment:
    branch: str
    classification: str
    confidence: str
    last_activity_at: str | None
    github_branch: str
    open_pull_requests: int | None
    github_checked_at: str | None
    backend_association_present: bool
    evidence: list[str]


@dataclass(frozen=True)
class DeploymentPlan:
    account_id: str
    region: str
    app_id: str
    branch: str
    stage: str | None
    action: str
    source_job_id: str
    source_commit_id: str
    branch_updated_at: str
    production: bool
    created_at: str
    expires_at: str
    plan_id: str


@dataclass(frozen=True)
class DeploymentReceipt:
    plan_id: str
    app_id: str
    branch: str
    job_id: str
    status: str
    outcome: str


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    next_step: str


@dataclass
class DoctorReport:
    report_type: str = "doctor"
    schema_version: int = 1
    complete: bool = True
    checks: list[DoctorCheck] = field(default_factory=list)
