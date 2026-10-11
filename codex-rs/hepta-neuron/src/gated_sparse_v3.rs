//! Shadow-only, versioned Q24 input-gated sparse temporal mechanism.
//!
//! All non-temporal calculations delegate to the exact V2 population kernel.
//! V1's journal and replay bytes are not modified. V3 does not grant routing,
//! persistence, model loading, training, calibration or effect authority.

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
const MAX_REPLAY_TICKS: usize = 1_024;

/// Three learned, frozen Q24 scalars per temporal channel. All fields are
/// included in the V3 config digest; weights never mutate during a run.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalGateV3 {
    pub bias_q24: i64,
    pub input_gain_q24: i64,
    pub change_gain_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GatedSparseConfigV3 {
    /// V2 projection, inhibition, populations, homeostasis and eligibility are
    /// preserved. V3 replaces only the V2 temporal_decay update; the
    /// base.temporal_decay_q24 remains bound to this V3 config digest but is
    /// not applied by the V3 tick.
    pub base: PopulationSparseConfigV2,
    pub gates: Vec<TemporalGateV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GatedSparseCheckpointV3 {
    config_digest: Digest32,
    predecessor: Digest32,
    original_input_digest: Digest32,
    gate_q24: Vec<i64>,
    inner: PopulationSparseCheckpointV2,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GatedSparseSignalReceiptV3 {
    pub config_digest: Digest32,
    /// Domain-separated binding to the complete *original* tick bytes.
    pub original_input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_q24: Vec<i64>,
    pub population_candidate_counts: Vec<u32>,
    pub gate_q24: Vec<i64>,
    pub gate_saturation_count: u32,
    pub active_fraction_ppm: u32,
    pub prediction_error_q24: i64,
    pub projection_count: u32,
    pub requires_calibration: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GatedSparseErrorV3 {
    InvalidGates,
    InvalidInput,
    InvalidCheckpoint,
    ConfigDrift,
    ReplayLength,
    Arithmetic,
    Mechanism(PopulationSparseError),
}

impl fmt::Display for GatedSparseErrorV3 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for GatedSparseErrorV3 {}

impl From<PopulationSparseError> for GatedSparseErrorV3 {
    fn from(value: PopulationSparseError) -> Self {
        Self::Mechanism(value)
    }
}

impl GatedSparseConfigV3 {
    pub fn digest(&self) -> Result<Digest32, GatedSparseErrorV3> {
        let base_digest = self.base.digest()?;
        if self.gates.len() != self.base.temporal_width
            || self.gates.iter().any(|gate| {
                !(0..=Q).contains(&gate.bias_q24)
                    || !(-Q..=Q).contains(&gate.input_gain_q24)
                    || !(-Q..=Q).contains(&gate.change_gain_q24)
            })
        {
            return Err(GatedSparseErrorV3::InvalidGates);
        }
        let mut bytes = b"hepta.neuron.gated-sparse-config.q24.v3".to_vec();
        bytes.extend_from_slice(base_digest.as_array());
        bytes.extend_from_slice(
            &u64::try_from(self.gates.len())
                .map_err(|_| GatedSparseErrorV3::Arithmetic)?
                .to_be_bytes(),
        );
        for gate in &self.gates {
            for value in [gate.bias_q24, gate.input_gain_q24, gate.change_gain_q24] {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl GatedSparseCheckpointV3 {
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

    pub fn thresholds_q24(&self) -> &[i64] {
        self.inner.thresholds_q24()
    }

    pub fn eligibility_q24(&self) -> &[i64] {
        self.inner.eligibility_q24()
    }

    fn calculate_digest(&self) -> Result<Digest32, GatedSparseErrorV3> {
        let mut bytes = b"hepta.neuron.gated-sparse-checkpoint.q24.v3".to_vec();
        for digest in [
            self.config_digest,
            self.predecessor,
            self.original_input_digest,
            self.inner.digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.gate_q24.len())
                .map_err(|_| GatedSparseErrorV3::Arithmetic)?
                .to_be_bytes(),
        );
        for gate in &self.gate_q24 {
            bytes.extend_from_slice(&gate.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Experimental temporal equation:
///   gate = clip(b + w_in*abs(drive)/8 + w_change*abs(drive-old)/16, 0, 1)
///   h_next = clip((1-gate)*old + gate*drive, -8, 8)
///
/// The norms use exact nonnegative integer division (floor); all Q24 products
/// use signed ties-to-even rounding, matching V2. V2 is invoked with a
/// temporary decay=0 config and h_next as its drive so only the temporal
/// recurrence changes. Neither V1 nor V2 public replay semantics change.
pub fn gated_sparse_tick_v3(
    config: &GatedSparseConfigV3,
    input: &PopulationSparseTickV2,
    previous: Option<&GatedSparseCheckpointV3>,
) -> Result<(GatedSparseCheckpointV3, GatedSparseSignalReceiptV3), GatedSparseErrorV3> {
    let config_digest = config.digest()?;
    validate_original_input(config, input)?;
    let predecessor = previous.map_or(Digest32::ZERO, GatedSparseCheckpointV3::digest);
    if let Some(prior) = previous {
        if prior.calculate_digest()? != prior.digest {
            return Err(GatedSparseErrorV3::InvalidCheckpoint);
        }
        if prior.config_digest != config_digest {
            return Err(GatedSparseErrorV3::ConfigDrift);
        }
    }

    let mut gated_temporal = Vec::with_capacity(config.base.temporal_width);
    let mut gates = Vec::with_capacity(config.base.temporal_width);
    let mut saturated = 0_u32;
    for (index, drive) in input.temporal_drive_q24.iter().copied().enumerate() {
        let old = previous.map_or(0, |prior| prior.inner.temporal_q24()[index]);
        let gate = &config.gates[index];
        let input_norm = drive.abs() / 8;
        let change_norm = (drive - old).abs() / 16;
        let raw_gate = gate
            .bias_q24
            .checked_add(mul_q24(gate.input_gain_q24, input_norm))
            .and_then(|value| value.checked_add(mul_q24(gate.change_gain_q24, change_norm)))
            .ok_or(GatedSparseErrorV3::Arithmetic)?;
        let g = raw_gate.clamp(0, Q);
        saturated += u32::from(g != raw_gate);
        gates.push(g);

        let update = mul_q24(Q - g, old)
            .checked_add(mul_q24(g, drive))
            .ok_or(GatedSparseErrorV3::Arithmetic)?;
        gated_temporal.push(update.clamp(-H, H));
    }

    let mut v2_config = config.base.clone();
    v2_config.temporal_decay_q24 = 0;
    let mut v2_input = input.clone();
    v2_input.temporal_drive_q24 = gated_temporal;
    let (inner, v2_receipt) =
        population_sparse_tick_v2(&v2_config, &v2_input, previous.map(|prior| &prior.inner))?;
    let original_input_digest = bind_original_input(input)?;
    let mut next = GatedSparseCheckpointV3 {
        config_digest,
        predecessor,
        original_input_digest,
        gate_q24: gates.clone(),
        inner,
        digest: Digest32::ZERO,
    };
    next.digest = next.calculate_digest()?;
    let receipt = GatedSparseSignalReceiptV3 {
        config_digest,
        original_input_digest,
        checkpoint_before: predecessor,
        checkpoint_after: next.digest,
        activation_q24: v2_receipt.activation_q24,
        population_candidate_counts: v2_receipt.population_candidate_counts,
        gate_q24: gates,
        gate_saturation_count: saturated,
        active_fraction_ppm: v2_receipt.active_fraction_ppm,
        prediction_error_q24: v2_receipt.prediction_error_q24,
        projection_count: v2_receipt.projection_count,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((next, receipt))
}

/// Cold-start deterministic reconstruction from *authenticated, ordered* V3
/// original tick records. This is NOT a persistent journal or artifact CAS.
/// A production owner must authenticate records and durably fence publications.
pub fn replay_gated_sparse_v3(
    config: &GatedSparseConfigV3,
    inputs: &[PopulationSparseTickV2],
) -> Result<GatedSparseCheckpointV3, GatedSparseErrorV3> {
    if inputs.is_empty() || inputs.len() > MAX_REPLAY_TICKS {
        return Err(GatedSparseErrorV3::ReplayLength);
    }
    let mut previous = None;
    for input in inputs {
        let (next, _) = gated_sparse_tick_v3(config, input, previous.as_ref())?;
        previous = Some(next);
    }
    previous.ok_or(GatedSparseErrorV3::ReplayLength)
}

fn validate_original_input(
    config: &GatedSparseConfigV3,
    input: &PopulationSparseTickV2,
) -> Result<(), GatedSparseErrorV3> {
    if [
        input.scope_digest,
        input.objective_digest,
        input.ndu_digest,
        input.body_digest,
        input.input_digest,
    ]
    .iter()
    .any(|digest| digest.is_zero())
        || input.temporal_drive_q24.len() != config.base.temporal_width
        || input.prediction_q24.len() != config.base.activation_width
        || input
            .temporal_drive_q24
            .iter()
            .chain(&input.prediction_q24)
            .any(|v| !(-H..=H).contains(v))
    {
        return Err(GatedSparseErrorV3::InvalidInput);
    }
    Ok(())
}

fn bind_original_input(input: &PopulationSparseTickV2) -> Result<Digest32, GatedSparseErrorV3> {
    let mut bytes = b"hepta.neuron.gated-sparse-input.q24.v3".to_vec();
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
        bytes.extend_from_slice(
            &u64::try_from(values.len())
                .map_err(|_| GatedSparseErrorV3::Arithmetic)?
                .to_be_bytes(),
        );
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
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
#[path = "gated_sparse_v3_tests.rs"]
mod tests;
