import asyncio
from dataclasses import replace

import pytest

from wallet_observer import ObserverConfig, ObserverError, ProviderBalance, ProviderFailure, observe
from wallet_observer import observer as module


def config():
    return ObserverConfig.from_dict(
        {
            "schema_version": 1,
            "chains": [{"id": "chain", "rpc_url_env": "TEST_WALLET_RPC", "expected_chain_id": 1}],
            "wallets": [
                {"id": "wallet", "chain_id": "chain", "address_env": "TEST_WALLET_ACCOUNT"}
            ],
            "assets": [
                {
                    "id": "unit",
                    "chain_id": "chain",
                    "symbol": "UNIT",
                    "decimals": 2,
                    "kind": {"type": "native"},
                    "valuation_price_usd": "2",
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "failure", [None, ProviderFailure("chain_id_mismatch"), asyncio.CancelledError()]
)
async def test_observe_closes_clients_on_success_failure_and_cancellation(monkeypatch, failure):
    closed = []

    class Fixture:
        def __init__(self, endpoint):
            assert endpoint == "https://rpc.example.test/opaque"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        async def verify_chain_id(self, expected):
            assert expected == 1
            if failure is not None:
                raise failure

        async def balance(self, request):
            assert request.account_reference == "opaque-account"
            return ProviderBalance(100, "1.00")

    monkeypatch.setattr(module, "EvmBalanceProvider", Fixture)
    monkeypatch.setenv("TEST_WALLET_RPC", "https://rpc.example.test/opaque")
    monkeypatch.setenv("TEST_WALLET_ACCOUNT", "opaque-account")
    if failure is not None:
        with pytest.raises(type(failure)):
            await observe(config())
    else:
        result = await observe(config())
        assert result.total_valued_nav_usd == 2
        assert "opaque" not in result.to_json()
    assert closed == [True]


async def test_configuration_validated_before_network(monkeypatch):
    def forbidden(*args):
        pytest.fail("network adapter must not be created")

    monkeypatch.setattr(module, "EvmBalanceProvider", forbidden)
    original = config()
    variants = [
        replace(original, schema_version=2),
        replace(original, chains=original.chains * 2),
        replace(original, wallets=(replace(original.wallets[0], chain_id="missing"),)),
        replace(original, assets=(replace(original.assets[0], decimals=29),)),
        replace(original, assets=(replace(original.assets[0], kind={"type": "unknown"}),)),
    ]
    for variant in variants:
        with pytest.raises(ObserverError):
            await observe(variant)
    monkeypatch.delenv("TEST_WALLET_RPC", raising=False)
    with pytest.raises(ObserverError, match="missing_environment"):
        await observe(original)
