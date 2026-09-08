import asyncio
import json
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from wallet_observer import (
    BalanceRecord,
    BalanceRequest,
    MinimumBalance,
    MovementRecommendation,
    ObserverError,
    PortfolioPolicy,
    PortfolioSnapshot,
    ProviderBalance,
    ProviderFailure,
    StaticValuationProvider,
    analyze,
    build_snapshot,
    observe_with_providers,
    quantity_from_atomic,
)


def balance(wallet, asset, quantity, price="1"):
    with localcontext() as context:
        context.prec = 256
        q = Decimal(quantity)
        p = None if price is None else Decimal(price)
        return BalanceRecord(
            wallet,
            "environment",
            asset,
            asset.upper(),
            "0",
            q,
            p,
            None if p is None else q * p,
            "fixture",
        )


def policy(*minimums, age=1000):
    return PortfolioPolicy(1, age, tuple(MinimumBalance(w, a, Decimal(q)) for w, a, q in minimums))


def test_nav_keeps_unpriced_assets_visible_and_round_trips():
    snapshot = build_snapshot(
        1000,
        [
            balance("operating", "usd", "50"),
            balance("reserve", "usd", "200"),
            balance("reserve", "gas", "3", None),
        ],
    )
    assert snapshot.total_valued_nav_usd == Decimal("250")
    assert snapshot.wallet_nav[1].unvalued_assets == ("gas",)
    assert PortfolioSnapshot.from_dict(json.loads(snapshot.to_json())) == snapshot


def test_donors_keep_their_floors_and_cannot_fund_twice():
    snapshot = build_snapshot(
        1000,
        [
            balance("a", "usd", "10"),
            balance("b", "usd", "0"),
            balance("reserve", "usd", "100"),
            balance("reserve", "other", "500"),
        ],
    )
    report = analyze(
        snapshot, policy(("a", "usd", "60"), ("b", "usd", "60"), ("reserve", "usd", "30")), 1100
    )
    assert [(r.to_wallet_id, r.quantity) for r in report.recommendations] == [
        ("a", Decimal("50")),
        ("b", Decimal("20")),
    ]
    assert all(not r.executable and r.requires_external_approval for r in report.recommendations)
    assert not report.healthy


def test_missing_stale_and_exact_age_boundary():
    snapshot = build_snapshot(1000, [balance("reserve", "usd", "100")])
    required = policy(("missing", "usd", "50"), age=100)
    report = analyze(snapshot, required, 1101)
    assert [f.code for f in report.findings] == ["stale_snapshot", "missing_balance"]
    assert report.recommendations[0].quantity == 50
    assert analyze(snapshot, policy(age=100), 1100).healthy
    assert analyze(snapshot, policy(age=100), 999).snapshot_age_ms == 0


def test_duplicate_or_inconsistent_inputs_rejected():
    item = balance("a", "usd", "1")
    with pytest.raises(ObserverError, match="duplicate_balance"):
        build_snapshot(1000, [item, item])
    snapshot = build_snapshot(1000, [item])
    with pytest.raises(ObserverError, match="duplicate_minimum"):
        analyze(snapshot, policy(("a", "usd", "1"), ("a", "usd", "1")), 1000)
    with pytest.raises(ObserverError, match="inconsistent_snapshot_nav"):
        analyze(replace(snapshot, total_valued_nav_usd=Decimal(999)), policy(), 1000)
    with pytest.raises(ObserverError, match="inconsistent_valuation"):
        build_snapshot(1000, [replace(item, value_usd=Decimal(4))])


@pytest.mark.parametrize(
    "bad", [-1, 0.1, True, "NaN", "sNaN", "Infinity", "-1", "1e1000", "9" * 97]
)
def test_invalid_quantities_rejected(bad):
    with pytest.raises(ObserverError):
        MinimumBalance("wallet", "asset", bad)


@pytest.mark.parametrize("bad", [-1, 29, True, 1.5])
def test_invalid_asset_scale_rejected(bad):
    with pytest.raises(ProviderFailure):
        quantity_from_atomic(1, bad)


def test_decimal_arithmetic_does_not_depend_on_callers_precision():
    balances = [balance("a", "usd", "12345.678901", "1.23456789"), balance("b", "usd", "1", "2")]
    reference = build_snapshot(1000, balances)
    with localcontext() as context:
        context.prec = 2
        assert build_snapshot(1000, balances) == reference
        assert quantity_from_atomic(1234500, 6) == Decimal("1.234500")
        assert quantity_from_atomic(2**128 - 1, 28) == Decimal(
            "34028236692.0938463463374607431768211455"
        )


def request():
    return BalanceRequest(
        "custom", "wallet", "environment", "asset", "UNIT", "opaque-account", "opaque-asset", 2
    )


class Balances:
    async def balance(self, request):
        return ProviderBalance(12345, Decimal("123.45"))


async def test_custom_providers_preserve_values_and_redact_references():
    item = request()
    snapshot = await observe_with_providers(
        [item],
        {"custom": Balances()},
        StaticValuationProvider({("custom", "asset"): Decimal("2.5")}),
        1000,
    )
    assert snapshot.total_valued_nav_usd == Decimal("308.625")
    assert "opaque-account" not in snapshot.to_json() + repr(item)
    assert "opaque-asset" not in snapshot.to_json() + repr(item)
    assert snapshot.balances[0].source == "custom"


@pytest.mark.parametrize(
    "failure", [ProviderFailure("opaque-account"), RuntimeError("opaque-account")]
)
async def test_upstream_error_text_does_not_escape(failure):
    class Failing:
        async def balance(self, request):
            raise failure

    with pytest.raises(ProviderFailure) as error:
        await observe_with_providers(
            [request()], {"custom": Failing()}, StaticValuationProvider({}), 1000
        )
    assert str(error.value) == "provider_failure"


@pytest.mark.parametrize(
    "atomic,quantity", [(True, "1"), (-1, "1"), (2**128, "1"), (1, "-1"), (1, "NaN"), (1, 0.5)]
)
async def test_bad_custom_balance_rejected(atomic, quantity):
    class Invalid:
        async def balance(self, request):
            return ProviderBalance(atomic, quantity)

    with pytest.raises(ProviderFailure, match="invalid_provider_quantity"):
        await observe_with_providers(
            [request()], {"custom": Invalid()}, StaticValuationProvider({}), 1000
        )


async def test_bad_valuation_and_cancellation():
    with pytest.raises(ProviderFailure, match="invalid_valuation_price"):
        await observe_with_providers(
            [request()],
            {"custom": Balances()},
            StaticValuationProvider({("custom", "asset"): Decimal(-1)}),
            1000,
        )

    class Cancelled:
        async def balance(self, request):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await observe_with_providers(
            [request()], {"custom": Cancelled()}, StaticValuationProvider({}), 1000
        )


def test_json_models_reject_ambiguous_data_and_executable_flags():
    with pytest.raises(ObserverError):
        MinimumBalance.from_dict(
            {"wallet_id": "a", "asset_id": "b", "minimum_quantity": "1", "extra": "value"}
        )
    with pytest.raises(ObserverError):
        PortfolioPolicy.from_dict(
            {"schema_version": True, "maximum_snapshot_age_ms": 100, "minimum_balances": []}
        )
    with pytest.raises(ObserverError):
        MovementRecommendation("a", "b", "asset", Decimal(1), executable=True)
