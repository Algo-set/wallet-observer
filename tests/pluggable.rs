use async_trait::async_trait;
use rust_decimal::Decimal;
use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;
use wallet_observer::{
    observe_with_providers, BalanceProvider, BalanceRequest, ProviderBalance, ProviderFailure,
    ValuationProvider,
};

struct FixtureBalances;

#[async_trait]
impl BalanceProvider for FixtureBalances {
    async fn balance(&self, request: &BalanceRequest) -> Result<ProviderBalance, ProviderFailure> {
        assert_eq!(request.account_reference, "opaque-account-reference");
        assert_eq!(
            request.asset_reference.as_deref(),
            Some("opaque-asset-reference")
        );
        Ok(ProviderBalance {
            atomic_units: 12_345,
            quantity: Decimal::from_str("123.45").unwrap(),
        })
    }
}

struct FixtureValuation;

#[async_trait]
impl ValuationProvider for FixtureValuation {
    async fn unit_price_usd(
        &self,
        request: &BalanceRequest,
    ) -> Result<Option<Decimal>, ProviderFailure> {
        assert_eq!(request.provider_id, "custom-provider");
        Ok(Some(Decimal::from_str("2.50").unwrap()))
    }
}

struct FailingBalances;

#[async_trait]
impl BalanceProvider for FailingBalances {
    async fn balance(&self, _request: &BalanceRequest) -> Result<ProviderBalance, ProviderFailure> {
        Err(ProviderFailure::new("opaque-account-reference"))
    }
}

struct NegativeBalances;

#[async_trait]
impl BalanceProvider for NegativeBalances {
    async fn balance(&self, _request: &BalanceRequest) -> Result<ProviderBalance, ProviderFailure> {
        Ok(ProviderBalance {
            atomic_units: 0,
            quantity: Decimal::new(-1, 0),
        })
    }
}

struct NegativeValuation;

#[async_trait]
impl ValuationProvider for NegativeValuation {
    async fn unit_price_usd(
        &self,
        _request: &BalanceRequest,
    ) -> Result<Option<Decimal>, ProviderFailure> {
        Ok(Some(Decimal::new(-1, 0)))
    }
}

fn request() -> BalanceRequest {
    BalanceRequest {
        provider_id: "custom-provider".to_string(),
        wallet_id: "treasury".to_string(),
        chain_id: "arbitrary-environment".to_string(),
        asset_id: "inventory-unit".to_string(),
        symbol: "UNIT".to_string(),
        account_reference: "opaque-account-reference".to_string(),
        asset_reference: Some("opaque-asset-reference".to_string()),
        decimals: 2,
    }
}

#[tokio::test]
async fn accepts_arbitrary_providers_without_persisting_opaque_references() {
    let requests = vec![request()];
    let providers: HashMap<String, Arc<dyn BalanceProvider>> = HashMap::from([(
        "custom-provider".to_string(),
        Arc::new(FixtureBalances) as Arc<dyn BalanceProvider>,
    )]);

    let snapshot = observe_with_providers(&requests, &providers, &FixtureValuation, 1_000)
        .await
        .unwrap();

    assert_eq!(
        snapshot.total_valued_nav_usd,
        Decimal::from_str("308.6250").unwrap()
    );
    let serialized = serde_json::to_string(&snapshot).unwrap();
    assert!(!serialized.contains("opaque-account-reference"));
    assert!(!serialized.contains("opaque-asset-reference"));
    assert!(serialized.contains("custom-provider"));
}

#[tokio::test]
async fn reduces_provider_errors_to_a_closed_safe_code() {
    let requests = vec![request()];
    let providers: HashMap<String, Arc<dyn BalanceProvider>> = HashMap::from([(
        "custom-provider".to_string(),
        Arc::new(FailingBalances) as Arc<dyn BalanceProvider>,
    )]);

    let error = observe_with_providers(&requests, &providers, &FixtureValuation, 1_000)
        .await
        .unwrap_err()
        .to_string();

    assert!(error.contains("provider_failure"));
    assert!(!error.contains("opaque-account-reference"));
}

#[tokio::test]
async fn rejects_negative_provider_quantities() {
    let requests = vec![request()];
    let providers: HashMap<String, Arc<dyn BalanceProvider>> = HashMap::from([(
        "custom-provider".to_string(),
        Arc::new(NegativeBalances) as Arc<dyn BalanceProvider>,
    )]);

    let error = observe_with_providers(&requests, &providers, &FixtureValuation, 1_000)
        .await
        .unwrap_err()
        .to_string();

    assert!(error.contains("invalid_provider_quantity"));
}

#[tokio::test]
async fn rejects_negative_provider_valuations() {
    let requests = vec![request()];
    let providers: HashMap<String, Arc<dyn BalanceProvider>> = HashMap::from([(
        "custom-provider".to_string(),
        Arc::new(FixtureBalances) as Arc<dyn BalanceProvider>,
    )]);

    let error = observe_with_providers(&requests, &providers, &NegativeValuation, 1_000)
        .await
        .unwrap_err()
        .to_string();

    assert!(error.contains("invalid_valuation_price"));
}
