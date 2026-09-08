//! Offline JSON fixture adapter for Rust/Python portfolio and policy parity.
use serde::Deserialize;
use std::io::{self, Read};
use wallet_observer::{analyze, observer::build_snapshot, PortfolioPolicy, PortfolioSnapshot};

#[derive(Deserialize)]
struct Case {
    snapshot: PortfolioSnapshot,
    policy: PortfolioPolicy,
    analyzed_at_ms: i64,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let cases: Vec<Case> = serde_json::from_str(&input)?;
    let mut results = Vec::new();
    for case in cases {
        let snapshot = build_snapshot(case.snapshot.observed_at_ms, case.snapshot.balances);
        let report = analyze(&snapshot, &case.policy, case.analyzed_at_ms)?;
        results.push(serde_json::json!({"snapshot": snapshot, "report": report}));
    }
    println!("{}", serde_json::to_string(&results)?);
    Ok(())
}
