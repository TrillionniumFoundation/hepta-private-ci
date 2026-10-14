//! Frozen, input-dependent, per-Cell Q24 low-rank gate for shadow qualification.
//!
//! This numerical kernel consumes only already admitted immutable features.
//! It does NOT train, execute an Encoder, authorize final use, load signed CAS
//! artifacts, or issue a production receipt. New learning versions must be
//! built off the serving path and registered as a new sealed model generation.

use codex_hepta_types::Digest32;

use super::Error;

const Q24: i64 = 1 << 24;
const Q24_ABS_LIMIT: i64 = 8 * Q24;
const MAX_DIM: usize = 512;
const MAX_GROUPS: usize = 64;
const MAX_RANK: usize = 32;
const MAX_HEAD_PARAMETERS: usize = 262_144;

/// A fully materialized immutable candidate. The trained state is private to
/// one Cell; no optimizer or mutable tensor is shared with other Cells.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DynamicGateCandidateV3 {
    pub cell_identity: String,
    pub encoder_digest: String,
    pub input_width: usize,
    pub output_width: usize,
    pub rank: usize,
    pub groups: usize,
    /// Row major [rank, input_width].
    pub down_q24: Vec<i64>,
    /// Row major [groups, rank].
    pub up_q24: Vec<i64>,
    pub gate_bias_q24: Vec<i64>,
    /// Cell-private frozen state, checkpointed with the candidate.
    pub cell_state_q24: Vec<i64>,
    pub drive_weights_q24: Vec<i64>,
    pub prediction_weights_q24: Vec<i64>,
    pub drive_bias_q24: Vec<i64>,
    pub prediction_bias_q24: Vec<i64>,
}

/// Every artifact has a distinct domain-separated digest derived from all
/// tensor bytes and shape metadata, never from a caller's declared digest.
#[derive(Clone, Debug)]
pub struct DynamicGateArtifactV3 {
    pub(crate) candidate: DynamicGateCandidateV3,
    pub(crate) head_digest: String,
    pub(crate) parameter_count: usize,
}

impl DynamicGateArtifactV3 {
    pub fn new(candidate: DynamicGateCandidateV3) -> Result<Self, Error> {
        super::validate_identity(&candidate.cell_identity, "cell")?;
        super::validate_digest(&candidate.encoder_digest, "encoder")?;
        if candidate.input_width == 0
            || candidate.output_width == 0
            || candidate.input_width > MAX_DIM
            || candidate.output_width > MAX_DIM
            || candidate.groups == 0
            || candidate.groups > MAX_GROUPS
            || candidate.rank == 0
            || candidate.rank > MAX_RANK
            || candidate.groups > candidate.input_width
        {
            return Err(Error::FeatureLimit);
        }
        let down = candidate
            .rank
            .checked_mul(candidate.input_width)
            .ok_or(Error::ArithmeticOverflow)?;
        let up = candidate
            .groups
            .checked_mul(candidate.rank)
            .ok_or(Error::ArithmeticOverflow)?;
        let dense = candidate
            .input_width
            .checked_mul(candidate.output_width)
            .ok_or(Error::ArithmeticOverflow)?;
        let total = down
            .checked_add(up)
            .and_then(|n| n.checked_add(candidate.groups.checked_mul(2)?))
            .and_then(|n| n.checked_add(dense.checked_mul(2)?))
            .and_then(|n| n.checked_add(candidate.output_width.checked_mul(2)?))
            .ok_or(Error::ArithmeticOverflow)?;
        if total > MAX_HEAD_PARAMETERS
            || candidate.down_q24.len() != down
            || candidate.up_q24.len() != up
            || candidate.gate_bias_q24.len() != candidate.groups
            || candidate.cell_state_q24.len() != candidate.groups
            || candidate.drive_weights_q24.len() != dense
            || candidate.prediction_weights_q24.len() != dense
            || candidate.drive_bias_q24.len() != candidate.output_width
            || candidate.prediction_bias_q24.len() != candidate.output_width
        {
            return Err(Error::FeatureLimit);
        }
        if tensors(&candidate)
            .iter()
            .flat_map(|tensor| tensor.iter())
            .any(|v| !(-Q24_ABS_LIMIT..=Q24_ABS_LIMIT).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        let head_digest = digest_candidate(&candidate);
        Ok(Self {
            candidate,
            head_digest,
            parameter_count: total,
        })
    }

    pub fn digest(&self) -> &str {
        &self.head_digest
    }

    pub fn parameter_count(&self) -> usize {
        self.parameter_count
    }

    pub fn tensor_bytes(&self) -> Result<usize, Error> {
        self.parameter_count
            .checked_mul(std::mem::size_of::<i64>())
            .ok_or(Error::ArithmeticOverflow)
    }

    pub fn compute(
        &self,
        encoder_digest: &str,
        cell_id: &str,
        features_q24: &[i64],
        expected_output_width: usize,
    ) -> Result<(Vec<i64>, Vec<i64>), Error> {
        let c = &self.candidate;
        if c.encoder_digest != encoder_digest
            || c.cell_identity != cell_id
            || features_q24.len() != c.input_width
            || expected_output_width != c.output_width
        {
            return Err(Error::FeatureOutputMismatch);
        }
        if features_q24
            .iter()
            .any(|v| !(-Q24_ABS_LIMIT..=Q24_ABS_LIMIT).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        let down_bias = vec![0_i64; c.rank];
        let low_rank = dense_q24(features_q24, &c.down_q24, &down_bias)?;
        let group_logits = dense_q24(&low_rank, &c.up_q24, &c.gate_bias_q24)?;
        let mut gates = Vec::with_capacity(c.groups);
        for (logit, state) in group_logits.iter().zip(&c.cell_state_q24) {
            let value = logit.checked_add(*state).ok_or(Error::ArithmeticOverflow)?;
            // Deterministic hard sigmoid: clamp(1/2 + x/4, 0, 1).
            // The trained Python exporter must use exactly this activation.
            gates.push((Q24 / 2 + value / 4).clamp(0, Q24));
        }
        let mut gated = Vec::with_capacity(c.input_width);
        for (index, feature) in features_q24.iter().enumerate() {
            let group = index * c.groups / c.input_width;
            gated.push(round_q24(i128::from(*feature) * i128::from(gates[group]))?);
        }
        let drive = dense_q24(&gated, &c.drive_weights_q24, &c.drive_bias_q24)?;
        let prediction = dense_q24(&gated, &c.prediction_weights_q24, &c.prediction_bias_q24)?;
        Ok((drive, prediction))
    }
}

fn tensors(candidate: &DynamicGateCandidateV3) -> [&[i64]; 8] {
    [
        &candidate.down_q24,
        &candidate.up_q24,
        &candidate.gate_bias_q24,
        &candidate.cell_state_q24,
        &candidate.drive_weights_q24,
        &candidate.prediction_weights_q24,
        &candidate.drive_bias_q24,
        &candidate.prediction_bias_q24,
    ]
}

fn digest_candidate(candidate: &DynamicGateCandidateV3) -> String {
    let mut bytes = b"hepta.infer.dynamic-cell-gate.v3".to_vec();
    for text in [&candidate.cell_identity, &candidate.encoder_digest] {
        bytes.extend_from_slice(&(text.len() as u64).to_be_bytes());
        bytes.extend_from_slice(text.as_bytes());
    }
    for dimension in [
        candidate.input_width,
        candidate.output_width,
        candidate.rank,
        candidate.groups,
    ] {
        bytes.extend_from_slice(&(dimension as u64).to_be_bytes());
    }
    for tensor in tensors(candidate) {
        bytes.extend_from_slice(&(tensor.len() as u64).to_be_bytes());
        for value in tensor {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn round_q24(raw_q48: i128) -> Result<i64, Error> {
    let divisor = i128::from(Q24);
    let floor = raw_q48.div_euclid(divisor);
    let remainder = raw_q48.rem_euclid(divisor);
    let twice = remainder * 2;
    let rounded = floor + i128::from(twice > divisor || (twice == divisor && floor % 2 != 0));
    if !(-i128::from(Q24_ABS_LIMIT)..=i128::from(Q24_ABS_LIMIT)).contains(&rounded) {
        return Err(Error::FeatureOutputMismatch);
    }
    i64::try_from(rounded).map_err(|_| Error::ArithmeticOverflow)
}

fn dense_q24(input: &[i64], weights: &[i64], bias: &[i64]) -> Result<Vec<i64>, Error> {
    if input.is_empty()
        || weights.len()
            != input
                .len()
                .checked_mul(bias.len())
                .ok_or(Error::ArithmeticOverflow)?
    {
        return Err(Error::FeatureLimit);
    }
    let mut output = Vec::with_capacity(bias.len());
    for (row, intercept) in weights.chunks_exact(input.len()).zip(bias) {
        let mut sum = i128::from(*intercept) * i128::from(Q24);
        for (weight, feature) in row.iter().zip(input) {
            sum = sum
                .checked_add(i128::from(*weight) * i128::from(*feature))
                .ok_or(Error::ArithmeticOverflow)?;
        }
        output.push(round_q24(sum)?);
    }
    Ok(output)
}

#[cfg(test)]
#[path = "model_worker_dynamic_gate_tests.rs"]
mod tests;
