//! Deterministic, advisory multi-asset population selection for NDU.
//!
//! This module stays on the authority-free NDU/control plane. It summarizes
//! typed asset populations and computes sparse portfolio recommendations, but
//! it never mutates a route or invokes a model/runtime operation.

use std::collections::{BTreeMap, BTreeSet};

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, Generation, StableId};

const MAX_ASSETS: usize = 4096;
const MAX_POPULATIONS: usize = 64;
const MAX_ACTIVE: usize = 512;
const MAX_ITERATIONS: usize = 64;
const MIN_Q32_RAW: i64 = -(1_i64 << 32);
const MAX_Q32_RAW: i64 = 1_i64 << 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AssetPopulationError {
    EmptyInput,
    TooManyAssets,
    TooManyPopulations,
    InvalidBounds,
    DuplicateAsset,
    GenerationMismatch,
    SnapshotMismatch,
    SummaryMismatch,
    Arithmetic,
    InvalidDamping,
    InvalidTolerance,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetPopulationConfigV1 {
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub generation: Generation,
    pub max_active: usize,
    pub risk_aversion: FixedQ32,
    pub resource_weight: FixedQ32,
    pub load_weight: FixedQ32,
    pub population_risk_weight: FixedQ32,
    pub population_load_weight: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetPopulationObservationV1 {
    pub asset_id: StableId,
    pub population_id: StableId,
    pub generation: Generation,
    pub snapshot_digest: Digest32,
    pub support_digest: Digest32,
    pub expected_utility: FixedQ32,
    pub semantic_risk: FixedQ32,
    pub resource_cost: FixedQ32,
    pub load: FixedQ32,
    pub confidence: FixedQ32,
    pub eligible: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeanFieldPopulationSummaryV1 {
    pub population_id: StableId,
    pub count: usize,
    pub eligible_count: usize,
    pub mean_utility: FixedQ32,
    pub mean_risk: FixedQ32,
    pub mean_resource_cost: FixedQ32,
    pub mean_load: FixedQ32,
    pub mean_confidence: FixedQ32,
    pub maximum_risk: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetPopulationSummaryV1 {
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub generation: Generation,
    pub observation_digest: Digest32,
    pub populations: Vec<MeanFieldPopulationSummaryV1>,
    pub summary_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetPortfolioWeightV1 {
    pub asset_id: StableId,
    pub population_id: StableId,
    pub score: FixedQ32,
    pub weight: FixedQ32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioSelectionDispositionV1 {
    Selected,
    NoEligibleAssets,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioSelectionReceiptV1 {
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub generation: Generation,
    pub summary_digest: Digest32,
    pub disposition: PortfolioSelectionDispositionV1,
    pub weights: Vec<AssetPortfolioWeightV1>,
    pub selection_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeanFieldIterationReceiptV1 {
    pub iteration: usize,
    pub summary_digest: Digest32,
    pub selection_digest: Digest32,
    pub maximum_load_delta: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeanFieldEquilibriumReceiptV1 {
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub generation: Generation,
    pub disposition: PortfolioSelectionDispositionV1,
    pub iterations: Vec<MeanFieldIterationReceiptV1>,
    pub terminal_summary_digest: Digest32,
    pub terminal_selection_digest: Digest32,
    pub terminal_load_delta: FixedQ32,
    pub authority: AuthorityPosture,
}

pub fn summarize_asset_population_v1(
    config: &AssetPopulationConfigV1,
    observations: &[AssetPopulationObservationV1],
) -> Result<AssetPopulationSummaryV1, AssetPopulationError> {
    validate_config(config)?;
    validate_observations(config, observations)?;

    let mut groups: BTreeMap<StableId, Vec<&AssetPopulationObservationV1>> = BTreeMap::new();
    for observation in observations {
        groups
            .entry(observation.population_id.clone())
            .or_default()
            .push(observation);
    }

    let mut populations = Vec::with_capacity(groups.len());
    for (population_id, values) in groups {
        let maximum_risk = values
            .iter()
            .map(|value| value.semantic_risk)
            .max()
            .ok_or(AssetPopulationError::EmptyInput)?;
        populations.push(MeanFieldPopulationSummaryV1 {
            population_id: population_id.clone(),
            count: values.len(),
            eligible_count: values.iter().filter(|value| value.eligible).count(),
            mean_utility: mean(values.iter().map(|value| value.expected_utility))?,
            mean_risk: mean(values.iter().map(|value| value.semantic_risk))?,
            mean_resource_cost: mean(values.iter().map(|value| value.resource_cost))?,
            mean_load: mean(values.iter().map(|value| value.load))?,
            mean_confidence: mean(values.iter().map(|value| value.confidence))?,
            maximum_risk,
        });
    }

    let observation_digest = digest_observations(config, observations);
    let summary_digest = digest_summary(config, observation_digest, &populations);
    Ok(AssetPopulationSummaryV1 {
        objective_digest: config.objective_digest,
        snapshot_digest: config.snapshot_digest,
        generation: config.generation,
        observation_digest,
        populations,
        summary_digest,
    })
}

pub fn select_asset_portfolio_v1(
    config: &AssetPopulationConfigV1,
    observations: &[AssetPopulationObservationV1],
    summary: &AssetPopulationSummaryV1,
) -> Result<PortfolioSelectionReceiptV1, AssetPopulationError> {
    validate_config(config)?;
    validate_observations(config, observations)?;
    if summary.objective_digest != config.objective_digest
        || summary.snapshot_digest != config.snapshot_digest
        || summary.generation != config.generation
        || summary.observation_digest != digest_observations(config, observations)
        || summary.summary_digest
            != digest_summary(config, summary.observation_digest, &summary.populations)
    {
        return Err(AssetPopulationError::SummaryMismatch);
    }

    let by_population: BTreeMap<StableId, &MeanFieldPopulationSummaryV1> = summary
        .populations
        .iter()
        .map(|population| (population.population_id.clone(), population))
        .collect();
    let mut scored: Vec<(&AssetPopulationObservationV1, FixedQ32)> = Vec::new();
    for observation in observations.iter().filter(|value| value.eligible) {
        let population = by_population
            .get(&observation.population_id)
            .ok_or(AssetPopulationError::SummaryMismatch)?;
        let score = weighted_score(config, observation, population)?;
        if score.raw() > 0 {
            scored.push((observation, score));
        }
    }
    scored.sort_by(|left, right| {
        right
            .1
            .raw()
            .cmp(&left.1.raw())
            .then_with(|| left.0.population_id.cmp(&right.0.population_id))
            .then_with(|| left.0.asset_id.cmp(&right.0.asset_id))
    });
    scored.truncate(config.max_active);

    let disposition = if scored.is_empty() {
        PortfolioSelectionDispositionV1::NoEligibleAssets
    } else {
        PortfolioSelectionDispositionV1::Selected
    };
    let total_score = scored.iter().try_fold(FixedQ32::ZERO, |sum, (_, score)| {
        checked_add(sum, *score)
    })?;
    let weights = if total_score == FixedQ32::ZERO {
        Vec::new()
    } else {
        scored
            .iter()
            .map(|(observation, score)| {
                Ok(AssetPortfolioWeightV1 {
                    asset_id: observation.asset_id.clone(),
                    population_id: observation.population_id.clone(),
                    score: *score,
                    weight: checked_div(*score, total_score)?,
                })
            })
            .collect::<Result<Vec<_>, AssetPopulationError>>()?
    };

    Ok(PortfolioSelectionReceiptV1 {
        objective_digest: config.objective_digest,
        snapshot_digest: config.snapshot_digest,
        generation: config.generation,
        summary_digest: summary.summary_digest,
        disposition,
        selection_digest: digest_selection(config, summary.summary_digest, &weights, disposition),
        weights,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn solve_mean_field_equilibrium_v1(
    config: &AssetPopulationConfigV1,
    observations: &[AssetPopulationObservationV1],
    damping: FixedQ32,
    tolerance: FixedQ32,
    max_iterations: usize,
) -> Result<MeanFieldEquilibriumReceiptV1, AssetPopulationError> {
    validate_config(config)?;
    if damping.raw() < 0 || damping.raw() > FixedQ32::ONE.raw() {
        return Err(AssetPopulationError::InvalidDamping);
    }
    if tolerance.raw() < 0 {
        return Err(AssetPopulationError::InvalidTolerance);
    }
    let iterations = max_iterations.min(MAX_ITERATIONS);
    if iterations == 0 {
        return Err(AssetPopulationError::InvalidTolerance);
    }

    let mut summary = summarize_asset_population_v1(config, observations)?;
    let mut selection = select_asset_portfolio_v1(config, observations, &summary)?;
    let mut iteration_receipts = Vec::with_capacity(iterations);
    let mut terminal_delta = FixedQ32::from_raw(i64::MAX);

    for iteration in 0..iterations {
        let selected_loads = selected_population_loads(&selection, observations)?;
        let mut maximum_delta = FixedQ32::ZERO;
        for population in &mut summary.populations {
            let target = selected_loads
                .get(&population.population_id)
                .copied()
                .unwrap_or(FixedQ32::ZERO);
            let difference = checked_sub(target, population.mean_load)?;
            let delta = abs_value(difference);
            if delta.raw() > maximum_delta.raw() {
                maximum_delta = delta;
            }
            population.mean_load = checked_add(
                population.mean_load,
                checked_mul(damping, difference)?,
            )?;
        }
        summary.summary_digest =
            digest_summary(config, summary.observation_digest, &summary.populations);
        selection = select_asset_portfolio_v1(config, observations, &summary)?;
        terminal_delta = maximum_delta;
        iteration_receipts.push(MeanFieldIterationReceiptV1 {
            iteration,
            summary_digest: summary.summary_digest,
            selection_digest: selection.selection_digest,
            maximum_load_delta: maximum_delta,
        });
        if maximum_delta.raw() <= tolerance.raw() {
            break;
        }
    }

    Ok(MeanFieldEquilibriumReceiptV1 {
        objective_digest: config.objective_digest,
        snapshot_digest: config.snapshot_digest,
        generation: config.generation,
        disposition: selection.disposition,
        iterations: iteration_receipts,
        terminal_summary_digest: summary.summary_digest,
        terminal_selection_digest: selection.selection_digest,
        terminal_load_delta: terminal_delta,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_config(config: &AssetPopulationConfigV1) -> Result<(), AssetPopulationError> {
    if config.objective_digest.is_zero()
        || config.snapshot_digest.is_zero()
        || config.max_active == 0
        || config.max_active > MAX_ACTIVE
    {
        return Err(AssetPopulationError::InvalidBounds);
    }
    for value in [
        config.risk_aversion,
        config.resource_weight,
        config.load_weight,
        config.population_risk_weight,
        config.population_load_weight,
    ] {
        if value.raw() < 0 {
            return Err(AssetPopulationError::InvalidBounds);
        }
    }
    Ok(())
}

fn validate_observations(
    config: &AssetPopulationConfigV1,
    observations: &[AssetPopulationObservationV1],
) -> Result<(), AssetPopulationError> {
    if observations.is_empty() {
        return Err(AssetPopulationError::EmptyInput);
    }
    if observations.len() > MAX_ASSETS {
        return Err(AssetPopulationError::TooManyAssets);
    }
    let mut asset_ids = BTreeSet::new();
    let mut population_ids = BTreeSet::new();
    for observation in observations {
        if observation.generation != config.generation {
            return Err(AssetPopulationError::GenerationMismatch);
        }
        if observation.snapshot_digest != config.snapshot_digest {
            return Err(AssetPopulationError::SnapshotMismatch);
        }
        if !asset_ids.insert(observation.asset_id.clone()) {
            return Err(AssetPopulationError::DuplicateAsset);
        }
        population_ids.insert(observation.population_id.clone());
        if observation.support_digest.is_zero()
            || !in_unit_interval(observation.semantic_risk)
            || !in_unit_interval(observation.resource_cost)
            || !in_unit_interval(observation.load)
            || !in_unit_interval(observation.confidence)
            || observation.expected_utility.raw() < MIN_Q32_RAW
            || observation.expected_utility.raw() > MAX_Q32_RAW
        {
            return Err(AssetPopulationError::InvalidBounds);
        }
    }
    if population_ids.len() > MAX_POPULATIONS {
        return Err(AssetPopulationError::TooManyPopulations);
    }
    Ok(())
}

fn weighted_score(
    config: &AssetPopulationConfigV1,
    observation: &AssetPopulationObservationV1,
    population: &MeanFieldPopulationSummaryV1,
) -> Result<FixedQ32, AssetPopulationError> {
    let utility = checked_mul(observation.expected_utility, observation.confidence)?;
    let risk = checked_mul(config.risk_aversion, observation.semantic_risk)?;
    let cost = checked_mul(config.resource_weight, observation.resource_cost)?;
    let load = checked_mul(config.load_weight, observation.load)?;
    let population_risk = checked_mul(config.population_risk_weight, population.mean_risk)?;
    let population_load = checked_mul(config.population_load_weight, population.mean_load)?;
    let penalty = checked_add(
        checked_add(risk, cost)?,
        checked_add(load, checked_add(population_risk, population_load)?)?,
    )?;
    checked_sub(utility, penalty)
}

fn selected_population_loads(
    selection: &PortfolioSelectionReceiptV1,
    observations: &[AssetPopulationObservationV1],
) -> Result<BTreeMap<StableId, FixedQ32>, AssetPopulationError> {
    let lookup: BTreeMap<StableId, &AssetPopulationObservationV1> = observations
        .iter()
        .map(|observation| (observation.asset_id.clone(), observation))
        .collect();
    let mut loads = BTreeMap::new();
    for weight in &selection.weights {
        let observation = lookup
            .get(&weight.asset_id)
            .ok_or(AssetPopulationError::SummaryMismatch)?;
        let contribution = checked_mul(weight.weight, observation.load)?;
        let entry = loads
            .entry(weight.population_id.clone())
            .or_insert(FixedQ32::ZERO);
        *entry = checked_add(*entry, contribution)?;
    }
    Ok(loads)
}

fn mean<I>(values: I) -> Result<FixedQ32, AssetPopulationError>
where
    I: IntoIterator<Item = FixedQ32>,
{
    let values: Vec<FixedQ32> = values.into_iter().collect();
    if values.is_empty() {
        return Err(AssetPopulationError::EmptyInput);
    }
    let sum = values.iter().try_fold(0_i128, |sum, value| {
        sum.checked_add(i128::from(value.raw()))
            .ok_or(AssetPopulationError::Arithmetic)
    })?;
    let divisor = i128::try_from(values.len()).map_err(|_| AssetPopulationError::Arithmetic)?;
    let raw = i64::try_from(sum / divisor).map_err(|_| AssetPopulationError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn in_unit_interval(value: FixedQ32) -> bool {
    value.raw() >= 0 && value.raw() <= FixedQ32::ONE.raw()
}

fn abs_value(value: FixedQ32) -> FixedQ32 {
    FixedQ32::from_raw(value.raw().abs())
}

fn checked_add(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, AssetPopulationError> {
    left.checked_add(right)
        .map_err(|_| AssetPopulationError::Arithmetic)
}

fn checked_sub(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, AssetPopulationError> {
    left.checked_sub(right)
        .map_err(|_| AssetPopulationError::Arithmetic)
}

fn checked_mul(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, AssetPopulationError> {
    left.checked_mul(right)
        .map_err(|_| AssetPopulationError::Arithmetic)
}

fn checked_div(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, AssetPopulationError> {
    left.checked_div(right)
        .map_err(|_| AssetPopulationError::Arithmetic)
}

fn digest_summary(
    config: &AssetPopulationConfigV1,
    observation_digest: Digest32,
    populations: &[MeanFieldPopulationSummaryV1],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta-asset-population-summary-v1\0");
    bytes.extend_from_slice(config.objective_digest.as_array());
    bytes.extend_from_slice(config.snapshot_digest.as_array());
    bytes.extend_from_slice(observation_digest.as_array());
    bytes.extend_from_slice(&config.generation.get().to_le_bytes());
    bytes.extend_from_slice(&(config.max_active as u64).to_le_bytes());
    for value in [
        config.risk_aversion,
        config.resource_weight,
        config.load_weight,
        config.population_risk_weight,
        config.population_load_weight,
    ] {
        bytes.extend_from_slice(&value.raw().to_le_bytes());
    }
    for population in populations {
        bytes.extend_from_slice(population.population_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(&(population.count as u64).to_le_bytes());
        bytes.extend_from_slice(&(population.eligible_count as u64).to_le_bytes());
        for value in [
            population.mean_utility,
            population.mean_risk,
            population.mean_resource_cost,
            population.mean_load,
            population.mean_confidence,
            population.maximum_risk,
        ] {
            bytes.extend_from_slice(&value.raw().to_le_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_observations(
    config: &AssetPopulationConfigV1,
    observations: &[AssetPopulationObservationV1],
) -> Digest32 {
    let mut ordered: Vec<&AssetPopulationObservationV1> = observations.iter().collect();
    ordered.sort_by(|left, right| left.asset_id.cmp(&right.asset_id));
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta-asset-population-observations-v1\0");
    bytes.extend_from_slice(config.snapshot_digest.as_array());
    bytes.extend_from_slice(&config.generation.get().to_le_bytes());
    for observation in ordered {
        bytes.extend_from_slice(observation.asset_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(observation.population_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(observation.snapshot_digest.as_array());
        bytes.extend_from_slice(observation.support_digest.as_array());
        bytes.extend_from_slice(&observation.expected_utility.raw().to_le_bytes());
        bytes.extend_from_slice(&observation.semantic_risk.raw().to_le_bytes());
        bytes.extend_from_slice(&observation.resource_cost.raw().to_le_bytes());
        bytes.extend_from_slice(&observation.load.raw().to_le_bytes());
        bytes.extend_from_slice(&observation.confidence.raw().to_le_bytes());
        bytes.push(if observation.eligible { 1 } else { 0 });
    }
    Digest32::of_bytes(&bytes)
}

fn digest_selection(
    config: &AssetPopulationConfigV1,
    summary_digest: Digest32,
    weights: &[AssetPortfolioWeightV1],
    disposition: PortfolioSelectionDispositionV1,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta-asset-population-selection-v1\0");
    bytes.extend_from_slice(config.objective_digest.as_array());
    bytes.extend_from_slice(config.snapshot_digest.as_array());
    bytes.extend_from_slice(&config.generation.get().to_le_bytes());
    bytes.extend_from_slice(summary_digest.as_array());
    bytes.push(match disposition {
        PortfolioSelectionDispositionV1::Selected => 1,
        PortfolioSelectionDispositionV1::NoEligibleAssets => 0,
    });
    for weight in weights {
        bytes.extend_from_slice(weight.asset_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(weight.population_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(&weight.score.raw().to_le_bytes());
        bytes.extend_from_slice(&weight.weight.raw().to_le_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "asset_population_tests.rs"]
mod tests;
