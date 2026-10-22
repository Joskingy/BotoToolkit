"""Cost Explorer account/service totals and explicitly tagged estimates."""

from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, InvalidOperation, localcontext

from amplify_ops.aws import AwsAccess, ResourceFailure
from amplify_ops.inventory import timestamp
from amplify_ops.models import CostRow, Report, ScanError


def add_cost(left: Decimal, right: Decimal) -> Decimal:
    """Preserve all reported places instead of rounding at the ambient precision."""
    fractional = min(left.as_tuple().exponent, right.as_tuple().exponent, 0)
    integral = max(left.adjusted() + 1, right.adjusted() + 1, 1)
    with localcontext() as context:
        # Reserve one extra integral digit for a carry, including signed amounts.
        context.prec = integral - fractional + 1
        return left + right


def cost_report(
    access: AwsAccess,
    start: date,
    end: date,
    tag_key: str | None,
    tag_value: str | None,
) -> Report:
    # Read the clock before CE calls; dates are explicit, and end is exclusive.
    now = datetime.now(UTC)
    if not start < end or end > now.date():
        raise ValueError("Use start < end and an end date no later than today (UTC).")
    report = Report(access.identity, "cost_attribution", timestamp(now), ["us-east-1"])
    report.observations = [
        f"Period: {start.isoformat()} to {end.isoformat()} (exclusive); "
        "UnblendedCost, monthly buckets.",
        "Scope: verified linked account, all billing regions, grouped by service; "
        "CE endpoint us-east-1. "
        "Credits and refunds are excluded; this is not an invoice total.",
        "Tag-attributed costs are estimates, not directly measured per-app resource costs. "
        "No direct-resource cost allocation is implemented.",
        "Outside-tag-scope costs combine unrelated, shared, and untagged costs; those components "
        "cannot be separated by this query. No proportional allocations are invented.",
        "Activated cost-allocation tags may lag or lack historical coverage. Zero tagged cost "
        "does not prove zero app cost. Backend resources may have different/missing tags. "
        "AWS estimated flags and reporting lag apply. CE reads may incur query charges.",
    ]
    base_filter = {
        "And": [
            {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [access.identity.account_id]}},
            {"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}},
        ]
    }
    params = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    reader = None
    totals: dict[tuple[str, str], Decimal] = {}
    tagged: dict[tuple[str, str], Decimal] = {}
    estimated: set[tuple[str, str]] = set()
    baseline_complete = False
    tagged_complete = False
    try:
        reader = access.service("ce", "us-east-1")
        for kind, filters, amounts in [
            ("account", base_filter, totals),
            *(
                [
                    (
                        "tagged",
                        {"And": [base_filter, {"Tags": {"Key": tag_key, "Values": [tag_value]}}]},
                        tagged,
                    )
                ]
                if tag_key
                else []
            ),
        ]:
            try:
                for page in reader.pages("get_cost_and_usage", **params, Filter=filters):
                    for period in page.get("ResultsByTime", []):
                        for group in period.get("Groups", []):
                            metric = group["Metrics"]["UnblendedCost"]
                            key = group["Keys"][0], metric["Unit"]
                            amount = Decimal(metric["Amount"])
                            if not amount.is_finite():
                                raise InvalidOperation
                            amounts[key] = add_cost(amounts.get(key, Decimal(0)), amount)
                            if period.get("Estimated", False):
                                estimated.add(key)
                if kind == "account":
                    baseline_complete = True
                else:
                    tagged_complete = True
            except ResourceFailure as error:
                report.add_error(error.error)
            except DecimalException:
                report.add_error(
                    ScanError("us-east-1", "get_cost_and_usage", "InvalidCostMetadata", "metadata")
                )
    except ResourceFailure as error:
        report.add_error(error.error)
    finally:
        if reader is not None:
            reader.close()
    for key in sorted(totals.keys() | tagged.keys()):
        total = totals.get(key, Decimal(0))
        attributed = tagged.get(key, Decimal(0)) if tagged_complete else None
        remainder = (
            add_cost(total, attributed.copy_negate())
            if attributed is not None and baseline_complete
            else None
        )
        report.rows.append(
            CostRow(
                key[0],
                key[1],
                str(total) if baseline_complete else None,
                str(attributed) if attributed is not None else None,
                str(remainder) if remainder is not None else None,
                key in estimated,
                start.isoformat(),
                end.isoformat(),
            )
        )
    if tag_key:
        report.observations.append(
            "An explicit operator-selected tag filter was applied; its value is withheld."
        )
    else:
        report.observations.append(
            "No tag filter selected: account totals are unattributed to any app."
        )
    return report
