"""Immutable records with the Rust implementation's JSON field names."""

import json
from dataclasses import dataclass, fields
from decimal import Decimal
from types import UnionType
from typing import Self, get_args, get_origin, get_type_hints

from ._validation import ObserverError, amount, integer


def _decode(value, kind):
    if get_origin(kind) is UnionType:
        if value is None and type(None) in get_args(kind):
            return None
        return _decode(value, next(k for k in get_args(kind) if k is not type(None)))
    if get_origin(kind) is tuple:
        if not isinstance(value, (tuple, list)):
            raise ObserverError("invalid_record")
        return tuple(_decode(v, get_args(kind)[0]) for v in value)
    if kind is Decimal:
        return amount(value)
    if kind is int:
        return integer(value, -(2**63))
    if kind in (str, bool):
        if type(value) is not kind:
            raise ObserverError("invalid_record")
        return value
    if isinstance(value, kind):
        return value
    return kind.from_dict(value)


def _encode(value):
    if isinstance(value, Record):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_encode(v) for v in value]
    return value


class Record:
    def __post_init__(self):
        hints = get_type_hints(type(self))
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "expected_chain_id" and value is not None:
                value = integer(value, 0, 2**64 - 1)
            else:
                value = _decode(value, hints[f.name])
            object.__setattr__(self, f.name, value)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        if not isinstance(data, dict):
            raise ObserverError("invalid_record")
        names = {f.name for f in fields(cls)}
        if data.keys() - names:
            raise ObserverError("unknown_record_field")
        try:
            return cls(**data)
        except (TypeError, KeyError):
            raise ObserverError("invalid_record") from None

    def to_dict(self) -> dict:
        return _encode(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, allow_nan=False)


@dataclass(frozen=True)
class ChainConfig(Record):
    id: str
    rpc_url_env: str
    expected_chain_id: int | None = None


@dataclass(frozen=True)
class WalletConfig(Record):
    id: str
    chain_id: str
    address_env: str


@dataclass(frozen=True)
class AssetKind(Record):
    type: str
    contract_address_env: str | None = None


@dataclass(frozen=True)
class AssetConfig(Record):
    id: str
    chain_id: str
    symbol: str
    decimals: int
    kind: AssetKind
    valuation_price_usd: Decimal | None = None


@dataclass(frozen=True)
class ObserverConfig(Record):
    schema_version: int
    chains: tuple[ChainConfig, ...]
    wallets: tuple[WalletConfig, ...]
    assets: tuple[AssetConfig, ...]


@dataclass(frozen=True)
class BalanceRecord(Record):
    wallet_id: str
    chain_id: str
    asset_id: str
    symbol: str
    atomic_units: str
    quantity: Decimal
    unit_price_usd: Decimal | None
    value_usd: Decimal | None
    source: str


@dataclass(frozen=True)
class WalletNav(Record):
    wallet_id: str
    valued_nav_usd: Decimal
    unvalued_assets: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioSnapshot(Record):
    schema_version: int
    observed_at_ms: int
    balances: tuple[BalanceRecord, ...]
    wallet_nav: tuple[WalletNav, ...]
    total_valued_nav_usd: Decimal


@dataclass(frozen=True)
class MinimumBalance(Record):
    wallet_id: str
    asset_id: str
    minimum_quantity: Decimal


@dataclass(frozen=True)
class PortfolioPolicy(Record):
    schema_version: int
    maximum_snapshot_age_ms: int
    minimum_balances: tuple[MinimumBalance, ...]


@dataclass(frozen=True)
class Finding(Record):
    severity: str
    code: str
    wallet_id: str | None
    asset_id: str | None
    detail: str


@dataclass(frozen=True)
class MovementRecommendation(Record):
    from_wallet_id: str
    to_wallet_id: str
    asset_id: str
    quantity: Decimal
    reason: str = "restore configured minimum balance"
    executable: bool = False
    requires_external_approval: bool = True

    def __post_init__(self):
        super().__post_init__()
        if self.executable or not self.requires_external_approval:
            raise ObserverError("non_executable_recommendation_required")


@dataclass(frozen=True)
class AnalysisReport(Record):
    schema_version: int
    analyzed_at_ms: int
    snapshot_age_ms: int
    healthy: bool
    findings: tuple[Finding, ...]
    recommendations: tuple[MovementRecommendation, ...]
