# wallet-observer · Python

A standalone Python library and CLI for observing balances, calculating valued
NAV, checking balance floors and proposing logical movements. It implements the
Rust component's normal-value data and policy contracts without requiring Rust
or the private Algo Set platform.

This is unofficial community software. It holds no signing keys and has no
transaction construction, signing, approval or broadcasting API. Every movement
recommendation has `executable: false` and `requires_external_approval: true`.

## Install

Requires Python 3.11 or newer. From this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./python
python -m wallet_observer --help
```

This package is available as source on GitHub; it has not been published to PyPI.
The Rust and Python entry points share the name `wallet-observer`. Use
`python -m wallet_observer` to select Python unambiguously.

## CLI

Both versions use the repository's `config.example.json`, `policy.example.json`
and the same snapshot/report JSON field names. Decimal fields are JSON strings.

```bash
python -m wallet_observer snapshot config.example.json snapshot.json
python -m wallet_observer analyze snapshot.json policy.example.json report.json
python -m wallet_observer analyze fixtures/example_snapshot.json fixtures/example_policy.json
```

The last command is fully offline. Its historical fixture can produce a stale
finding. An unhealthy analysis still exits successfully: inspect `healthy` and
`findings`. Invalid input or provider failure exits with 2; interruption exits
with 130. Output files are written through a unique, owner-readable temporary
file and atomically replaced only after serialization and flushing succeed.

Configuration names environment variables containing RPC endpoints and opaque
account/token references. Set their values outside this repository. Logical
wallet, provider and asset IDs are caller-defined and must be non-secret labels;
use a globally distinct asset ID when assets belong to different environments.
The supplied adapter supports native EVM balances and ERC-20 `balanceOf` queries.
Its entire RPC method set is `eth_chainId`, `eth_getBalance` and `eth_call`.

## Custom providers

```python
import asyncio
from decimal import Decimal
from wallet_observer import (
    BalanceRequest,
    ProviderBalance,
    StaticValuationProvider,
    observe_with_providers,
)


class FixtureBalances:
    async def balance(self, request):
        return ProviderBalance(12345, Decimal("123.45"))


async def main():
    request = BalanceRequest(
        provider_id="fixture",
        wallet_id="reserve",
        chain_id="environment-a",
        asset_id="inventory",
        symbol="UNIT",
        account_reference="opaque-account",
        asset_reference=None,
        decimals=2,
    )
    snapshot = await observe_with_providers(
        [request],
        {"fixture": FixtureBalances()},
        StaticValuationProvider({("fixture", "inventory"): Decimal("2.50")}),
        observed_at_ms=1000,
    )
    print(snapshot.to_json())


asyncio.run(main())
```

`BalanceProvider` and `ValuationProvider` are asynchronous protocols. Callers
own the lifetime and behavior of custom providers; these must remain read-only.
The built-in `observe` function owns and closes all EVM clients, including on
failure or cancellation. Direct EVM clients/providers support `async with`.

Account and asset references are hidden from request `repr` output and omitted
from persisted snapshot types. Python introspection can still access in-memory
request fields. Unknown provider exceptions become fixed error codes; raw
upstream messages and endpoint values are not printed by the CLI. Custom
providers remain responsible for their own logging and network behavior.

## Numeric and policy behavior

- Exact `Decimal` arithmetic uses a private context and fails instead of silently
  rounding. Floats, negative and nonfinite quantities/prices are rejected.
- Decimal values are bounded to 96 coefficient digits and exponents -56 through
  56. Atomic units are unsigned 128-bit integers; EVM decimals are 0–28.
  Python does not emulate Rust's 96-bit decimal overflow/rounding at extremes.
- NAV includes valued assets only. Unpriced assets remain visible in each
  wallet's `unvalued_assets`; an absent price is not treated as zero.
- Floors, missing/stale findings, deterministic donor ordering and surplus
  allocation mirror the Rust policy. Recommendations can accompany stale or
  missing-balance findings: inspect those findings before external review.
- A future observation timestamp has age zero, matching Rust. The package does
  not synchronize clocks or prove an observation's freshness.
- Python additionally rejects unknown JSON fields, duplicate JSON keys, invalid
  quantities and inconsistent persisted valuation/NAV totals. Custom providers
  define the relationship between their atomic units and quantity.

The default HTTP client verifies TLS, disables redirects and ambient proxies,
and bounds requests to 10 seconds and responses to 1 MiB. Endpoint URLs may
contain provider routing paths/query parameters, but not embedded URL userinfo
or fragments. Use trusted read-only endpoints. No live oracle, recurring
scheduler, history database or execution system is included.

## Test and build

```bash
cd python
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build --no-isolation
```

Tests use synthetic fixtures and mock HTTP transports. CI runs Python 3.11–3.14,
builds and installs the wheel outside the source tree, and compares generated
portfolio/policy fixtures with the Rust implementation. To run parity locally:

```bash
cargo build --locked --manifest-path ../Cargo.toml --example replay_portfolio
WALLET_OBSERVER_RUST_REPLAY=../target/debug/examples/replay_portfolio python -m pytest tests/test_rust_parity.py
```

See the repository's [security policy](../SECURITY.md),
[dependency policy](../DEPENDENCIES.md) and [MIT license](LICENSE).
