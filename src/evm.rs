use reqwest::Client;
use rust_decimal::Decimal;
use serde_json::{json, Value};
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use thiserror::Error;

const ALLOWED_METHODS: [&str; 3] = ["eth_chainId", "eth_getBalance", "eth_call"];

#[derive(Debug, Error)]
pub enum RpcError {
    #[error("invalid EVM address")]
    InvalidAddress,
    #[error("invalid RPC URL")]
    InvalidUrl,
    #[error("network: {0}")]
    Network(#[from] reqwest::Error),
    #[error("RPC returned an error: {0}")]
    Response(String),
    #[error("invalid hexadecimal quantity: {0}")]
    InvalidQuantity(String),
    #[error("token decimals must not exceed 28")]
    UnsupportedDecimals,
    #[error("RPC method is not on the read-only allowlist")]
    MethodNotAllowed,
}

pub struct EvmRpcClient {
    endpoint: String,
    client: Client,
    request_id: AtomicU64,
}

impl EvmRpcClient {
    pub fn new(endpoint: String) -> Result<Self, RpcError> {
        let parsed = reqwest::Url::parse(&endpoint).map_err(|_| RpcError::InvalidUrl)?;
        if !matches!(parsed.scheme(), "http" | "https") {
            return Err(RpcError::InvalidUrl);
        }
        Ok(Self {
            endpoint,
            client: Client::builder()
                .timeout(Duration::from_secs(10))
                .user_agent("wallet-observer/0.1")
                .build()?,
            request_id: AtomicU64::new(1),
        })
    }

    pub async fn chain_id(&self) -> Result<u64, RpcError> {
        let value = self.call("eth_chainId", json!([])).await?;
        let raw = value
            .as_str()
            .ok_or_else(|| RpcError::Response(value.to_string()))?;
        u64::from_str_radix(raw.trim_start_matches("0x"), 16)
            .map_err(|_| RpcError::InvalidQuantity(raw.to_string()))
    }

    pub async fn native_balance(&self, address: &str) -> Result<u128, RpcError> {
        let address = normalize_address(address)?;
        let value = self
            .call("eth_getBalance", json!([address, "latest"]))
            .await?;
        parse_hex_quantity(&value)
    }

    pub async fn token_balance(&self, token: &str, owner: &str) -> Result<u128, RpcError> {
        let token = normalize_address(token)?;
        let data = encode_balance_query(owner)?;
        let value = self
            .call("eth_call", json!([{"to": token, "data": data}, "latest"]))
            .await?;
        parse_hex_quantity(&value)
    }

    async fn call(&self, method: &str, params: Value) -> Result<Value, RpcError> {
        if !ALLOWED_METHODS.contains(&method) {
            return Err(RpcError::MethodNotAllowed);
        }
        let id = self.request_id.fetch_add(1, Ordering::Relaxed);
        let response: Value = self
            .client
            .post(&self.endpoint)
            .json(&json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        if let Some(error) = response.get("error") {
            return Err(RpcError::Response(error.to_string()));
        }
        response
            .get("result")
            .cloned()
            .ok_or_else(|| RpcError::Response("missing result".to_string()))
    }
}

pub fn normalize_address(value: &str) -> Result<String, RpcError> {
    let body = value.strip_prefix("0x").ok_or(RpcError::InvalidAddress)?;
    if body.len() != 40 || !body.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(RpcError::InvalidAddress);
    }
    Ok(format!("0x{}", body.to_ascii_lowercase()))
}

pub fn encode_balance_query(owner: &str) -> Result<String, RpcError> {
    let owner = normalize_address(owner)?;
    Ok(format!("0x70a08231{:0>64}", owner.trim_start_matches("0x")))
}

pub fn quantity_from_atomic(value: u128, decimals: u32) -> Result<Decimal, RpcError> {
    if decimals > 28 {
        return Err(RpcError::UnsupportedDecimals);
    }
    let digits = value.to_string();
    let rendered = if decimals == 0 {
        digits
    } else if digits.len() <= decimals as usize {
        format!("0.{:0>width$}", digits, width = decimals as usize)
    } else {
        let split = digits.len() - decimals as usize;
        format!("{}.{}", &digits[..split], &digits[split..])
    };
    Decimal::from_str(&rendered).map_err(|_| RpcError::InvalidQuantity(rendered))
}

fn parse_hex_quantity(value: &Value) -> Result<u128, RpcError> {
    let raw = value
        .as_str()
        .ok_or_else(|| RpcError::InvalidQuantity(value.to_string()))?;
    u128::from_str_radix(raw.trim_start_matches("0x"), 16)
        .map_err(|_| RpcError::InvalidQuantity(raw.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_and_encodes_balance_query() {
        let address = format!("0x{}", "12".repeat(20));
        let encoded = encode_balance_query(&address).unwrap();
        assert_eq!(encoded.len(), 74);
        assert!(encoded.starts_with("0x70a08231"));
        assert!(encoded.ends_with(&"12".repeat(20)));
    }

    #[test]
    fn formats_atomic_quantity_exactly() {
        assert_eq!(
            quantity_from_atomic(1_234_500, 6).unwrap().to_string(),
            "1.234500"
        );
        assert_eq!(quantity_from_atomic(42, 0).unwrap().to_string(), "42");
    }
}
