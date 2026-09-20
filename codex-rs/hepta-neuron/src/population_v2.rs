//! Versioned multi-population Q24 mechanism for the readiness target.
//!
//! V1 SparseConfig remains replay-compatible. This V2 profile separates
//! temporal and activation dimensions and performs competition inside each
//! registered population before a global bounded competition. It is a pure
//! mechanism: model selection, persistence, calibration and authority remain
//! outside this module.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::InhibitoryEdge;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const ELIGIBILITY_L1: i64 = 4 * Q;
const MAX_PROJECTION_EDGES: usize = 8_192;
const MAX_POPULATIONS: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct TemporalProjectionEdgeV2 {
    pub source_temporal: usize,
    pub target_activation: usize,
    pub weight_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ActivationPopulationV2 {
    pub start: usize,
    pub len: usize,
    pub top_k: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PopulationSparseConfigV2 {
    pub model_digest: Digest32,
    pub normalization_digest: Digest32,
    pub generation: Generation,
    pub temporal_width: usize,
    pub activation_width: usize,
    pub global_top_k: usize,
    pub temporal_decay_q24: i64,
    pub projection: Vec<TemporalProjectionEdgeV2>,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<InhibitoryEdge>,
    pub populations: Vec<ActivationPopulationV2>,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PopulationSparseTickV2 {
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_digest: Digest32,
    pub body_digest: Digest32,
    pub input_digest: Digest32,
    pub sequence: u64,
    pub monotonic_micros: u64,
    pub temporal_drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PopulationSparseCheckpointV2 {
    config: Digest32,
    scope: Digest32,
    objective: Digest32,
    body: Digest32,
    sequence: u64,
    monotonic_micros: u64,
    predecessor: Digest32,
    input: Digest32,
    temporal: Vec<i64>,
    activation: Vec<i64>,
    activity: Vec<i64>,
    threshold: Vec<i64>,
    eligibility: Vec<i64>,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PopulationSparseSignalReceiptV2 {
    pub config_digest: Digest32,
    pub input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_q24: Vec<i64>,
    pub population_candidate_counts: Vec<u32>,
    pub active_fraction_ppm: u32,
    pub prediction_error_q24: i64,
    pub projection_count: u32,
    pub requires_calibration: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PopulationSparseError {
    InvalidConfig,
    InvalidInput,
    InvalidCheckpoint,
    ScopeDrift,
    ConfigDrift,
    Sequence,
    Clock,
    Arithmetic,
}

impl fmt::Display for PopulationSparseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PopulationSparseError {}

impl PopulationSparseConfigV2 {
    pub fn digest(&self) -> Result<Digest32, PopulationSparseError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.population-sparse-config.q24.v2".to_vec();
        bytes.extend_from_slice(self.model_digest.as_array());
        bytes.extend_from_slice(self.normalization_digest.as_array());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for value in [
            self.temporal_width,
            self.activation_width,
            self.global_top_k,
        ] {
            bytes.extend_from_slice(
                &u64::try_from(value)
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
        }
        for value in [
            self.temporal_decay_q24,
            self.inhibition_gain_q24,
            self.activity_decay_q24,
            self.target_activity_q24,
            self.threshold_rate_q24,
            self.threshold_min_q24,
            self.threshold_max_q24,
            self.eligibility_decay_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        let mut projections = self.projection.clone();
        projections.sort();
        for edge in projections {
            bytes.extend_from_slice(
                &u64::try_from(edge.source_temporal)
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
            bytes.extend_from_slice(
                &u64::try_from(edge.target_activation)
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
            bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
        }
        let mut inhibition = self.inhibition.clone();
        inhibition.sort();
        for edge in inhibition {
            bytes.extend_from_slice(
                &u64::try_from(edge.source)
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
            bytes.extend_from_slice(
                &u64::try_from(edge.target)
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
            bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
        }
        for population in &self.populations {
            for value in [population.start, population.len, population.top_k] {
                bytes.extend_from_slice(
                    &u64::try_from(value)
                        .map_err(|_| PopulationSparseError::Arithmetic)?
                        .to_be_bytes(),
                );
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), PopulationSparseError> {
        if self.model_digest.is_zero()
            || self.normalization_digest.is_zero()
            || !(1..=256).contains(&self.temporal_width)
            || !(5..=512).contains(&self.activation_width)
            || self.global_top_k == 0
            || self.global_top_k > self.activation_width / 5
            || self.global_top_k * 100 < self.activation_width
            || self.projection.is_empty()
            || self.projection.len() > MAX_PROJECTION_EDGES
            || self.inhibition.len() > 4_096
            || self.populations.is_empty()
            || self.populations.len() > MAX_POPULATIONS
            || self.threshold_min_q24 < -H
            || self.threshold_max_q24 > H
            || self.threshold_min_q24 > self.threshold_max_q24
        {
            return Err(PopulationSparseError::InvalidConfig);
        }
        for value in [
            self.temporal_decay_q24,
            self.inhibition_gain_q24,
            self.activity_decay_q24,
            self.target_activity_q24,
            self.threshold_rate_q24,
            self.eligibility_decay_q24,
        ] {
            if !(0..=Q).contains(&value) {
                return Err(PopulationSparseError::InvalidConfig);
            }
        }

        let mut projection_seen = BTreeSet::new();
        let mut target_has_projection = vec![false; self.activation_width];
        for edge in &self.projection {
            if edge.source_temporal >= self.temporal_width
                || edge.target_activation >= self.activation_width
                || !(-Q..=Q).contains(&edge.weight_q24)
                || !projection_seen.insert((edge.target_activation, edge.source_temporal))
            {
                return Err(PopulationSparseError::InvalidConfig);
            }
            target_has_projection[edge.target_activation] = true;
        }
        if target_has_projection.iter().any(|present| !present) {
            return Err(PopulationSparseError::InvalidConfig);
        }

        let mut inhibition_seen = BTreeSet::new();
        let mut row_sums = vec![0_i64; self.activation_width];
        for edge in &self.inhibition {
            if edge.source >= self.activation_width
                || edge.target >= self.activation_width
                || edge.source == edge.target
                || !(0..=Q).contains(&edge.weight_q24)
                || !inhibition_seen.insert((edge.target, edge.source))
            {
                return Err(PopulationSparseError::InvalidConfig);
            }
            row_sums[edge.target] = row_sums[edge.target]
                .checked_add(edge.weight_q24)
                .ok_or(PopulationSparseError::Arithmetic)?;
            if row_sums[edge.target] > Q {
                return Err(PopulationSparseError::InvalidConfig);
            }
        }

        let mut next_start = 0_usize;
        let mut population_budget = 0_usize;
        for population in &self.populations {
            if population.start != next_start
                || population.len == 0
                || population.top_k == 0
                || population.top_k > population.len
            {
                return Err(PopulationSparseError::InvalidConfig);
            }
            next_start = population
                .start
                .checked_add(population.len)
                .ok_or(PopulationSparseError::Arithmetic)?;
            if next_start > self.activation_width {
                return Err(PopulationSparseError::InvalidConfig);
            }
            population_budget = population_budget
                .checked_add(population.top_k)
                .ok_or(PopulationSparseError::Arithmetic)?;
        }
        if next_start != self.activation_width || self.global_top_k > population_budget {
            return Err(PopulationSparseError::InvalidConfig);
        }
        Ok(())
    }
}

impl PopulationSparseCheckpointV2 {
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn sequence(&self) -> u64 {
        self.sequence
    }

    pub fn temporal_q24(&self) -> &[i64] {
        &self.temporal
    }

    pub fn activation_q24(&self) -> &[i64] {
        &self.activation
    }

    pub fn thresholds_q24(&self) -> &[i64] {
        &self.threshold
    }

    pub fn eligibility_q24(&self) -> &[i64] {
        &self.eligibility
    }

    fn calculate_digest(&self) -> Result<Digest32, PopulationSparseError> {
        let mut bytes = b"hepta.neuron.population-sparse-checkpoint.q24.v2".to_vec();
        for digest in [
            self.config,
            self.scope,
            self.objective,
            self.body,
            self.predecessor,
            self.input,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.monotonic_micros.to_be_bytes());
        for values in [
            &self.temporal,
            &self.activation,
            &self.activity,
            &self.threshold,
            &self.eligibility,
        ] {
            bytes.extend_from_slice(
                &u64::try_from(values.len())
                    .map_err(|_| PopulationSparseError::Arithmetic)?
                    .to_be_bytes(),
            );
            for value in values {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn population_sparse_tick_v2(
    config: &PopulationSparseConfigV2,
    input: &PopulationSparseTickV2,
    previous: Option<&PopulationSparseCheckpointV2>,
) -> Result<(PopulationSparseCheckpointV2, PopulationSparseSignalReceiptV2), PopulationSparseError> {
    let config_digest = config.digest()?;
    validate_input(config, input)?;
    let before = previous.map_or(Digest32::ZERO, PopulationSparseCheckpointV2::digest);
    if let Some(prior) = previous {
        if prior.calculate_digest()? != prior.digest {
            return Err(PopulationSparseError::InvalidCheckpoint);
        }
        if prior.config != config_digest {
            return Err(PopulationSparseError::ConfigDrift);
        }
        if prior.scope != input.scope_digest
            || prior.objective != input.objective_digest
            || prior.body != input.body_digest
        {
            return Err(PopulationSparseError::ScopeDrift);
        }
        if prior.sequence.checked_add(1) != Some(input.sequence) {
            return Err(PopulationSparseError::Sequence);
        }
        if input.monotonic_micros <= prior.monotonic_micros {
            return Err(PopulationSparseError::Clock);
        }
    } else if input.sequence != 1 {
        return Err(PopulationSparseError::Sequence);
    } else if input.monotonic_micros == 0 {
        return Err(PopulationSparseError::Clock);
    }

    let mut binding = Vec::new();
    for digest in [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ] {
        binding.extend_from_slice(digest.as_array());
    }
    for value in input
        .temporal_drive_q24
        .iter()
        .chain(&input.prediction_q24)
    {
        binding.extend_from_slice(&value.to_be_bytes());
    }

    let mut next = PopulationSparseCheckpointV2 {
        config: config_digest,
        scope: input.scope_digest,
        objective: input.objective_digest,
        body: input.body_digest,
        sequence: input.sequence,
        monotonic_micros: input.monotonic_micros,
        predecessor: before,
        input: Digest32::of_bytes(&binding),
        temporal: vec![0; config.temporal_width],
        activation: vec![0; config.activation_width],
        activity: vec![0; config.activation_width],
        threshold: vec![0; config.activation_width],
        eligibility: vec![0; config.activation_width],
        digest: Digest32::ZERO,
    };

    let mut projections = 0_u32;
    for (index, drive) in input.temporal_drive_q24.iter().enumerate() {
        let old = previous.map_or(0, |value| value.temporal[index]);
        let raw = mul(config.temporal_decay_q24, old)
            .checked_add(*drive)
            .ok_or(PopulationSparseError::Arithmetic)?;
        next.temporal[index] = raw.clamp(-H, H);
        projections = projections
            .checked_add(u32::from(raw != next.temporal[index]))
            .ok_or(PopulationSparseError::Arithmetic)?;
    }

    let mut projected = vec![0_i64; config.activation_width];
    for edge in &config.projection {
        projected[edge.target_activation] = projected[edge.target_activation]
            .checked_add(mul(
                edge.weight_q24,
                next.temporal[edge.source_temporal],
            ))
            .ok_or(PopulationSparseError::Arithmetic)?;
    }
    for value in &mut projected {
        let clamped = (*value).clamp(-H, H);
        projections = projections
            .checked_add(u32::from(clamped != *value))
            .ok_or(PopulationSparseError::Arithmetic)?;
        *value = clamped;
    }

    let mut inhibition = vec![0_i64; config.activation_width];
    if let Some(prior) = previous {
        for edge in &config.inhibition {
            inhibition[edge.target] = inhibition[edge.target]
                .checked_add(mul(edge.weight_q24, prior.activation[edge.source]))
                .ok_or(PopulationSparseError::Arithmetic)?;
        }
    }

    let mut scores = vec![0_i64; config.activation_width];
    for index in 0..config.activation_width {
        next.threshold[index] = previous.map_or(
            0_i64.clamp(config.threshold_min_q24, config.threshold_max_q24),
            |value| value.threshold[index],
        );
        scores[index] = projected[index]
            .checked_sub(mul(config.inhibition_gain_q24, inhibition[index]))
            .and_then(|value| value.checked_sub(next.threshold[index]))
            .ok_or(PopulationSparseError::Arithmetic)?;
    }

    let mut population_candidates = Vec::new();
    let mut population_candidate_counts = Vec::with_capacity(config.populations.len());
    for population in &config.populations {
        let end = population
            .start
            .checked_add(population.len)
            .ok_or(PopulationSparseError::Arithmetic)?;
        let mut local = (population.start..end)
            .filter_map(|index| {
                let score = scores[index];
                (score > 0).then_some((index, score))
            })
            .collect::<Vec<_>>();
        local.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
        let selected = local.into_iter().take(population.top_k).collect::<Vec<_>>();
        population_candidate_counts.push(
            u32::try_from(selected.len()).map_err(|_| PopulationSparseError::Arithmetic)?,
        );
        population_candidates.extend(selected);
    }
    population_candidates
        .sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
    for (index, score) in population_candidates.into_iter().take(config.global_top_k) {
        next.activation[index] = score.min(H);
        projections = projections
            .checked_add(u32::from(score > H))
            .ok_or(PopulationSparseError::Arithmetic)?;
    }

    for index in 0..config.activation_width {
        let active = if next.activation[index] > 0 { Q } else { 0 };
        let old_rate = previous.map_or(0, |value| value.activity[index]);
        next.activity[index] = mul(config.activity_decay_q24, old_rate)
            .checked_add(mul(Q - config.activity_decay_q24, active))
            .ok_or(PopulationSparseError::Arithmetic)?;
        let raw_threshold = next.threshold[index]
            .checked_add(mul(
                config.threshold_rate_q24,
                next.activity[index] - config.target_activity_q24,
            ))
            .ok_or(PopulationSparseError::Arithmetic)?;
        next.threshold[index] =
            raw_threshold.clamp(config.threshold_min_q24, config.threshold_max_q24);
        projections = projections
            .checked_add(u32::from(raw_threshold != next.threshold[index]))
            .ok_or(PopulationSparseError::Arithmetic)?;
        let old_eligibility = previous.map_or(0, |value| value.eligibility[index]);
        next.eligibility[index] = mul(config.eligibility_decay_q24, old_eligibility)
            .checked_add(mul(projected[index], next.activation[index]))
            .ok_or(PopulationSparseError::Arithmetic)?;
    }
    let eligibility_norm = next
        .eligibility
        .iter()
        .try_fold(0_i64, |sum, value| sum.checked_add(value.abs()))
        .ok_or(PopulationSparseError::Arithmetic)?;
    if eligibility_norm > ELIGIBILITY_L1 {
        for value in &mut next.eligibility {
            *value = (i128::from(*value) * i128::from(ELIGIBILITY_L1)
                / i128::from(eligibility_norm)) as i64;
        }
        projections = projections
            .checked_add(1)
            .ok_or(PopulationSparseError::Arithmetic)?;
    }

    next.digest = next.calculate_digest()?;
    let active_count = next.activation.iter().filter(|value| **value > 0).count();
    let numerator = active_count
        .checked_mul(1_000_000)
        .ok_or(PopulationSparseError::Arithmetic)?;
    let active_fraction_ppm = u32::try_from(numerator / config.activation_width)
        .map_err(|_| PopulationSparseError::Arithmetic)?;
    let prediction_error_q24 = next
        .activation
        .iter()
        .zip(&input.prediction_q24)
        .map(|(observed, predicted)| (observed - predicted).abs())
        .max()
        .unwrap_or(0);

    let receipt = PopulationSparseSignalReceiptV2 {
        config_digest,
        input_digest: next.input,
        checkpoint_before: before,
        checkpoint_after: next.digest,
        activation_q24: next.activation.clone(),
        population_candidate_counts,
        active_fraction_ppm,
        prediction_error_q24,
        projection_count: projections,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((next, receipt))
}

fn validate_input(
    config: &PopulationSparseConfigV2,
    input: &PopulationSparseTickV2,
) -> Result<(), PopulationSparseError> {
    if [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ]
    .iter()
    .any(Digest32::is_zero)
        || input.temporal_drive_q24.len() != config.temporal_width
        || input.prediction_q24.len() != config.activation_width
        || input
            .temporal_drive_q24
            .iter()
            .chain(&input.prediction_q24)
            .any(|value| !(-H..=H).contains(value))
    {
        return Err(PopulationSparseError::InvalidInput);
    }
    Ok(())
}

fn mul(left: i64, right: i64) -> i64 {
    let product = i128::from(left) * i128::from(right);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q);
    let remainder = magnitude % i128::from(Q);
    let round_up =
        remainder * 2 > i128::from(Q) || (remainder * 2 == i128::from(Q) && quotient % 2 != 0);
    ((quotient + i128::from(round_up)) * product.signum()) as i64
}

#[cfg(test)]
#[path = "population_v2_tests.rs"]
mod tests;
