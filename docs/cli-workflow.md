# CLI workflow

These diagrams describe the AWS operations in `bototoolkit` and its compatible
`amplify-ops` command. Both entry points run the same workflow.
AWS operations require an explicit profile, expected account, and region. Local
diagnostics and command help are outside the workflow shown here.
Select your local AWS profile and obtain the account and region from private
settings or the operator.

## Command overview

```mermaid
flowchart TD
    A["Run amplify-ops with profile, expected account, region, and command"] --> B["Validate global and command-specific inputs"]
    B --> C["Create explicit profile session and call STS GetCallerIdentity"]
    C --> D{"Account matches and identity is valid?"}
    D -- "No" --> X["Stop: no resource collection or deployment"]
    D -- "Yes" --> E{"Selected command"}
    E -->|identity| I["Display verified identity"]
    E -->|"inventory, investigate, compare,<br/>api-keys, costs, stale"| R["Read data and prepare a report"]
    R --> O["Display table or JSON;<br/>optionally write a new JSON file"]
    E -->|deploy-plan| P["Read-only preflight for a completed job"]
    P --> F["Write a retry plan; expires after 15 minutes"]
    F --> H["Operator reviews plan and target"]
    H --> N["Run deploy as a separate invocation"]
    E -->|deploy| W["Run the controlled retry workflow below"]
```

`investigate` reads bounded logs only when `--inspect-logs` is specified. `stale`
also gathers GitHub evidence; missing evidence can make a report partial. For
`deploy`, plan loading and confirmation checks happen before identity verification.
The CLI requires an explicit profile but does not restrict its name.
Verification details and diagnostics go
to stderr; JSON report output goes to stdout. The `identity` command also prints
identity details to stdout. The optional output file must be new. A partial report
exits with code 3; invalid arguments exit with code 2, while authentication,
blocked deployment, and output-file failures exit with code 1.

## Controlled retry deployment

```mermaid
flowchart TD
    A["Operator reviews the plan and invokes deploy"] --> B["Load plan; check integrity, expiry, account and region"]
    B --> C["Confirm exact plan ID and, for production, branch name"]
    C --> D["Verify AWS identity against the expected account"]
    D --> E["Fresh preflight: completed job, no active job,<br/>unchanged target and source commit, unexpired plan"]
    E --> F["Persist exclusive local audit claim"]
    F --> G["Submit one StartJob RETRY request"]
    G --> H{"Submission outcome"}
    H -->|"Submitted and recorded"| I["Review receipt; investigate job status"]
    H -->|"Uncertain or final audit write fails"| J["Inspect AWS job history before further action"]
    K["Any failed check before submission"] --> L["Stop without submitting a job"]
    B -.-> K
    C -.-> K
    D -.-> K
    E -.-> K
    F -.-> K
```

The plan is a read-only proposal; reviewing it is an operator responsibility.
`deploy` is the sole AWS write path, requires separate `StartJob` permission, and
supports only retrying a completed job. It does not automatically retry or roll
back. Once the audit claim is made, an uncertain submission consumes that local
plan. The local claim protects against reuse in that audit directory; it is not
distributed idempotency. See [deployment details](remaining-commands.md) and the
[README](../README.md) for operating instructions.
