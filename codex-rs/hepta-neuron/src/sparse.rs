//! Pure Q24 neural mechanism kernel. No model execution or persistence authority.
//! The host supplies frozen-head drives and owns atomic checkpoint publication.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const ELIGIBILITY_L1: i64 = 4 * Q;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct InhibitoryEdge {
    pub source: usize,
    pub target: usize,
    pub weight_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SparseConfig {
    pub model_digest: Digest32,
    pub normalization_digest: Digest32,
    pub generation: Generation,
    pub width: usize,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<InhibitoryEdge>,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SparseTick {
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_digest: Digest32,
    pub body_digest: Digest32,
    pub input_digest: Digest32,
    pub sequence: u64,
    pub monotonic_micros: u64,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SparseCheckpoint {
    config: Digest32,
    scope: Digest32,
    objective: Digest32,
    // Private replay context. The persisted tick and `input` digest already bind
    // these bytes, so retaining them here does not change journal wire encoding.
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
pub struct SparseSignalReceipt {
    pub config_digest: Digest32,
    pub input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_q24: Vec<i64>,
    pub active_fraction_ppm: u32,
    pub prediction_error_q24: i64,
    pub projection_count: u32,
    /// This mechanism has no calibrated confidence/OOD head. Always slow-path.
    pub requires_calibration: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SparseError {
    InvalidConfig,
    InvalidInput,
    InvalidCheckpoint,
    ScopeDrift,
    ConfigDrift,
    Sequence,
    Clock,
}

impl fmt::Display for SparseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for SparseError {}

impl SparseConfig {
    /// Bounded production mechanism profile; no small-fixture ratio exception.
    pub fn digest(&self) -> Result<Digest32, SparseError> {
        if !(5..=256).contains(&self.width)
            || self.top_k > self.width / 5
            || self.top_k * 100 < self.width
            || self.inhibition.len() > 4096
            || self.model_digest.is_zero()
            || self.normalization_digest.is_zero()
            || self.threshold_min_q24 < -H
            || self.threshold_max_q24 > H
            || self.threshold_min_q24 > self.threshold_max_q24
        {
            return Err(SparseError::InvalidConfig);
        }
        let rates = [
            self.temporal_decay_q24,
            self.inhibition_gain_q24,
            self.activity_decay_q24,
            self.target_activity_q24,
            self.threshold_rate_q24,
            self.eligibility_decay_q24,
        ];
        if rates.iter().any(|value| !(0..=Q).contains(value)) {
            return Err(SparseError::InvalidConfig);
        }
        let mut seen = BTreeSet::new();
        let mut row_sums = vec![0_i64; self.width];
        for edge in &self.inhibition {
            if edge.source >= self.width
                || edge.target >= self.width
                || edge.source == edge.target
                || !(0..=Q).contains(&edge.weight_q24)
                || !seen.insert((edge.target, edge.source))
            {
                return Err(SparseError::InvalidConfig);
            }
            row_sums[edge.target] += edge.weight_q24;
            if row_sums[edge.target] > Q {
                return Err(SparseError::InvalidConfig);
            }
        }
        let mut bytes = b"hepta.neuron.sparse-config.q24.v1".to_vec();
        bytes.extend_from_slice(self.model_digest.as_array());
        bytes.extend_from_slice(self.normalization_digest.as_array());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for value in [self.width as i64, self.top_k as i64]
            .into_iter()
            .chain(rates)
            .chain([self.threshold_min_q24, self.threshold_max_q24])
        {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        let mut edges = self.inhibition.clone();
        edges.sort();
        for edge in edges {
            bytes.extend_from_slice(&(edge.source as u64).to_be_bytes());
            bytes.extend_from_slice(&(edge.target as u64).to_be_bytes());
            bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl SparseCheckpoint {
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    /// Diagonal local-head eligibility sufficient statistics, not model weights.
    pub fn eligibility_q24(&self) -> &[i64] {
        &self.eligibility
    }

    pub fn thresholds_q24(&self) -> &[i64] {
        &self.threshold
    }

    fn calculate_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.neuron.sparse-checkpoint.q24.v1".to_vec();
        for value in [
            self.config,
            self.scope,
            self.objective,
            self.predecessor,
            self.input,
        ] {
            bytes.extend_from_slice(value.as_array());
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
            bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
            for value in values {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Compute a complete successor without mutating the selected config or prior state.
/// The caller must CAS-publish state and receipt together; success here is not a commit.
pub fn sparse_tick(
    config: &SparseConfig,
    input: &SparseTick,
    previous: Option<&SparseCheckpoint>,
) -> Result<(SparseCheckpoint, SparseSignalReceipt), SparseError> {
    let config_digest = config.digest()?;
    if [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ]
    .iter()
    .any(|digest| digest.is_zero())
        || input.drive_q24.len() != config.width
        || input.prediction_q24.len() != config.width
        || input
            .drive_q24
            .iter()
            .chain(&input.prediction_q24)
            .any(|v| !(-H..=H).contains(v))
    {
        return Err(SparseError::InvalidInput);
    }
    let mut binding = Vec::new();
    for value in [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ] {
        binding.extend_from_slice(value.as_array());
    }
    for value in input.drive_q24.iter().chain(&input.prediction_q24) {
        binding.extend_from_slice(&value.to_be_bytes());
    }
    let before = previous.map_or(Digest32::ZERO, SparseCheckpoint::digest);
    if let Some(prior) = previous {
        if prior.calculate_digest() != prior.digest {
            return Err(SparseError::InvalidCheckpoint);
        }
        if prior.config != config_digest {
            return Err(SparseError::ConfigDrift);
        }
        if prior.scope != input.scope_digest
            || prior.objective != input.objective_digest
            || prior.body != input.body_digest
        {
            return Err(SparseError::ScopeDrift);
        }
        if prior.sequence.checked_add(1) != Some(input.sequence) {
            return Err(SparseError::Sequence);
        }
        if input.monotonic_micros <= prior.monotonic_micros {
            return Err(SparseError::Clock);
        }
    } else if input.sequence != 1 {
        return Err(SparseError::Sequence);
    } else if input.monotonic_micros == 0 {
        return Err(SparseError::Clock);
    }
    let mut next = SparseCheckpoint {
        config: config_digest,
        scope: input.scope_digest,
        objective: input.objective_digest,
        body: input.body_digest,
        sequence: input.sequence,
        monotonic_micros: input.monotonic_micros,
        predecessor: before,
        input: Digest32::of_bytes(&binding),
        temporal: vec![0; config.width],
        activation: vec![0; config.width],
        activity: vec![0; config.width],
        threshold: vec![0; config.width],
        eligibility: vec![0; config.width],
        digest: Digest32::ZERO,
    };
    let mut inhibition = vec![0_i64; config.width];
    if let Some(prior) = previous {
        for edge in &config.inhibition {
            inhibition[edge.target] += mul(edge.weight_q24, prior.activation[edge.source]);
        }
    }
    let mut scores = Vec::with_capacity(config.width);
    let mut projections = 0_u32;
    for (index, drive) in input.drive_q24.iter().enumerate() {
        let old_h = previous.map_or(0, |p| p.temporal[index]);
        let raw_h = mul(config.temporal_decay_q24, old_h) + drive;
        next.temporal[index] = raw_h.clamp(-H, H);
        projections += u32::from(raw_h != next.temporal[index]);
        next.threshold[index] = previous.map_or(
            0_i64.clamp(config.threshold_min_q24, config.threshold_max_q24),
            |p| p.threshold[index],
        );
        let score = next.temporal[index]
            - mul(config.inhibition_gain_q24, inhibition[index])
            - next.threshold[index];
        if score > 0 {
            scores.push((index, score));
        }
    }
    scores.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    for &(index, score) in scores.iter().take(config.top_k) {
        next.activation[index] = score.min(H);
        projections += u32::from(score > H);
    }
    for (index, drive) in input.drive_q24.iter().enumerate() {
        let active = if next.activation[index] > 0 { Q } else { 0 };
        let old_rate = previous.map_or(0, |p| p.activity[index]);
        next.activity[index] =
            mul(config.activity_decay_q24, old_rate) + mul(Q - config.activity_decay_q24, active);
        let raw_theta = next.threshold[index]
            + mul(
                config.threshold_rate_q24,
                next.activity[index] - config.target_activity_q24,
            );
        next.threshold[index] = raw_theta.clamp(config.threshold_min_q24, config.threshold_max_q24);
        projections += u32::from(raw_theta != next.threshold[index]);
        let old_e = previous.map_or(0, |p| p.eligibility[index]);
        next.eligibility[index] =
            mul(config.eligibility_decay_q24, old_e) + mul(*drive, next.activation[index]);
    }
    let norm: i64 = next.eligibility.iter().map(|v| v.abs()).sum();
    if norm > ELIGIBILITY_L1 {
        for value in &mut next.eligibility {
            // Toward-zero radial L1 projection cannot exceed the declared norm.
            *value = (i128::from(*value) * i128::from(ELIGIBILITY_L1) / i128::from(norm)) as i64;
        }
        projections += 1;
    }
    next.digest = next.calculate_digest();
    let active_count = next.activation.iter().filter(|&&v| v > 0).count();
    let receipt = SparseSignalReceipt {
        config_digest,
        input_digest: next.input,
        checkpoint_before: before,
        checkpoint_after: next.digest,
        activation_q24: next.activation.clone(),
        active_fraction_ppm: (active_count * 1_000_000 / config.width) as u32,
        prediction_error_q24: input
            .drive_q24
            .iter()
            .zip(&input.prediction_q24)
            .map(|(observed, predicted)| (observed - predicted).abs())
            .max()
            .unwrap_or(0),
        projection_count: projections,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((next, receipt))
}

// Inputs are bounded before this helper. i128 handles products exactly.
fn mul(a: i64, b: i64) -> i64 {
    let product = i128::from(a) * i128::from(b);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q);
    let remainder = magnitude % i128::from(Q);
    let round_up =
        remainder * 2 > i128::from(Q) || (remainder * 2 == i128::from(Q) && quotient % 2 != 0);
    ((quotient + i128::from(round_up)) * product.signum()) as i64
}

#[cfg(test)]
#[path = "sparse_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "sparse_body_scope_tests.rs"]
mod body_scope_tests;
