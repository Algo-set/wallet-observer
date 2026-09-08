use crate::evm::{quantity_from_atomic, EvmRpcClient, RpcError};
use async_trait::async_trait;
use rust_decimal::Decimal;
use std::collections::HashMap;

/// An in-memory request passed to a provider. Account and asset references are
/// intentionally omitted from all persisted output types.
pub struct BalanceRequest {
    pub provider_id: String,
    pub wallet_id: String,
    pub chain_id: String,
    pub asset_id: String,
    pub symbol: String,
    pub account_reference: String,
    pub asset_reference: Option<String>,
    pub decimals: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderBalance {
    pub atomic_units: u128,
    pub quantity: Decimal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderFailure {
    pub code: String,
}

impl ProviderFailure {
    pub fn new(code: impl Into<String>) -> Self {
        Self { code: code.into() }
    }
}

#[async_trait]
pub trait BalanceProvider: Send + Sync {
    async fn balance(&self, request: &BalanceRequest) -> Result<ProviderBalance, ProviderFailure>;
}

#[async_trait]
pub trait ValuationProvider: Send + Sync {
    async fn unit_price_usd(
        &self,
        request: &BalanceRequest,
    ) -> Result<Option<Decimal>, ProviderFailure>;
}

pub struct EvmBalanceProvider {
    client: EvmRpcClient,
}

impl EvmBalanceProvider {
    pub fn new(endpoint: String) -> Result<Self, RpcError> {
        Ok(Self {
            client: EvmRpcClient::new(endpoint)?,
        })
    }

    pub async fn verify_chain_id(&self, expected: u64) -> Result<(), ProviderFailure> {
        let observed = self.client.chain_id().await.map_err(evm_failure)?;
        if observed == expected {
            Ok(())
        } else {
            Err(ProviderFailure::new("chain_id_mismatch"))
        }
    }
}

#[async_trait]
impl BalanceProvider for EvmBalanceProvider {
    async fn balance(&self, request: &BalanceRequest) -> Result<ProviderBalance, ProviderFailure> {
        let atomic = match &request.asset_reference {
            Some(token) => {
                self.client
                    .token_balance(token, &request.account_reference)
                    .await
            }
            None => self.client.native_balance(&request.account_reference).await,
        }
        .map_err(evm_failure)?;
        let quantity = quantity_from_atomic(atomic, request.decimals).map_err(evm_failure)?;
        Ok(ProviderBalance {
            atomic_units: atomic,
            quantity,
        })
    }
}

pub struct StaticValuationProvider {
    prices: HashMap<(String, String), Decimal>,
}

impl StaticValuationProvider {
    pub fn new(prices: HashMap<(String, String), Decimal>) -> Self {
        Self { prices }
    }
}

#[async_trait]
impl ValuationProvider for StaticValuationProvider {
    async fn unit_price_usd(
        &self,
        request: &BalanceRequest,
    ) -> Result<Option<Decimal>, ProviderFailure> {
        Ok(self
            .prices
            .get(&(request.provider_id.clone(), request.asset_id.clone()))
            .copied())
    }
}

fn evm_failure(error: RpcError) -> ProviderFailure {
    let code = match error {
        RpcError::InvalidAddress => "invalid_account_or_asset_reference",
        RpcError::InvalidUrl => "invalid_provider_endpoint",
        RpcError::Network(_) => "provider_network_error",
        RpcError::Response(_) => "provider_response_error",
        RpcError::InvalidQuantity(_) => "invalid_provider_quantity",
        RpcError::UnsupportedDecimals => "unsupported_asset_decimals",
        RpcError::MethodNotAllowed => "provider_method_not_allowed",
    };
    ProviderFailure::new(code)
}
