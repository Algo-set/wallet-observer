use rust_decimal::Decimal;
use std::str::FromStr;
use wallet_observer::observer::build_snapshot;
use wallet_observer::{analyze, BalanceRecord, MinimumBalance, PortfolioPolicy};

fn d(value: &str) -> Decimal {
    Decimal::from_str(value).unwrap()
}

fn balance(wallet: &str, asset: &str, quantity: &str, price: Option<&str>) -> BalanceRecord {
    let quantity = d(quantity);
    let unit_price_usd = price.map(d);
    BalanceRecord {
        wallet_id: wallet.to_string(),
        chain_id: "chain-a".to_string(),
        asset_id: asset.to_string(),
        symbol: asset.to_uppercase(),
        atomic_units: "0".to_string(),
        quantity,
        unit_price_usd,
        value_usd: unit_price_usd.map(|value| value * quantity),
        source: "fixture".to_string(),
    }
}

#[test]
fn aggregates_valued_nav_without_counting_unvalued_assets() {
    let snapshot = build_snapshot(
        1_000,
        vec![
            balance("operating", "usd", "50", Some("1")),
            balance("reserve", "usd", "200", Some("1")),
            balance("reserve", "gas", "3", None),
        ],
    );
    assert_eq!(snapshot.total_valued_nav_usd, d("250"));
    assert_eq!(snapshot.wallet_nav[1].unvalued_assets, vec!["gas"]);
}

#[test]
fn recommends_non_executable_movement_from_surplus() {
    let snapshot = build_snapshot(
        10_000,
        vec![
            balance("operating", "usd", "60", Some("1")),
            balance("reserve", "usd", "300", Some("1")),
        ],
    );
    let policy = PortfolioPolicy {
        schema_version: 1,
        maximum_snapshot_age_ms: 1_000,
        minimum_balances: vec![
            MinimumBalance {
                wallet_id: "operating".to_string(),
                asset_id: "usd".to_string(),
                minimum_quantity: d("100"),
            },
            MinimumBalance {
                wallet_id: "reserve".to_string(),
                asset_id: "usd".to_string(),
                minimum_quantity: d("200"),
            },
        ],
    };
    let report = analyze(&snapshot, &policy, 10_100).unwrap();
    assert!(!report.healthy);
    assert_eq!(report.recommendations.len(), 1);
    let recommendation = &report.recommendations[0];
    assert_eq!(recommendation.quantity, d("40"));
    assert!(!recommendation.executable);
    assert!(recommendation.requires_external_approval);
}

#[test]
fn stale_snapshot_is_critical() {
    let snapshot = build_snapshot(1_000, vec![]);
    let policy = PortfolioPolicy {
        schema_version: 1,
        maximum_snapshot_age_ms: 100,
        minimum_balances: vec![],
    };
    let report = analyze(&snapshot, &policy, 1_101).unwrap();
    assert!(!report.healthy);
    assert_eq!(report.findings[0].code, "stale_snapshot");
}

#[test]
fn rejects_ambiguous_duplicate_minimums() {
    let snapshot = build_snapshot(1_000, vec![balance("operating", "usd", "60", Some("1"))]);
    let minimum = MinimumBalance {
        wallet_id: "operating".to_string(),
        asset_id: "usd".to_string(),
        minimum_quantity: d("50"),
    };
    let policy = PortfolioPolicy {
        schema_version: 1,
        maximum_snapshot_age_ms: 100,
        minimum_balances: vec![minimum.clone(), minimum],
    };

    assert!(analyze(&snapshot, &policy, 1_000).is_err());
}
