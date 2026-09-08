# Wallet observer

A standalone, keyless Rust library and CLI for observing wallet balances,
calculating valued NAV, enforcing configurable balance floors, and producing
non-executable movement recommendations.

Wallets, providers, environments, asset types, balances, valuations, floors,
and logical IDs are caller-defined. EVM JSON-RPC is one optional built-in
adapter, not a requirement of the core.

This is unofficial community software and is not affiliated with, endorsed by,
or sponsored by any wallet provider, chain operator, exchange, or custodian.
Upstream APIs may change without notice.

## Safety boundary

This is an observation and policy package, not a custody system. It cannot:

- construct or encode a transaction;
- sign messages or transactions;
- approve token spending;
- submit or broadcast a transaction; or
- hold a private key, seed phrase, or signing credential.

Movement recommendations always contain `executable: false` and
`requires_external_approval: true`.

## Architecture

```text
Caller-defined BalanceProvider ----+
                                    |
Caller-defined ValuationProvider --+--> PortfolioSnapshot --> policy analysis
                                                                     |
                                                                     v
                                                      findings and logical
                                                      recommendations only
```

The core exposes two asynchronous plug-in traits:

- `BalanceProvider`: resolves an opaque account/asset request into a quantity.
- `ValuationProvider`: optionally assigns a USD unit value to that quantity.

This supports read-only chain nodes, exchange accounts, custody APIs, databases,
price services, static fixtures, or other caller-owned sources without changing
portfolio or policy code.

Custom implementations are outside the shipped package's audited network
boundary. They should remain read-only and must not introduce credentials or
execution behavior into this process.

## Build and test

Rust 1.88 or newer is required.

```bash
cargo build --locked
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

Tests cover exact decimal conversion, NAV aggregation, stale snapshots, balance
floors, movement recommendations, duplicate policy entries, arbitrary custom
providers, opaque-reference redaction, safe provider errors, and the absence of
transaction or secret-handling capabilities.

## Built-in EVM adapter

The included EVM client has a closed JSON-RPC allowlist:

- `eth_chainId`
- `eth_getBalance`
- `eth_call`, used only for ERC-20 `balanceOf(address)`

No generic JSON-RPC call is publicly exposed. The CLI reads RPC endpoints,
wallet addresses, and token contract addresses from environment variables named
in the configuration. Their values are never written to snapshots.

## Configure observation

Start with [`config.example.json`](config.example.json):

```json
{
  "schema_version": 1,
  "chains": [
    {
      "id": "evm-primary",
      "rpc_url_env": "WALLET_OBSERVER_RPC_URL",
      "expected_chain_id": null
    }
  ],
  "wallets": [
    {
      "id": "operating",
      "chain_id": "evm-primary",
      "address_env": "OPERATING_WALLET_ADDRESS"
    }
  ],
  "assets": [
    {
      "id": "stablecoin",
      "chain_id": "evm-primary",
      "symbol": "USD-STABLE",
      "decimals": 6,
      "kind": {
        "type": "erc20",
        "contract_address_env": "STABLECOIN_CONTRACT_ADDRESS"
      },
      "valuation_price_usd": "1.00"
    }
  ]
}
```

Configuration fields:

| Field | Meaning |
|---|---|
| `chains[].id` | Caller-defined logical provider/environment ID |
| `rpc_url_env` | Name of the environment variable containing the endpoint |
| `expected_chain_id` | Optional network identity check |
| `wallets[].id` | Non-secret logical wallet ID persisted in reports |
| `address_env` | Name of the environment variable containing the account reference |
| `assets[].id` | Caller-defined logical asset ID |
| `decimals` | Atomic-unit decimal places, up to 28 for the EVM adapter |
| `kind` | `native` or `erc20` for the built-in EVM adapter |
| `valuation_price_usd` | Optional exact decimal string used by the static valuation adapter |

Set the named environment variables outside the package, then collect a
snapshot:

```bash
export WALLET_OBSERVER_RPC_URL='https://your-read-only-endpoint.example'
export OPERATING_WALLET_ADDRESS='YOUR_ACCOUNT_REFERENCE'
export STABLECOIN_CONTRACT_ADDRESS='YOUR_ASSET_REFERENCE'

cargo run --locked --bin wallet-observer -- \
  snapshot config.example.json snapshot.json
```

Snapshot writes are atomic: the CLI writes a temporary file and renames it only
after serialization succeeds.

## Configure policy

Start with [`policy.example.json`](policy.example.json):

```json
{
  "schema_version": 1,
  "maximum_snapshot_age_ms": 60000,
  "minimum_balances": [
    {
      "wallet_id": "operating",
      "asset_id": "stablecoin",
      "minimum_quantity": "100.00"
    }
  ]
}
```

All floors are arbitrary caller-supplied decimal values. They are not hardcoded,
scaled, or inferred by the package. Duplicate wallet/asset minimums and negative
minimums are rejected.

Analyze a snapshot and print the result:

```bash
cargo run --locked --bin wallet-observer -- \
  analyze snapshot.json policy.example.json
```

Write the result atomically instead:

```bash
cargo run --locked --bin wallet-observer -- \
  analyze snapshot.json policy.example.json report.json
```

The fully offline fixture can be used without an endpoint:

```bash
cargo run --locked --bin wallet-observer -- \
  analyze fixtures/example_snapshot.json fixtures/example_policy.json
```

## Output contracts

`PortfolioSnapshot` contains:

- logical wallet, provider, and asset IDs;
- exact atomic units and decimal quantities;
- optional unit price and valued amount;
- per-wallet valued NAV and unvalued asset IDs; and
- total valued NAV across wallets.

Assets without a valuation remain visible but are excluded from valued NAV.
This prevents an absent price from silently being treated as zero.

`AnalysisReport` contains:

- snapshot freshness;
- missing, stale, or below-minimum findings;
- a health flag; and
- logical movement recommendations from available surplus.

Recommendations do not account for fees, withdrawal restrictions, settlement
delays, or chain execution. Those concerns belong to a separately authorized
system.

## Custom providers

Use `observe_with_providers` to supply arbitrary balance and valuation sources:

```rust,no_run
use async_trait::async_trait;
use rust_decimal::Decimal;
use wallet_observer::{
    BalanceProvider, BalanceRequest, ProviderBalance, ProviderFailure,
};

struct MyReadOnlyProvider;

#[async_trait]
impl BalanceProvider for MyReadOnlyProvider {
    async fn balance(
        &self,
        request: &BalanceRequest,
    ) -> Result<ProviderBalance, ProviderFailure> {
        let _opaque_reference = &request.account_reference;
        Ok(ProviderBalance {
            atomic_units: 12_500,
            quantity: Decimal::new(125, 0),
        })
    }
}
```

`BalanceRequest` carries opaque account and asset references in memory only.
`PortfolioSnapshot` has no dedicated fields for serializing those references.
The persisted `source` field is the caller-defined logical provider ID, so all
logical IDs should be non-secret labels rather than account references.

Provider atomic balances are a `u128`, and negative quantities or valuations
are rejected before a snapshot is built. This prevents arbitrary upstream text
from entering the persisted atomic-balance field.

Custom provider failures are reduced to a closed set of machine-safe codes.
Unrecognized text becomes `provider_failure`, preventing upstream response text
or opaque references from leaking into reports.

## Privacy model

- Source files contain no endpoints, addresses, account IDs, or credentials.
- Configuration contains environment-variable names, not their values.
- Snapshots contain logical IDs and never wallet or token addresses.
- Provider and connector errors do not include upstream payloads or endpoints.
- The source test rejects concrete EVM addresses and local filesystem paths.
- `.env`, key, certificate, state, and build-output files are ignored.

## Current limitations

- The built-in CLI composes only the EVM and static valuation adapters.
- Other providers are integrated through the library traits.
- Static valuation is configuration, not a live price oracle.
- The package does not persist history or schedule recurring observations.
- It does not execute the movement recommendations it produces.

## License

Licensed under the MIT License. See [`LICENSE`](LICENSE).

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and review guidance,
[DEPENDENCIES.md](DEPENDENCIES.md) for dependency policy, and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.
