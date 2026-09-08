"""Synthetic portfolio and policy example; no network or environment required."""

from decimal import Decimal

from wallet_observer import BalanceRecord, MinimumBalance, PortfolioPolicy, analyze, build_snapshot

balances = [
    BalanceRecord(
        wallet,
        "example",
        "unit",
        "UNIT",
        "0",
        Decimal(quantity),
        Decimal(1),
        Decimal(quantity),
        "fixture",
    )
    for wallet, quantity in [("operating", "60"), ("reserve", "300")]
]
snapshot = build_snapshot(1000, balances)
policy = PortfolioPolicy(
    1,
    1000,
    (
        MinimumBalance("operating", "unit", Decimal(100)),
        MinimumBalance("reserve", "unit", Decimal(200)),
    ),
)
print(analyze(snapshot, policy, 1100).to_json())
