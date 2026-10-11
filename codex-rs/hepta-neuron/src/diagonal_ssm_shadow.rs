//! Bounded, diagonal Q24 state-space shadow comparator for A3.
//!
//! This is a distinct parameter / checkpoint generation from V1, V2 and V3.
//! It holds no production routing, effect or model-selection authority. All
//! non-temporal computation delegates to the same V2 sparse competition kernel.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::population_v2::PopulationSparseCheckpointV2;
use crate::population_v2::PopulationSparseConfigV2;
use crate::population_v2::PopulationSparseError;
use crate::population_v2::PopulationSparseTickV2;
use crate::population_v2::population_sparse_tick_v2;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_ELAPSED_STEPS: u64 = 65_535;
const MAX_REPLAY: usize = 1_024;

/// Stable diagonal recurrence h_t = A(delta_t) h_(t-1) + B * x_t.
/// Each channel uses just two frozen parameters, and the same input
/// information/Encoder as the V2/V3 competitor. Time is already part
/// of the shared PopulationSparseTickV2 monotonic input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiagonalSsmConfigV1 {
    pub base: PopulationSparseConfigV2,
    pub decay_per_step_q24: Vec<i64>,
    pub input_gain_q24: Vec<i64>,
    pub time_quantum_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiagonalSsmCheckpointV1 {
    config: Digest32,
    predecessor: Digest32,
    original_input: Digest32,
    monotonic_micros: u64,
    elapsed_steps: u64,
    inner: PopulationSparseCheckpointV2,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DiagonalSsmReceiptV1 {
    pub config_digest: Digest32,
    pub original_input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub elapsed_steps: u64,
    pub activation_q24: Vec<i64>,
    pub population_candidate_counts: Vec<u32>,
    pub active_fraction_ppm: u32,
    pub prediction_error_q24: i64,
    pub projection_count: u32,
    pub requires_calibration: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DiagonalSsmErrorV1 {
    InvalidConfig,
    InvalidInput,
    InvalidCheckpoint,
    ConfigDrift,
    InvalidElapsedTime,
    ReplayLength,
    Arithmetic,
    Mechanism(PopulationSparseError),
}

impl fmt::Display for DiagonalSsmErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for DiagonalSsmErrorV1 {}
impl From<PopulationSparseError> for DiagonalSsmErrorV1 {
    fn from(value: PopulationSparseError) -> Self {
        Self::Mechanism(value)
    }
}

impl DiagonalSsmConfigV1 {
    pub fn digest(&self) -> Result<Digest32, DiagonalSsmErrorV1> {
        let base = self.base.digest()?;
        let width = self.base.temporal_width;
        if self.decay_per_step_q24.len() != width
            || self.input_gain_q24.len() != width
            || self.time_quantum_micros == 0
            || self.time_quantum_micros > 1_000_000_000
            || self
                .decay_per_step_q24
                .iter()
                .any(|value| !(0..=Q).contains(value))
            || self
                .input_gain_q24
                .iter()
                .any(|value| !(-Q..=Q).contains(value))
        {
            return Err(DiagonalSsmErrorV1::InvalidConfig);
        }
        let mut bytes = b"hepta.neuron.diagonal-ssm-config.q24.v1".to_vec();
        bytes.extend_from_slice(base.as_array());
        bytes.extend_from_slice(&self.time_quantum_micros.to_be_bytes());
        bytes.extend_from_slice(&(width as u64).to_be_bytes());
        for value in self.decay_per_step_q24.iter().chain(&self.input_gain_q24) {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl DiagonalSsmCheckpointV1 {
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn sequence(&self) -> u64 {
        self.inner.sequence()
    }

    pub fn temporal_q24(&self) -> &[i64] {
        self.inner.temporal_q24()
    }

    pub fn activation_q24(&self) -> &[i64] {
        self.inner.activation_q24()
    }

    fn calculate_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.neuron.diagonal-ssm-checkpoint.q24.v1".to_vec();
        for digest in [
            self.config,
            self.predecessor,
            self.original_input,
            self.inner.digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.monotonic_micros.to_be_bytes());
        bytes.extend_from_slice(&self.elapsed_steps.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

pub fn diagonal_ssm_tick_v1(
    config: &DiagonalSsmConfigV1,
    input: &PopulationSparseTickV2,
    previous: Option<&DiagonalSsmCheckpointV1>,
) -> Result<(DiagonalSsmCheckpointV1, DiagonalSsmReceiptV1), DiagonalSsmErrorV1> {
    let config_digest = config.digest()?;
    if input.temporal_drive_q24.len() != config.base.temporal_width
        || input.prediction_q24.len() != config.base.activation_width
        || [
            input.scope_digest,
            input.objective_digest,
            input.ndu_digest,
            input.body_digest,
            input.input_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        || input
            .temporal_drive_q24
            .iter()
            .chain(&input.prediction_q24)
            .any(|value| !(-H..=H).contains(value))
    {
        return Err(DiagonalSsmErrorV1::InvalidInput);
    }
    let before = previous.map_or(Digest32::ZERO, DiagonalSsmCheckpointV1::digest);
    let steps = if let Some(prior) = previous {
        if prior.calculate_digest() != prior.digest {
            return Err(DiagonalSsmErrorV1::InvalidCheckpoint);
        }
        if prior.config != config_digest {
            return Err(DiagonalSsmErrorV1::ConfigDrift);
        }
        let delta = input
            .monotonic_micros
            .checked_sub(prior.monotonic_micros)
            .filter(|delta| *delta > 0)
            .ok_or(DiagonalSsmErrorV1::InvalidElapsedTime)?;
        // Ceiling converts positive sub-quantum gaps to one step rather
        // than silently treating them as zero decay.
        delta / config.time_quantum_micros + u64::from(delta % config.time_quantum_micros != 0)
    } else {
        1
    };
    if steps == 0 || steps > MAX_ELAPSED_STEPS {
        return Err(DiagonalSsmErrorV1::InvalidElapsedTime);
    }
    let mut effective = Vec::with_capacity(config.base.temporal_width);
    let mut clamps = 0_u32;
    for (i, drive) in input.temporal_drive_q24.iter().copied().enumerate() {
        let old = previous.map_or(0, |prior| prior.temporal_q24()[i]);
        let retention = q24_power(config.decay_per_step_q24[i], steps);
        let raw = mul_q24(retention, old)
            .checked_add(mul_q24(config.input_gain_q24[i], drive))
            .ok_or(DiagonalSsmErrorV1::Arithmetic)?;
        let clamped = raw.clamp(-H, H);
        clamps += u32::from(raw != clamped);
        effective.push(clamped);
    }

    let mut v2_config = config.base.clone();
    v2_config.temporal_decay_q24 = 0;
    let mut v2_input = input.clone();
    v2_input.temporal_drive_q24 = effective;
    let (inner, receipt) =
        population_sparse_tick_v2(&v2_config, &v2_input, previous.map(|prior| &prior.inner))?;
    let original_input = input_digest(input);
    let mut next = DiagonalSsmCheckpointV1 {
        config: config_digest,
        predecessor: before,
        original_input,
        monotonic_micros: input.monotonic_micros,
        elapsed_steps: steps,
        inner,
        digest: Digest32::ZERO,
    };
    next.digest = next.calculate_digest();
    let signal = DiagonalSsmReceiptV1 {
        config_digest,
        original_input_digest: original_input,
        checkpoint_before: before,
        checkpoint_after: next.digest,
        elapsed_steps: steps,
        activation_q24: receipt.activation_q24,
        population_candidate_counts: receipt.population_candidate_counts,
        active_fraction_ppm: receipt.active_fraction_ppm,
        prediction_error_q24: receipt.prediction_error_q24,
        projection_count: receipt.projection_count + clamps,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((next, signal))
}

pub fn replay_diagonal_ssm_v1(
    config: &DiagonalSsmConfigV1,
    inputs: &[PopulationSparseTickV2],
) -> Result<DiagonalSsmCheckpointV1, DiagonalSsmErrorV1> {
    if inputs.is_empty() || inputs.len() > MAX_REPLAY {
        return Err(DiagonalSsmErrorV1::ReplayLength);
    }
    let mut prior = None;
    for input in inputs {
        let (next, _) = diagonal_ssm_tick_v1(config, input, prior.as_ref())?;
        prior = Some(next);
    }
    prior.ok_or(DiagonalSsmErrorV1::ReplayLength)
}

fn input_digest(input: &PopulationSparseTickV2) -> Digest32 {
    let mut bytes = b"hepta.neuron.diagonal-ssm-input.q24.v1".to_vec();
    for digest in [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&input.sequence.to_be_bytes());
    bytes.extend_from_slice(&input.monotonic_micros.to_be_bytes());
    for data in [&input.temporal_drive_q24, &input.prediction_q24] {
        bytes.extend_from_slice(&(data.len() as u64).to_be_bytes());
        for value in data {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn q24_power(mut base: i64, mut exponent: u64) -> i64 {
    let mut answer = Q;
    while exponent > 0 {
        if exponent & 1 != 0 {
            answer = mul_q24(answer, base);
        }
        exponent >>= 1;
        if exponent > 0 {
            base = mul_q24(base, base);
        }
    }
    answer
}

fn mul_q24(left: i64, right: i64) -> i64 {
    let product = i128::from(left) * i128::from(right);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q);
    let remainder = magnitude % i128::from(Q);
    let round_up =
        remainder * 2 > i128::from(Q) || (remainder * 2 == i128::from(Q) && quotient % 2 != 0);
    ((quotient + i128::from(round_up)) * product.signum()) as i64
}

#[cfg(test)]
#[path = "diagonal_ssm_shadow_tests.rs"]
mod tests;
