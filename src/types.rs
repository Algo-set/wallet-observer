use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChainConfig {
    pub id: String,
    pub rpc_url_env: String,
    pub expected_chain_id: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WalletConfig {
    pub id: String,
    pub chain_id: String,
    pub address_env: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AssetKind {
    Native,
    Erc20 { contract_address_env: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AssetConfig {
    pub id: String,
    pub chain_id: String,
    pub symbol: String,
    pub decimals: u32,
    pub kind: AssetKind,
    pub valuation_price_usd: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObserverConfig {
    pub schema_version: u32,
    pub chains: Vec<ChainConfig>,
    pub wallets: Vec<WalletConfig>,
    pub assets: Vec<AssetConfig>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BalanceRecord {
    pub wallet_id: String,
    pub chain_id: String,
    pub asset_id: String,
    pub symbol: String,
    pub atomic_units: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub quantity: Decimal,
    #[serde(with = "rust_decimal::serde::str_option")]
    pub unit_price_usd: Option<Decimal>,
    #[serde(with = "rust_decimal::serde::str_option")]
    pub value_usd: Option<Decimal>,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WalletNav {
    pub wallet_id: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub valued_nav_usd: Decimal,
    pub unvalued_assets: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PortfolioSnapshot {
    pub schema_version: u32,
    pub observed_at_ms: i64,
    pub balances: Vec<BalanceRecord>,
    pub wallet_nav: Vec<WalletNav>,
    #[serde(with = "rust_decimal::serde::str")]
    pub total_valued_nav_usd: Decimal,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MinimumBalance {
    pub wallet_id: String,
    pub asset_id: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub minimum_quantity: Decimal,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PortfolioPolicy {
    pub schema_version: u32,
    pub maximum_snapshot_age_ms: i64,
    pub minimum_balances: Vec<MinimumBalance>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Warning,
    Critical,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Finding {
    pub severity: Severity,
    pub code: String,
    pub wallet_id: Option<String>,
    pub asset_id: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MovementRecommendation {
    pub from_wallet_id: String,
    pub to_wallet_id: String,
    pub asset_id: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub quantity: Decimal,
    pub reason: String,
    pub executable: bool,
    pub requires_external_approval: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AnalysisReport {
    pub schema_version: u32,
    pub analyzed_at_ms: i64,
    pub snapshot_age_ms: i64,
    pub healthy: bool,
    pub findings: Vec<Finding>,
    pub recommendations: Vec<MovementRecommendation>,
}
