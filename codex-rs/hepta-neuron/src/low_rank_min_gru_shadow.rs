//! Research-only Q24 low-rank minGRU-inspired temporal comparator.
//!
//! Both update gate and candidate depend only on the current input, allowing a
//! recurrent affine update in the previous state. This is NOT a pretrained GRU,
//! a production Cell owner, a training implementation or an authorization port.
//! Downstream sparse competition delegates to the unchanged V2 mechanism.
//! The rank factor matrices are frozen manifest parameters for this generation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::population_v2::PopulationSparseCheckpointV2;
use crate::population_v2::PopulationSparseConfigV2;
use crate::population_v2::PopulationSparseError;
use crate::population_v2::PopulationSparseTickV2;
use crate::population_v2::PreparedPopulationSparseConfigV2;
use crate::population_v2::population_sparse_tick_v2_from_temporal_override;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_REPLAY: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LowRankMinGruConfigV1 {
    pub base: PopulationSparseConfigV2,
    pub rank: usize,
    /// Rank-major [rank, temporal_width].
    pub gate_input_q24: Vec<i64>,
    /// Channel-major [temporal_width, rank].
    pub gate_output_q24: Vec<i64>,
    /// Rank-major [rank, temporal_width].
    pub candidate_input_q24: Vec<i64>,
    /// Channel-major [temporal_width, rank].
    pub candidate_output_q24: Vec<i64>,
    pub gate_bias_q24: Vec<i64>,
    pub candidate_bias_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LowRankMinGruCheckpointV1 {
    config: Digest32,
    predecessor: Digest32,
    original_input: Digest32,
    inner: PopulationSparseCheckpointV2,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LowRankMinGruReceiptV1 {
    pub config_digest: Digest32,
    pub original_input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub gate_q24: Vec<i64>,
    pub activation_q24: Vec<i64>,
    pub population_candidate_counts: Vec<u32>,
    pub active_fraction_ppm: u32,
    pub prediction_error_q24: i64,
    pub projection_count: u32,
    pub requires_calibration: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LowRankMinGruErrorV1 {
    InvalidConfig,
    InvalidInput,
    InvalidCheckpoint,
    ConfigDrift,
    ReplayLength,
    Arithmetic,
    Mechanism(PopulationSparseError),
}

impl fmt::Display for LowRankMinGruErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LowRankMinGruErrorV1 {}

impl From<PopulationSparseError> for LowRankMinGruErrorV1 {
    fn from(value: PopulationSparseError) -> Self {
        Self::Mechanism(value)
    }
}

impl LowRankMinGruConfigV1 {
    /// Counts only this candidate's trainable gate/candidate factor tensors.
    /// Shared encoder, V2 graph, head and optimizer state must be added by the
    /// experiment-level budget ledger; do not present this as a total Cell size.
    pub fn temporal_parameter_count(&self) -> Result<usize, LowRankMinGruErrorV1> {
        self.digest()?;
        let width = self.base.temporal_width;
        width
            .checked_mul(self.rank)
            .and_then(|value| value.checked_mul(4))
            .and_then(|value| value.checked_add(2 * width))
            .ok_or(LowRankMinGruErrorV1::Arithmetic)
    }

    pub fn digest(&self) -> Result<Digest32, LowRankMinGruErrorV1> {
        let base_digest = self.base.digest()?;
        let width = self.base.temporal_width;
        if self.rank == 0 || self.rank > width {
            return Err(LowRankMinGruErrorV1::InvalidConfig);
        }
        let n = width
            .checked_mul(self.rank)
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        let factors = [
            &self.gate_input_q24,
            &self.gate_output_q24,
            &self.candidate_input_q24,
            &self.candidate_output_q24,
        ];
        if factors
            .iter()
            .any(|values| values.len() != n || values.iter().any(|value| !(-Q..=Q).contains(value)))
            || self.gate_bias_q24.len() != width
            || self.candidate_bias_q24.len() != width
            || self
                .gate_bias_q24
                .iter()
                .any(|value| !(-Q..=Q).contains(value))
            || self
                .candidate_bias_q24
                .iter()
                .any(|value| !(-Q..=Q).contains(value))
        {
            return Err(LowRankMinGruErrorV1::InvalidConfig);
        }

        let mut bytes = b"hepta.neuron.low-rank-min-gru-config.q24.v1".to_vec();
        bytes.extend_from_slice(base_digest.as_array());
        bytes.extend_from_slice(&(self.rank as u64).to_be_bytes());
        for values in factors
            .into_iter()
            .chain([&self.gate_bias_q24, &self.candidate_bias_q24])
        {
            bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
            for value in values {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Prepared immutable low-rank minGRU shadow configuration. Does not train,
/// change selected tensors or authorize routes. For each generation, the
/// private config and its cached hashes are frozen together.
#[derive(Clone, Debug)]
pub struct PreparedLowRankMinGruConfigV1 {
    config: LowRankMinGruConfigV1,
    prepared_base: PreparedPopulationSparseConfigV2,
    config_digest: Digest32,
}

impl PreparedLowRankMinGruConfigV1 {
    pub fn new(config: LowRankMinGruConfigV1) -> Result<Self, LowRankMinGruErrorV1> {
        let config_digest = config.digest()?;
        let prepared_base = PreparedPopulationSparseConfigV2::new(config.base.clone())?;
        Ok(Self {
            config,
            prepared_base,
            config_digest,
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.config_digest
    }

    pub fn tick(
        &self,
        input: &PopulationSparseTickV2,
        previous: Option<&LowRankMinGruCheckpointV1>,
    ) -> Result<(LowRankMinGruCheckpointV1, LowRankMinGruReceiptV1), LowRankMinGruErrorV1> {
        low_rank_min_gru_tick_v1_inner(
            &self.config,
            input,
            previous,
            Some((&self.prepared_base, self.config_digest)),
        )
    }
}

impl LowRankMinGruCheckpointV1 {
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
        let mut bytes = b"hepta.neuron.low-rank-min-gru-checkpoint.q24.v1".to_vec();
        for digest in [
            self.config,
            self.predecessor,
            self.original_input,
            self.inner.digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Signed nearest/ties-to-even Q24 multiplication with checked final conversion.
fn mul_q24(left: i64, right: i64) -> Result<i64, LowRankMinGruErrorV1> {
    let product = i128::from(left) * i128::from(right);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q);
    let remainder = magnitude % i128::from(Q);
    let round_up =
        remainder * 2 > i128::from(Q) || (remainder * 2 == i128::from(Q) && quotient % 2 != 0);
    i64::try_from((quotient + i128::from(round_up)) * product.signum())
        .map_err(|_| LowRankMinGruErrorV1::Arithmetic)
}

/// V is rank-major; the operation does not allocate or multiply dense W=U*V.
fn rank_projection(
    factors: &[i64],
    input: &[i64],
    rank: usize,
) -> Result<Vec<i64>, LowRankMinGruErrorV1> {
    let width = input.len();
    let mut projected = Vec::with_capacity(rank);
    for r in 0..rank {
        let mut accumulator = 0_i64;
        for i in 0..width {
            accumulator = accumulator
                .checked_add(mul_q24(factors[r * width + i], input[i])?)
                .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        }
        projected.push(accumulator);
    }
    Ok(projected)
}

fn original_input_digest(input: &PopulationSparseTickV2) -> Digest32 {
    let mut bytes = b"hepta.neuron.low-rank-min-gru-input.q24.v1".to_vec();
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
    for values in [&input.temporal_drive_q24, &input.prediction_q24] {
        bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

/// Pure shadow successor; callers must not interpret this as a persisted commit.
/// The deployed V1 journal/replay format remains unchanged.
pub fn low_rank_min_gru_tick_v1(
    config: &LowRankMinGruConfigV1,
    input: &PopulationSparseTickV2,
    previous: Option<&LowRankMinGruCheckpointV1>,
) -> Result<(LowRankMinGruCheckpointV1, LowRankMinGruReceiptV1), LowRankMinGruErrorV1> {
    low_rank_min_gru_tick_v1_inner(config, input, previous, None)
}

fn low_rank_min_gru_tick_v1_inner(
    config: &LowRankMinGruConfigV1,
    input: &PopulationSparseTickV2,
    previous: Option<&LowRankMinGruCheckpointV1>,
    prepared: Option<(&PreparedPopulationSparseConfigV2, Digest32)>,
) -> Result<(LowRankMinGruCheckpointV1, LowRankMinGruReceiptV1), LowRankMinGruErrorV1> {
    let config_digest = match prepared {
        Some((_, digest)) => digest,
        None => config.digest()?,
    };
    let width = config.base.temporal_width;
    if input.temporal_drive_q24.len() != width
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
        return Err(LowRankMinGruErrorV1::InvalidInput);
    }
    let before = previous.map_or(Digest32::ZERO, LowRankMinGruCheckpointV1::digest);
    if let Some(prior) = previous {
        if prior.calculate_digest() != prior.digest {
            return Err(LowRankMinGruErrorV1::InvalidCheckpoint);
        }
        if prior.config != config_digest {
            return Err(LowRankMinGruErrorV1::ConfigDrift);
        }
    }
    let gate_latent = rank_projection(
        &config.gate_input_q24,
        &input.temporal_drive_q24,
        config.rank,
    )?;
    let candidate_latent = rank_projection(
        &config.candidate_input_q24,
        &input.temporal_drive_q24,
        config.rank,
    )?;
    let mut gates = Vec::with_capacity(width);
    let mut successor = Vec::with_capacity(width);
    let mut clamps = 0_u32;
    for (i, drive) in input.temporal_drive_q24.iter().copied().enumerate() {
        let mut raw_gate = (Q / 2)
            .checked_add(config.gate_bias_q24[i])
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        let mut raw_candidate = drive
            .checked_add(config.candidate_bias_q24[i])
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        for r in 0..config.rank {
            raw_gate = raw_gate
                .checked_add(mul_q24(
                    config.gate_output_q24[i * config.rank + r],
                    gate_latent[r],
                )?)
                .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
            raw_candidate = raw_candidate
                .checked_add(mul_q24(
                    config.candidate_output_q24[i * config.rank + r],
                    candidate_latent[r],
                )?)
                .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        }
        let gate = raw_gate.clamp(0, Q);
        let candidate = raw_candidate.clamp(-H, H);
        clamps = clamps
            .checked_add(u32::from(gate != raw_gate) + u32::from(candidate != raw_candidate))
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        let old = previous.map_or(0, |prior| prior.inner.temporal_q24()[i]);
        let raw_next = mul_q24(Q - gate, old)?
            .checked_add(mul_q24(gate, candidate)?)
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        let next = raw_next.clamp(-H, H);
        clamps = clamps
            .checked_add(u32::from(raw_next != next))
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?;
        gates.push(gate);
        successor.push(next);
    }

    let (inner, v2_receipt) = match prepared {
        Some((base, _)) => {
            base.tick_from_temporal_override(input, &successor, previous.map(|prior| &prior.inner))?
        }
        None => population_sparse_tick_v2_from_temporal_override(
            &config.base,
            input,
            &successor,
            previous.map(|prior| &prior.inner),
        )?,
    };
    let original_input = original_input_digest(input);
    let mut checkpoint = LowRankMinGruCheckpointV1 {
        config: config_digest,
        predecessor: before,
        original_input,
        inner,
        digest: Digest32::ZERO,
    };
    checkpoint.digest = checkpoint.calculate_digest();
    let receipt = LowRankMinGruReceiptV1 {
        config_digest,
        original_input_digest: original_input,
        checkpoint_before: before,
        checkpoint_after: checkpoint.digest,
        gate_q24: gates,
        activation_q24: v2_receipt.activation_q24,
        population_candidate_counts: v2_receipt.population_candidate_counts,
        active_fraction_ppm: v2_receipt.active_fraction_ppm,
        prediction_error_q24: v2_receipt.prediction_error_q24,
        projection_count: v2_receipt
            .projection_count
            .checked_add(clamps)
            .ok_or(LowRankMinGruErrorV1::Arithmetic)?,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((checkpoint, receipt))
}

pub fn replay_low_rank_min_gru_v1(
    config: &LowRankMinGruConfigV1,
    inputs: &[PopulationSparseTickV2],
) -> Result<LowRankMinGruCheckpointV1, LowRankMinGruErrorV1> {
    if inputs.is_empty() || inputs.len() > MAX_REPLAY {
        return Err(LowRankMinGruErrorV1::ReplayLength);
    }
    let mut previous = None;
    for input in inputs {
        let (next, _) = low_rank_min_gru_tick_v1(config, input, previous.as_ref())?;
        previous = Some(next);
    }
    previous.ok_or(LowRankMinGruErrorV1::ReplayLength)
}

#[cfg(test)]
#[path = "low_rank_min_gru_shadow_tests.rs"]
mod tests;
