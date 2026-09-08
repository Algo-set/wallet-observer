"""Balance floors and logical recommendations; no execution capability."""

from decimal import Decimal

from ._validation import ObserverError, calculate, integer, unique
from .observer import build_snapshot
from .types import (
    AnalysisReport,
    Finding,
    MovementRecommendation,
    PortfolioPolicy,
    PortfolioSnapshot,
)


def analyze(
    snapshot: PortfolioSnapshot,
    policy: PortfolioPolicy,
    analyzed_at_ms: int,
) -> AnalysisReport:
    if snapshot.schema_version != 1 or policy.schema_version != 1:
        raise ObserverError("schema_version")
    integer(analyzed_at_ms)
    integer(policy.maximum_snapshot_age_ms, 1)
    # Validate persisted inputs before using their balances for policy analysis.
    rebuilt = build_snapshot(snapshot.observed_at_ms, list(snapshot.balances))
    if (
        rebuilt.wallet_nav != snapshot.wallet_nav
        or rebuilt.total_valued_nav_usd != snapshot.total_valued_nav_usd
    ):
        raise ObserverError("inconsistent_snapshot_nav")
    age = max(0, analyzed_at_ms - snapshot.observed_at_ms)
    findings = []
    if age > policy.maximum_snapshot_age_ms:
        findings.append(
            Finding(
                "critical",
                "stale_snapshot",
                None,
                None,
                f"snapshot age {age} ms exceeds {policy.maximum_snapshot_age_ms} ms",
            )
        )
    holdings = {(b.wallet_id, b.asset_id): b.quantity for b in snapshot.balances}
    minimums = {}
    for requirement in policy.minimum_balances:
        unique([requirement.wallet_id])
        unique([requirement.asset_id])
        key = (requirement.wallet_id, requirement.asset_id)
        if key in minimums:
            raise ObserverError("duplicate_minimum")
        minimums[key] = requirement.minimum_quantity
        observed = holdings.get(key)
        if observed is None:
            findings.append(
                Finding(
                    "critical",
                    "missing_balance",
                    *key,
                    "required wallet/asset balance is absent",
                )
            )
        elif observed < requirement.minimum_quantity:
            findings.append(
                Finding(
                    "warning",
                    "below_minimum",
                    *key,
                    f"observed {observed} is below minimum {requirement.minimum_quantity}",
                )
            )
    working = dict(holdings)
    recommendations = []
    zero = Decimal(0)
    for (receiver, asset), minimum in sorted(minimums.items()):
        deficit = calculate(minimum, "-", working.get((receiver, asset), zero))
        if not deficit:
            continue
        donors = sorted(w for w, a in working if a == asset and w != receiver)
        for donor in donors:
            available = calculate(working[(donor, asset)], "-", minimums.get((donor, asset), zero))
            if not available:
                continue
            quantity = min(deficit, available)
            recommendations.append(MovementRecommendation(donor, receiver, asset, quantity))
            working[(donor, asset)] = calculate(working[(donor, asset)], "-", quantity)
            working[(receiver, asset)] = calculate(
                working.get((receiver, asset), zero), "+", quantity
            )
            deficit = calculate(deficit, "-", quantity)
            if not deficit:
                break
    return AnalysisReport(
        1, analyzed_at_ms, age, not findings, tuple(findings), tuple(recommendations)
    )
