"""Portfolio observation with caller-defined providers and logical identifiers."""

import os
import re
import time
from contextlib import AsyncExitStack
from decimal import Decimal

from ._validation import ObserverError, amount, calculate, integer, unique
from .evm import EvmBalanceProvider
from .provider import (
    BalanceProvider,
    BalanceRequest,
    ProviderFailure,
    StaticValuationProvider,
    ValuationProvider,
)
from .types import BalanceRecord, ObserverConfig, PortfolioSnapshot, WalletNav


def build_snapshot(observed_at_ms: int, balances: list[BalanceRecord]) -> PortfolioSnapshot:
    integer(observed_at_ms)
    seen = set()
    valued: dict[str, Decimal] = {}
    unvalued: dict[str, list[str]] = {}
    for balance in balances:
        key = (balance.wallet_id, balance.asset_id)
        if key in seen:
            raise ObserverError("duplicate_balance")
        seen.add(key)
        for label in (balance.wallet_id, balance.asset_id, balance.chain_id, balance.source):
            unique([label])
        if not re.fullmatch(r"[0-9]{1,39}", balance.atomic_units):
            raise ObserverError("invalid_provider_quantity")
        integer(int(balance.atomic_units), 0, 2**128 - 1)
        expected = (
            None
            if balance.unit_price_usd is None
            else calculate(balance.quantity, "*", balance.unit_price_usd)
        )
        if expected != balance.value_usd:
            raise ObserverError("inconsistent_valuation")
        wallet = balance.wallet_id
        valued.setdefault(wallet, Decimal(0))
        unvalued.setdefault(wallet, [])
        if balance.value_usd is None:
            unvalued[wallet].append(balance.asset_id)
        else:
            valued[wallet] = calculate(valued[wallet], "+", balance.value_usd)
    nav = tuple(WalletNav(w, valued[w], tuple(unvalued[w])) for w in sorted(valued))
    total = Decimal(0)
    for wallet in nav:
        total = calculate(total, "+", wallet.valued_nav_usd)
    return PortfolioSnapshot(1, observed_at_ms, tuple(balances), nav, total)


async def observe_with_providers(
    requests: list[BalanceRequest],
    providers: dict[str, BalanceProvider],
    valuation: ValuationProvider,
    observed_at_ms: int,
) -> PortfolioSnapshot:
    integer(observed_at_ms)
    seen = set()
    for request in requests:
        for label in (request.provider_id, request.wallet_id, request.chain_id, request.asset_id):
            unique([label])
        if (request.wallet_id, request.asset_id) in seen:
            raise ObserverError("duplicate_balance")
        seen.add((request.wallet_id, request.asset_id))
        if request.provider_id not in providers:
            raise ObserverError("unknown_provider")
        integer(request.decimals, 0, 28)
    balances = []
    for request in requests:
        try:
            observed = await providers[request.provider_id].balance(request)
        except ProviderFailure as error:
            raise ProviderFailure(error.code) from None
        except Exception:
            raise ProviderFailure() from None
        try:
            atomic = integer(observed.atomic_units, 0, 2**128 - 1)
            quantity = amount(observed.quantity)
        except (ObserverError, AttributeError):
            raise ProviderFailure("invalid_provider_quantity") from None
        try:
            price = await valuation.unit_price_usd(request)
        except ProviderFailure as error:
            raise ProviderFailure(error.code) from None
        except Exception:
            raise ProviderFailure() from None
        try:
            price = None if price is None else amount(price)
        except ObserverError:
            raise ProviderFailure("invalid_valuation_price") from None
        value = None if price is None else calculate(quantity, "*", price)
        balances.append(
            BalanceRecord(
                request.wallet_id,
                request.chain_id,
                request.asset_id,
                request.symbol,
                str(atomic),
                quantity,
                price,
                value,
                request.provider_id,
            )
        )
    balances.sort(key=lambda b: (b.wallet_id, b.asset_id))
    return build_snapshot(observed_at_ms, balances)


def _required_env(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ObserverError("invalid_environment_name")
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ObserverError("missing_environment")
    return value


def _validate_config(config: ObserverConfig):
    if config.schema_version != 1:
        raise ObserverError("schema_version")
    for group in (config.chains, config.wallets, config.assets):
        unique([item.id for item in group])
    chains = {c.id for c in config.chains}
    for item in (*config.wallets, *config.assets):
        if item.chain_id not in chains:
            raise ObserverError("unknown_chain")
    for chain in config.chains:
        if chain.expected_chain_id is not None:
            integer(chain.expected_chain_id, 0, 2**64 - 1)
    for asset in config.assets:
        integer(asset.decimals, 0, 28)
        if asset.kind.type == "native":
            if asset.kind.contract_address_env is not None:
                raise ObserverError("invalid_asset_kind")
        elif asset.kind.type != "erc20" or not asset.kind.contract_address_env:
            raise ObserverError("invalid_asset_kind")


async def observe(config: ObserverConfig) -> PortfolioSnapshot:
    """Collect through owned EVM clients; always close them, including on cancellation."""
    _validate_config(config)
    observed_at_ms = time.time_ns() // 1_000_000
    endpoints = {c.id: _required_env(c.rpc_url_env) for c in config.chains}
    requests = []
    for wallet in config.wallets:
        account = _required_env(wallet.address_env)
        for asset in config.assets:
            if asset.chain_id == wallet.chain_id:
                reference = (
                    _required_env(asset.kind.contract_address_env)
                    if asset.kind.type == "erc20"
                    else None
                )
                requests.append(
                    BalanceRequest(
                        wallet.chain_id,
                        wallet.id,
                        wallet.chain_id,
                        asset.id,
                        asset.symbol,
                        account,
                        reference,
                        asset.decimals,
                    )
                )
    prices = {
        (a.chain_id, a.id): a.valuation_price_usd
        for a in config.assets
        if a.valuation_price_usd is not None
    }
    async with AsyncExitStack() as stack:
        providers = {}
        for chain in config.chains:
            provider = await stack.enter_async_context(EvmBalanceProvider(endpoints[chain.id]))
            if chain.expected_chain_id is not None:
                await provider.verify_chain_id(chain.expected_chain_id)
            providers[chain.id] = provider
        return await observe_with_providers(
            requests,
            providers,
            StaticValuationProvider(prices),
            observed_at_ms,
        )
