import json
import os
import random
import subprocess
from decimal import Decimal

import pytest

from wallet_observer import BalanceRecord, MinimumBalance, PortfolioPolicy, analyze, build_snapshot


def normalize(value, key=None):
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if value is not None and key in {
        "quantity",
        "unit_price_usd",
        "value_usd",
        "valued_nav_usd",
        "total_valued_nav_usd",
    }:
        return Decimal(value)
    return value


def test_generated_portfolios_and_policies_match_rust():
    executable = os.environ.get("WALLET_OBSERVER_RUST_REPLAY")
    if not executable:
        pytest.skip("build replay_portfolio and set WALLET_OBSERVER_RUST_REPLAY")
    rng = random.Random(701)
    cases, expected = [], []
    for index in range(40):
        balances, minimums = [], []
        for wallet in ("operating", "reserve", "secondary"):
            for asset in ("unit-a", "unit-b"):
                q = Decimal(rng.randrange(0, 500)) / Decimal(100)
                price = None if asset == "unit-b" else Decimal("2.50")
                balances.append(
                    BalanceRecord(
                        wallet,
                        "environment",
                        asset,
                        "UNIT",
                        "0",
                        q,
                        price,
                        None if price is None else q * price,
                        "fixture",
                    )
                )
                if rng.choice([True, False]):
                    minimums.append(
                        MinimumBalance(wallet, asset, Decimal(rng.randrange(0, 500)) / Decimal(100))
                    )
        if index % 4 == 0:
            minimums.append(MinimumBalance("missing", "unit-a", Decimal(1)))
        snapshot = build_snapshot(1000, balances)
        policy = PortfolioPolicy(1, 100, minimums)
        when = 1000 + index * 10
        cases.append(
            {"snapshot": snapshot.to_dict(), "policy": policy.to_dict(), "analyzed_at_ms": when}
        )
        expected.append(
            {"snapshot": snapshot.to_dict(), "report": analyze(snapshot, policy, when).to_dict()}
        )
    run = subprocess.run(
        [executable],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert normalize(json.loads(run.stdout)) == normalize(expected)
