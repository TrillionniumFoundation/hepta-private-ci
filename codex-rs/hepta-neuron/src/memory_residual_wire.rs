//! Strict native transport preserving TensorCell float32 bits and parameter identity.

use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AssociativeMemoryError;
use crate::MEMORY_RESIDUAL_NUMERIC_PROFILE_V1;
use crate::MEMORY_RESIDUAL_SCHEMA_V1;
use crate::MemoryResidualCellV1;
use crate::MemoryResidualOutputProfileV1;

const MAX_BYTES: usize = 4 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TensorWire {
    shape: Vec<usize>,
    f32le_hex: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TensorsWire {
    #[serde(rename = "A")]
    a: TensorWire,
    #[serde(rename = "B")]
    b: TensorWire,
    #[serde(rename = "head.weight")]
    head_weight: TensorWire,
    #[serde(rename = "head.bias")]
    head_bias: TensorWire,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ResidualWire {
    schema: String,
    numeric_profile: String,
    output_profile: MemoryResidualOutputProfileV1,
    dimension: usize,
    rank: usize,
    encoder_sha256: String,
    checkpoint_manifest_sha256: String,
    training_history_sha256: String,
    parameter_sha256: String,
    lineage_sources: Vec<String>,
    tensors: TensorsWire,
}

impl ResidualWire {
    pub(super) fn decode(
        bytes: &[u8],
        expected: Digest32,
    ) -> Result<MemoryResidualCellV1, AssociativeMemoryError> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        if expected.is_zero() || Digest32::of_bytes(bytes) != expected {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        let wire: Self =
            serde_json::from_slice(bytes).map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
        if wire.schema != MEMORY_RESIDUAL_SCHEMA_V1
            || wire.numeric_profile != MEMORY_RESIDUAL_NUMERIC_PROFILE_V1
            || wire.dimension != 384
            || !(1..=wire.dimension).contains(&wire.rank)
            || !(1..=4096).contains(&wire.lineage_sources.len())
            || wire.lineage_sources.windows(2).any(|pair| pair[0] >= pair[1])
        {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let encoder_digest = digest(&wire.encoder_sha256)?;
        let checkpoint_digest = digest(&wire.checkpoint_manifest_sha256)?;
        let training_digest = digest(&wire.training_history_sha256)?;
        let parameter_digest = digest(&wire.parameter_sha256)?;
        for source in &wire.lineage_sources {
            digest(source)?;
        }
        let d = wire.dimension;
        let r = wire.rank;
        let w = wire.output_profile.width();
        let mut parameter_bytes = Vec::new();
        let a = decode_tensor("A", &wire.tensors.a, &[r, d], &mut parameter_bytes)?;
        let b = decode_tensor("B", &wire.tensors.b, &[d, r], &mut parameter_bytes)?;
        let head_bias = decode_tensor(
            "head.bias", &wire.tensors.head_bias, &[w], &mut parameter_bytes,
        )?;
        let head_weight = decode_tensor(
            "head.weight", &wire.tensors.head_weight, &[w, d], &mut parameter_bytes,
        )?;
        if Digest32::of_bytes(&parameter_bytes) != parameter_digest {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        Ok(MemoryResidualCellV1 {
            profile: wire.output_profile,
            dimension: d,
            rank: r,
            a,
            b,
            head_weight,
            head_bias,
            encoder_digest,
            parameter_digest,
            checkpoint_digest,
            training_digest,
            sources: wire.lineage_sources,
            artifact_digest: expected,
            serialized_bytes: bytes.len(),
        })
    }
}

fn digest(value: &str) -> Result<Digest32, AssociativeMemoryError> {
    let parsed = value.parse::<Digest32>().map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
    if parsed.is_zero() || parsed.to_string() != value {
        return Err(AssociativeMemoryError::InvalidArtifact);
    }
    Ok(parsed)
}

fn decode_tensor(
    name: &str,
    tensor: &TensorWire,
    shape: &[usize],
    parameter_bytes: &mut Vec<u8>,
) -> Result<Vec<f32>, AssociativeMemoryError> {
    let count = shape.iter().try_fold(1_usize, |size, dimension| size.checked_mul(*dimension))
        .ok_or(AssociativeMemoryError::InvalidArtifact)?;
    if tensor.shape != shape || tensor.f32le_hex.len() != count * 8 {
        return Err(AssociativeMemoryError::InvalidArtifact);
    }
    let metadata = serde_json::to_vec(&(name, shape, "float32"))
        .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
    parameter_bytes.extend_from_slice(&metadata);
    let mut values = Vec::with_capacity(count);
    for encoded in tensor.f32le_hex.as_bytes().chunks_exact(8) {
        let mut raw = [0_u8; 4];
        for (index, pair) in encoded.chunks_exact(2).enumerate() {
            let high = hex_digit(pair[0])?;
            let low = hex_digit(pair[1])?;
            raw[index] = high * 16 + low;
        }
        let value = f32::from_le_bytes(raw);
        if !value.is_finite() {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        parameter_bytes.extend_from_slice(&raw);
        values.push(value);
    }
    Ok(values)
}

fn hex_digit(value: u8) -> Result<u8, AssociativeMemoryError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(AssociativeMemoryError::InvalidArtifact),
    }
}
