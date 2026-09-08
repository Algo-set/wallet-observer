//! Keyless wallet observation and policy analysis.
//!
//! Network access is restricted to an allowlist of read-only EVM JSON-RPC
//! methods. Reports identify wallets by caller-defined logical IDs and do not
//! persist addresses or RPC URLs.

pub mod evm;
pub mod observer;
pub mod policy;
pub mod provider;
pub mod types;

pub use observer::{observe, observe_with_providers, ObserverError};
pub use policy::{analyze, AnalysisError};
pub use provider::{
    BalanceProvider, BalanceRequest, EvmBalanceProvider, ProviderBalance, ProviderFailure,
    StaticValuationProvider, ValuationProvider,
};
pub use types::*;
