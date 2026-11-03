use super::*;
use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn q32(value: f64) -> FixedQ32 {
    FixedQ32::from_raw((value * (1_i64 << 32) as f64).round() as i64)
}

fn config() -> AssetPopulationConfigV1 {
    AssetPopulationConfigV1 {
        objective_digest: Digest32::of_bytes(b"objective"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        generation: generation(7),
        max_active: 2,
        risk_aversion: q32(0.25),
        resource_weight: q32(0.10),
        load_weight: q32(0.10),
        population_risk_weight: q32(0.05),
        population_load_weight: q32(0.05),
    }
}

fn observation(
    asset: &str,
    population: &str,
    utility: f64,
    risk: f64,
    load: f64,
    eligible: bool,
) -> AssetPopulationObservationV1 {
    let config = config();
    AssetPopulationObservationV1 {
        asset_id: id(asset),
        population_id: id(population),
        generation: config.generation,
        snapshot_digest: config.snapshot_digest,
        support_digest: Digest32::of_bytes(asset.as_bytes()),
        expected_utility: q32(utility),
        semantic_risk: q32(risk),
        resource_cost: q32(0.1),
        load: q32(load),
        confidence: q32(0.9),
        eligible,
    }
}

#[test]
fn summary_and_selection_are_order_independent_and_sparse() {
    let config = config();
    let first = vec![
        observation("asset-a", "text", 0.9, 0.1, 0.1, true),
        observation("asset-b", "text", 0.7, 0.2, 0.2, true),
        observation("asset-c", "vision", 0.8, 0.6, 0.3, true),
    ];
    let mut reordered = first.clone();
    reordered.reverse();

    let summary = summarize_asset_population_v1(&config, &first).expect("summary");
    let reordered_summary = summarize_asset_population_v1(&config, &reordered).expect("summary");
    assert_eq!(summary, reordered_summary);

    let receipt = select_asset_portfolio_v1(&config, &first, &summary).expect("selection");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(receipt.disposition, PortfolioSelectionDispositionV1::Selected);
    assert!(receipt.weights.len() <= config.max_active);
    let total_raw: i128 = receipt
        .weights
        .iter()
        .map(|weight| i128::from(weight.weight.raw()))
        .sum();
    assert!((total_raw - i128::from(FixedQ32::ONE.raw())).abs() <= 2);
}

#[test]
fn rejects_duplicate_stale_and_zero_support_assets() {
    let config = config();
    let mut values = vec![observation("asset-a", "text", 0.9, 0.1, 0.1, true)];
    values.push(observation("asset-a", "vision", 0.8, 0.2, 0.2, true));
    assert_eq!(
        summarize_asset_population_v1(&config, &values),
        Err(AssetPopulationError::DuplicateAsset)
    );

    let mut stale = observation("asset-b", "text", 0.9, 0.1, 0.1, true);
    stale.generation = generation(8);
    assert_eq!(
        summarize_asset_population_v1(&config, &[stale]),
        Err(AssetPopulationError::GenerationMismatch)
    );

    let mut zero_support = observation("asset-c", "text", 0.9, 0.1, 0.1, true);
    zero_support.support_digest = Digest32::ZERO;
    assert_eq!(
        summarize_asset_population_v1(&config, &[zero_support]),
        Err(AssetPopulationError::InvalidBounds)
    );
}

#[test]
fn all_negative_or_ineligible_returns_empty_advisory_selection() {
    let config = config();
    let values = vec![observation("asset-a", "text", -0.8, 1.0, 1.0, true)];
    let summary = summarize_asset_population_v1(&config, &values).expect("summary");
    let receipt = select_asset_portfolio_v1(&config, &values, &summary).expect("selection");
    assert_eq!(receipt.disposition, PortfolioSelectionDispositionV1::NoEligibleAssets);
    assert!(receipt.weights.is_empty());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn equilibrium_is_bounded_and_authority_free() {
    let config = config();
    let values = vec![
        observation("asset-a", "text", 0.9, 0.1, 0.1, true),
        observation("asset-b", "vision", 0.8, 0.2, 0.2, true),
    ];
    let receipt = solve_mean_field_equilibrium_v1(
        &config,
        &values,
        q32(0.5),
        q32(0.001),
        8,
    )
    .expect("equilibrium");
    assert!(!receipt.iterations.is_empty());
    assert!(receipt.iterations.len() <= 8);
    assert!(!receipt.terminal_summary_digest.is_zero());
    assert!(!receipt.terminal_selection_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}
