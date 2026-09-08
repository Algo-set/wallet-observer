use crate::evm::RpcError;
use crate::provider::{
    BalanceProvider, BalanceRequest, EvmBalanceProvider, StaticValuationProvider, ValuationProvider,
};
use crate::types::{AssetKind, BalanceRecord, ObserverConfig, PortfolioSnapshot, WalletNav};
use rust_decimal::Decimal;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::env;
use std::str::FromStr;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ObserverError {
    #[error("configuration schema_version must be 1")]
    SchemaVersion,
    #[error("duplicate identifier: {0}")]
    DuplicateId(String),
    #[error("unknown chain: {0}")]
    UnknownChain(String),
    #[error("missing environment variable: {0}")]
    MissingEnvironment(String),
    #[error("invalid valuation price for {0}")]
    InvalidPrice(String),
    #[error("unknown balance provider: {0}")]
    UnknownProvider(String),
    #[error("balance provider {provider_id} failed: {code}")]
    Provider { provider_id: String, code: String },
    #[error("valuation provider failed: {0}")]
    Valuation(String),
    #[error("decimal overflow")]
    DecimalOverflow,
    #[error(transparent)]
    Rpc(#[from] RpcError),
}

pub async fn observe(config: &ObserverConfig) -> Result<PortfolioSnapshot, ObserverError> {
    validate_config(config)?;
    let observed_at_ms = unix_time_ms();
    let mut providers = HashMap::<String, Arc<dyn BalanceProvider>>::new();
    for chain in &config.chains {
        let endpoint = required_env(&chain.rpc_url_env)?;
        let provider = EvmBalanceProvider::new(endpoint)?;
        if let Some(expected) = chain.expected_chain_id {
            provider
                .verify_chain_id(expected)
                .await
                .map_err(|error| provider_error(&chain.id, error.code))?;
        }
        providers.insert(chain.id.clone(), Arc::new(provider));
    }

    let mut prices = HashMap::new();
    for asset in &config.assets {
        if let Some(raw_price) = &asset.valuation_price_usd {
            let price = Decimal::from_str(raw_price)
                .map_err(|_| ObserverError::InvalidPrice(asset.id.clone()))?;
            if price.is_sign_negative() {
                return Err(ObserverError::InvalidPrice(asset.id.clone()));
            }
            prices.insert((asset.chain_id.clone(), asset.id.clone()), price);
        }
    }

    let mut requests = Vec::new();
    for wallet in &config.wallets {
        let account_reference = required_env(&wallet.address_env)?;
        for asset in config
            .assets
            .iter()
            .filter(|asset| asset.chain_id == wallet.chain_id)
        {
            let asset_reference = match &asset.kind {
                AssetKind::Native => None,
                AssetKind::Erc20 {
                    contract_address_env,
                } => Some(required_env(contract_address_env)?),
            };
            requests.push(BalanceRequest {
                provider_id: wallet.chain_id.clone(),
                wallet_id: wallet.id.clone(),
                chain_id: wallet.chain_id.clone(),
                asset_id: asset.id.clone(),
                symbol: asset.symbol.clone(),
                account_reference: account_reference.clone(),
                asset_reference,
                decimals: asset.decimals,
            });
        }
    }

    let valuation = StaticValuationProvider::new(prices);
    observe_with_providers(&requests, &providers, &valuation, observed_at_ms).await
}

pub async fn observe_with_providers(
    requests: &[BalanceRequest],
    providers: &HashMap<String, Arc<dyn BalanceProvider>>,
    valuation: &dyn ValuationProvider,
    observed_at_ms: i64,
) -> Result<PortfolioSnapshot, ObserverError> {
    let mut balances = Vec::with_capacity(requests.len());
    let mut seen = HashSet::new();
    for request in requests {
        let key = (request.wallet_id.as_str(), request.asset_id.as_str());
        if !seen.insert(key) {
            return Err(ObserverError::DuplicateId(format!(
                "{}/{}",
                request.wallet_id, request.asset_id
            )));
        }
        let provider = providers
            .get(&request.provider_id)
            .ok_or_else(|| ObserverError::UnknownProvider(request.provider_id.clone()))?;
        let observed = provider
            .balance(request)
            .await
            .map_err(|error| provider_error(&request.provider_id, error.code))?;
        if observed.quantity.is_sign_negative() {
            return Err(provider_error(
                &request.provider_id,
                "invalid_provider_quantity".to_string(),
            ));
        }
        let unit_price_usd = valuation
            .unit_price_usd(request)
            .await
            .map_err(|error| ObserverError::Valuation(safe_error_code(&error.code)))?;
        if unit_price_usd.is_some_and(|price| price.is_sign_negative()) {
            return Err(ObserverError::Valuation(
                "invalid_valuation_price".to_string(),
            ));
        }
        let value_usd = unit_price_usd
            .map(|price| {
                observed
                    .quantity
                    .checked_mul(price)
                    .ok_or(ObserverError::DecimalOverflow)
            })
            .transpose()?;
        balances.push(BalanceRecord {
            wallet_id: request.wallet_id.clone(),
            chain_id: request.chain_id.clone(),
            asset_id: request.asset_id.clone(),
            symbol: request.symbol.clone(),
            atomic_units: observed.atomic_units.to_string(),
            quantity: observed.quantity,
            unit_price_usd,
            value_usd,
            source: request.provider_id.clone(),
        });
    }
    balances.sort_by(|left, right| {
        (&left.wallet_id, &left.asset_id).cmp(&(&right.wallet_id, &right.asset_id))
    });
    Ok(build_snapshot(observed_at_ms, balances))
}

pub fn build_snapshot(observed_at_ms: i64, balances: Vec<BalanceRecord>) -> PortfolioSnapshot {
    let mut valued = BTreeMap::<String, Decimal>::new();
    let mut unvalued = BTreeMap::<String, Vec<String>>::new();
    for balance in &balances {
        if let Some(value) = balance.value_usd {
            *valued.entry(balance.wallet_id.clone()).or_default() += value;
        } else {
            unvalued
                .entry(balance.wallet_id.clone())
                .or_default()
                .push(balance.asset_id.clone());
        }
    }
    let wallet_ids: BTreeMap<_, _> = balances
        .iter()
        .map(|balance| (balance.wallet_id.clone(), ()))
        .collect();
    let wallet_nav: Vec<_> = wallet_ids
        .into_keys()
        .map(|wallet_id| WalletNav {
            valued_nav_usd: valued.get(&wallet_id).copied().unwrap_or_default(),
            unvalued_assets: unvalued.remove(&wallet_id).unwrap_or_default(),
            wallet_id,
        })
        .collect();
    let total_valued_nav_usd = wallet_nav.iter().map(|wallet| wallet.valued_nav_usd).sum();
    PortfolioSnapshot {
        schema_version: 1,
        observed_at_ms,
        balances,
        wallet_nav,
        total_valued_nav_usd,
    }
}

fn validate_config(config: &ObserverConfig) -> Result<(), ObserverError> {
    if config.schema_version != 1 {
        return Err(ObserverError::SchemaVersion);
    }
    unique(config.chains.iter().map(|item| item.id.as_str()))?;
    unique(config.wallets.iter().map(|item| item.id.as_str()))?;
    unique(config.assets.iter().map(|item| item.id.as_str()))?;
    let chains: HashSet<_> = config.chains.iter().map(|item| item.id.as_str()).collect();
    for chain_id in config
        .wallets
        .iter()
        .map(|item| item.chain_id.as_str())
        .chain(config.assets.iter().map(|item| item.chain_id.as_str()))
    {
        if !chains.contains(chain_id) {
            return Err(ObserverError::UnknownChain(chain_id.to_string()));
        }
    }
    Ok(())
}

fn unique<'a>(values: impl Iterator<Item = &'a str>) -> Result<(), ObserverError> {
    let mut seen = HashSet::new();
    for value in values {
        if value.is_empty() || !seen.insert(value) {
            return Err(ObserverError::DuplicateId(value.to_string()));
        }
    }
    Ok(())
}

fn required_env(name: &str) -> Result<String, ObserverError> {
    env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ObserverError::MissingEnvironment(name.to_string()))
}

fn provider_error(provider_id: &str, code: String) -> ObserverError {
    ObserverError::Provider {
        provider_id: provider_id.to_string(),
        code: safe_error_code(&code),
    }
}

fn safe_error_code(code: &str) -> String {
    if [
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
    ]
    .contains(&code)
    {
        code.to_string()
    } else {
        "provider_failure".to_string()
    }
}

fn unix_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}
