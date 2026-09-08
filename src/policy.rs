use crate::types::{
    AnalysisReport, Finding, MovementRecommendation, PortfolioPolicy, PortfolioSnapshot, Severity,
};
use rust_decimal::Decimal;
use std::collections::{BTreeMap, HashMap};
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum AnalysisError {
    #[error("snapshot and policy schema_version must be 1")]
    SchemaVersion,
    #[error("maximum_snapshot_age_ms must be positive")]
    InvalidMaximumAge,
    #[error("duplicate balance for wallet={wallet_id}, asset={asset_id}")]
    DuplicateBalance { wallet_id: String, asset_id: String },
    #[error("minimum quantity must not be negative")]
    NegativeMinimum,
    #[error("duplicate minimum for wallet={wallet_id}, asset={asset_id}")]
    DuplicateMinimum { wallet_id: String, asset_id: String },
}

pub fn analyze(
    snapshot: &PortfolioSnapshot,
    policy: &PortfolioPolicy,
    analyzed_at_ms: i64,
) -> Result<AnalysisReport, AnalysisError> {
    if snapshot.schema_version != 1 || policy.schema_version != 1 {
        return Err(AnalysisError::SchemaVersion);
    }
    if policy.maximum_snapshot_age_ms <= 0 {
        return Err(AnalysisError::InvalidMaximumAge);
    }
    let snapshot_age_ms = analyzed_at_ms
        .saturating_sub(snapshot.observed_at_ms)
        .max(0);
    let mut findings = Vec::new();
    if snapshot_age_ms > policy.maximum_snapshot_age_ms {
        findings.push(Finding {
            severity: Severity::Critical,
            code: "stale_snapshot".to_string(),
            wallet_id: None,
            asset_id: None,
            detail: format!(
                "snapshot age {} ms exceeds {} ms",
                snapshot_age_ms, policy.maximum_snapshot_age_ms
            ),
        });
    }

    let mut holdings = HashMap::new();
    for balance in &snapshot.balances {
        let key = (balance.wallet_id.clone(), balance.asset_id.clone());
        if holdings.insert(key.clone(), balance.quantity).is_some() {
            return Err(AnalysisError::DuplicateBalance {
                wallet_id: key.0,
                asset_id: key.1,
            });
        }
    }
    let mut minimums = HashMap::new();
    for requirement in &policy.minimum_balances {
        if requirement.minimum_quantity.is_sign_negative() {
            return Err(AnalysisError::NegativeMinimum);
        }
        let key = (requirement.wallet_id.clone(), requirement.asset_id.clone());
        if minimums
            .insert(key.clone(), requirement.minimum_quantity)
            .is_some()
        {
            return Err(AnalysisError::DuplicateMinimum {
                wallet_id: key.0,
                asset_id: key.1,
            });
        }
        let observed = holdings
            .get(&(requirement.wallet_id.clone(), requirement.asset_id.clone()))
            .copied();
        match observed {
            None => findings.push(Finding {
                severity: Severity::Critical,
                code: "missing_balance".to_string(),
                wallet_id: Some(requirement.wallet_id.clone()),
                asset_id: Some(requirement.asset_id.clone()),
                detail: "required wallet/asset balance is absent".to_string(),
            }),
            Some(quantity) if quantity < requirement.minimum_quantity => {
                findings.push(Finding {
                    severity: Severity::Warning,
                    code: "below_minimum".to_string(),
                    wallet_id: Some(requirement.wallet_id.clone()),
                    asset_id: Some(requirement.asset_id.clone()),
                    detail: format!(
                        "observed {} is below minimum {}",
                        quantity, requirement.minimum_quantity
                    ),
                });
            }
            _ => {}
        }
    }

    let recommendations = recommendations(&holdings, &minimums);
    Ok(AnalysisReport {
        schema_version: 1,
        analyzed_at_ms,
        snapshot_age_ms,
        healthy: findings.is_empty(),
        findings,
        recommendations,
    })
}

fn recommendations(
    holdings: &HashMap<(String, String), Decimal>,
    minimums: &HashMap<(String, String), Decimal>,
) -> Vec<MovementRecommendation> {
    let mut working = holdings.clone();
    let mut requirements: Vec<_> = minimums.iter().collect();
    requirements.sort_by(|left, right| left.0.cmp(right.0));
    let mut output = Vec::new();
    for ((receiver, asset), minimum) in requirements {
        let current = working
            .get(&(receiver.clone(), asset.clone()))
            .copied()
            .unwrap_or_default();
        let mut deficit = (*minimum - current).max(Decimal::ZERO);
        if deficit.is_zero() {
            continue;
        }
        let mut donors = BTreeMap::new();
        for ((wallet, holding_asset), quantity) in &working {
            if wallet == receiver || holding_asset != asset {
                continue;
            }
            let donor_minimum = minimums
                .get(&(wallet.clone(), asset.clone()))
                .copied()
                .unwrap_or_default();
            let available = (*quantity - donor_minimum).max(Decimal::ZERO);
            if !available.is_zero() {
                donors.insert(wallet.clone(), available);
            }
        }
        for (donor, available) in donors {
            let quantity = deficit.min(available);
            output.push(MovementRecommendation {
                from_wallet_id: donor.clone(),
                to_wallet_id: receiver.clone(),
                asset_id: asset.clone(),
                quantity,
                reason: "restore configured minimum balance".to_string(),
                executable: false,
                requires_external_approval: true,
            });
            *working.entry((donor, asset.clone())).or_default() -= quantity;
            *working
                .entry((receiver.clone(), asset.clone()))
                .or_default() += quantity;
            deficit -= quantity;
            if deficit.is_zero() {
                break;
            }
        }
    }
    output
}
