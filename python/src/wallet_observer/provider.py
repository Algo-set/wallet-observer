"""Caller-owned asynchronous balance and valuation interfaces."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from ._validation import ObserverError

_CODES = frozenset(
    {
        "chain_id_mismatch",
        "invalid_account_or_asset_reference",
        "invalid_provider_endpoint",
        "invalid_provider_quantity",
        "invalid_valuation_price",
        "provider_failure",
        "provider_method_not_allowed",
        "provider_network_error",
        "provider_response_error",
        "unsupported_asset_decimals",
        "valuation_unavailable",
    }
)


class ProviderFailure(ObserverError):
    def __init__(self, code: str = "provider_failure"):
        self.code = code if isinstance(code, str) and code in _CODES else "provider_failure"
        super().__init__(self.code)


@dataclass(frozen=True)
class BalanceRequest:
    provider_id: str
    wallet_id: str
    chain_id: str
    asset_id: str
    symbol: str
    account_reference: str = field(repr=False)
    asset_reference: str | None = field(repr=False)
    decimals: int


@dataclass(frozen=True)
class ProviderBalance:
    atomic_units: int
    quantity: Decimal


class BalanceProvider(Protocol):
    async def balance(self, request: BalanceRequest) -> ProviderBalance: ...


class ValuationProvider(Protocol):
    async def unit_price_usd(self, request: BalanceRequest) -> Decimal | None: ...


class StaticValuationProvider:
    def __init__(self, prices: dict[tuple[str, str], Decimal]):
        self._prices = dict(prices)

    async def unit_price_usd(self, request: BalanceRequest) -> Decimal | None:
        return self._prices.get((request.provider_id, request.asset_id))
