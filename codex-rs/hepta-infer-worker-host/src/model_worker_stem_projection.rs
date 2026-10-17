//! Immutable, signed-Q24 low-rank Stem projection, compatible with the
//! shadow Python projection reference. No inference grant, source permission,
//! signature, installed Encoder or cache authority is created here.
//!
//! Feature width > 512 is handled only through an explicitly pinned matrix;
//! silently truncating the source Transformer representation is forbidden.

use super::Error;
use super::Q24_STATE_LIMIT;
use codex_hepta_types::Digest32;

const Q: i128 = 1_i128 << 24;
const MAX_SOURCE_WIDTH: usize = 8192;
const MAX_NATIVE_WIDTH: usize = 512;
const MAX_RANK: usize = 64;
const MAX_COEFFICIENTS: usize = 600_000;
const PROJECTION_DOMAIN: &[u8] = b"hepta.stem.low-rank-projection.q24.v1";
const BOUND_DOMAIN: &[u8] = b"hepta.stem.projected-feature-bound.v1";

fn push_field(buffer: &mut Vec<u8>, value: &str) -> Result<(), Error> {
    let len = u64::try_from(value.len()).map_err(|_| Error::ArithmeticOverflow)?;
    buffer.extend_from_slice(&len.to_be_bytes());
    buffer.extend_from_slice(value.as_bytes());
    Ok(())
}

fn checked_identity(digest: &str) -> Result<(), Error> {
    if digest.len() != 64
        || !digest
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return Err(Error::FeatureContract);
    }
    Ok(())
}

fn q48_round_ties_even(value: i128) -> Result<i64, Error> {
    let lower = value.div_euclid(Q);
    let remain = value.rem_euclid(Q);
    let twice = remain * 2;
    let rounded = if twice > Q || (twice == Q && lower.rem_euclid(2) == 1) {
        lower.checked_add(1).ok_or(Error::ArithmeticOverflow)?
    } else {
        lower
    };
    let result = i64::try_from(rounded).map_err(|_| Error::FeatureOutputMismatch)?;
    if !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(&result) {
        return Err(Error::FeatureOutputMismatch);
    }
    Ok(result)
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LowRankStemProjectionV1 {
    pub encoder_digest: String,
    pub preprocessor_digest: String,
    pub runtime_digest: String,
    pub normalizer_digest: String,
    pub representation: String,
    pub input_width: usize,
    pub output_width: usize,
    pub rank: usize,
    /// Q24 row-major [rank, input_width].
    pub a_q24: Vec<i64>,
    /// Q24 row-major [output_width, rank].
    pub b_q24: Vec<i64>,
    pub bias_q24: Vec<i64>,
}

impl LowRankStemProjectionV1 {
    pub fn validate(&self) -> Result<(), Error> {
        for digest in [
            &self.encoder_digest,
            &self.preprocessor_digest,
            &self.runtime_digest,
            &self.normalizer_digest,
        ] {
            checked_identity(digest)?;
        }
        if !matches!(self.representation.as_str(), "mean" | "landmark8")
            || !(1..=MAX_SOURCE_WIDTH).contains(&self.input_width)
            || !(1..=MAX_NATIVE_WIDTH).contains(&self.output_width)
            || !(1..=MAX_RANK).contains(&self.rank)
        {
            return Err(Error::FeatureLimit);
        }
        if self.a_q24.len() != self.input_width * self.rank
            || self.b_q24.len() != self.output_width * self.rank
            || self.bias_q24.len() != self.output_width
            || self.a_q24.len() + self.b_q24.len() + self.bias_q24.len() > MAX_COEFFICIENTS
        {
            return Err(Error::FeatureLimit);
        }
        if self
            .a_q24
            .iter()
            .chain(&self.b_q24)
            .chain(&self.bias_q24)
            .any(|v| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut bytes = PROJECTION_DOMAIN.to_vec();
        for value in [
            &self.encoder_digest,
            &self.preprocessor_digest,
            &self.runtime_digest,
            &self.normalizer_digest,
            &self.representation,
        ] {
            push_field(&mut bytes, value)?;
        }
        for value in [self.input_width, self.output_width, self.rank] {
            let value = u64::try_from(value).map_err(|_| Error::ArithmeticOverflow)?;
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for tensor in [&self.a_q24, &self.b_q24, &self.bias_q24] {
            let len = u64::try_from(tensor.len()).map_err(|_| Error::ArithmeticOverflow)?;
            bytes.extend_from_slice(&len.to_be_bytes());
            for value in tensor {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    /// An actual bounded low-rank matrix multiplication, not a slice.
    pub fn project_q24(&self, input: &[i64]) -> Result<Vec<i64>, Error> {
        self.validate()?;
        if input.len() != self.input_width
            || input
                .iter()
                .any(|v| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(v))
        {
            return Err(Error::FeatureLimit);
        }
        let mut hidden = Vec::with_capacity(self.rank);
        for row in self.a_q24.chunks_exact(self.input_width) {
            let acc = row.iter().zip(input).fold(0_i128, |sum, (weight, value)| {
                sum + (*weight as i128) * (*value as i128)
            });
            hidden.push(q48_round_ties_even(acc)?);
        }
        let mut projected = Vec::with_capacity(self.output_width);
        for (bias, row) in self.bias_q24.iter().zip(self.b_q24.chunks_exact(self.rank)) {
            let acc = row
                .iter()
                .zip(&hidden)
                .fold((*bias as i128) * Q, |sum, (w, v)| {
                    sum + (*w as i128) * (*v as i128)
                });
            projected.push(q48_round_ties_even(acc)?);
        }
        Ok(projected)
    }

    pub fn project_float32(&self, input: &[f32]) -> Result<Vec<i64>, Error> {
        if input.len() != self.input_width {
            return Err(Error::FeatureLimit);
        }
        let mut converted = Vec::with_capacity(input.len());
        for &value in input {
            if !value.is_finite() || !(-8.0..=8.0).contains(&value) {
                return Err(Error::FeatureLimit);
            }
            converted.push(((value as f64) * (Q as f64)).round_ties_even() as i64);
        }
        self.project_q24(&converted)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemProjectionBindingV1 {
    pub scope_digest: String,
    pub generation: u64,
    pub revocation_frontier_digest: String,
    pub encoder_digest: String,
    pub preprocessor_digest: String,
    pub runtime_digest: String,
    pub source_input_digest: String,
    pub source_feature_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectedStemFeatureV1 {
    pub values_q24: Vec<i64>,
    pub projection_digest: Digest32,
    pub projected_input_digest: Digest32,
    pub production_authorized: bool,
}

pub fn stem_feature_f32_digest(
    values: &[f32],
    token_count: u64,
    representation: &str,
) -> Result<Digest32, Error> {
    if values.is_empty()
        || values.len() > MAX_SOURCE_WIDTH
        || token_count == 0
        || !matches!(representation, "mean" | "landmark8")
        || values.iter().any(|v| !v.is_finite())
    {
        return Err(Error::FeatureLimit);
    }
    let mut bytes = b"hepta.stem.feature.f32.v1".to_vec();
    let len = u64::try_from(values.len()).map_err(|_| Error::ArithmeticOverflow)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    bytes.extend_from_slice(&token_count.to_be_bytes());
    bytes.extend_from_slice(representation.as_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

/// Validates the supplied source feature digest, scope, revocation and exact
/// immutable projector. Does NOT authenticate the caller or a CAS artifact.
pub fn project_bound_f32(
    projector: &LowRankStemProjectionV1,
    binding: &StemProjectionBindingV1,
    features: &[f32],
    token_count: u64,
) -> Result<ProjectedStemFeatureV1, Error> {
    projector.validate()?;
    for digest in [
        &binding.scope_digest,
        &binding.revocation_frontier_digest,
        &binding.encoder_digest,
        &binding.preprocessor_digest,
        &binding.runtime_digest,
        &binding.source_input_digest,
        &binding.source_feature_digest,
    ] {
        checked_identity(digest)?;
    }
    if binding.generation == 0
        || binding.encoder_digest != projector.encoder_digest
        || binding.preprocessor_digest != projector.preprocessor_digest
        || binding.runtime_digest != projector.runtime_digest
        || stem_feature_f32_digest(features, token_count, &projector.representation)?.to_string()
            != binding.source_feature_digest
    {
        return Err(Error::FeatureContract);
    }
    let projected = projector.project_float32(features)?;
    let projector_digest = projector.digest()?;
    let mut bytes = BOUND_DOMAIN.to_vec();
    for value in [
        &binding.scope_digest,
        &binding.revocation_frontier_digest,
        &binding.encoder_digest,
        &binding.preprocessor_digest,
        &binding.runtime_digest,
        &binding.source_input_digest,
        &binding.source_feature_digest,
    ] {
        push_field(&mut bytes, value)?;
    }
    push_field(&mut bytes, &projector_digest.to_string())?;
    bytes.extend_from_slice(&binding.generation.to_be_bytes());
    let len = u64::try_from(projected.len()).map_err(|_| Error::ArithmeticOverflow)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    for value in &projected {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(ProjectedStemFeatureV1 {
        values_q24: projected,
        projection_digest: projector_digest,
        projected_input_digest: Digest32::of_bytes(&bytes),
        production_authorized: false,
    })
}

/// Checks that an already admitted Neuron request consumes exactly this
/// projected feature and its generation-bound identity. No grant or
/// authorization payload is constructed here; the inference owner still
/// verifies a pre-existing reservation and lease independently.
pub fn verify_neuron_projected_request(
    binding: &StemProjectionBindingV1,
    projected: &ProjectedStemFeatureV1,
    request: &super::NeuronFeatureRequest,
    worker_generation: u64,
) -> Result<(), Error> {
    if worker_generation == 0
        || worker_generation != binding.generation
        || request.encoder_digest != binding.encoder_digest
        || request.input_digest != projected.projected_input_digest.to_string()
        || request.feature_vector_q24 != projected.values_q24
        || request.authorization.payload_digest
            != super::canonical_neuron_feature_payload_digest(request)
        || request.authorization.payload_digest != request.authorization.lease_payload_digest
    {
        return Err(Error::FeatureContract);
    }
    Ok(())
}

#[cfg(test)]
#[path = "model_worker_stem_projection_tests.rs"]
mod tests;
