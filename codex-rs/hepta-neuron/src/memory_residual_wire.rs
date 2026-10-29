//! Closed residual envelope: validate dimensions, digests and dependencies
//! before native execution; do not reinterpret the legacy catalog profile.

use std::collections::BTreeMap;
use std::fmt;
use std::marker::PhantomData;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::MapAccess;
use serde::de::Visitor;

use crate::AssociativeMemoryError;
use crate::memory_residual_cell::MAX_MEMORY_RESIDUAL_BYTES;
use crate::memory_residual_cell::MEMORY_RESIDUAL_ADDRESS_PROFILE_V1;
use crate::memory_residual_cell::MEMORY_RESIDUAL_NUMERIC_PROFILE_V1;
use crate::memory_residual_cell::MEMORY_RESIDUAL_POLICY_PROFILE_V1;
use crate::memory_residual_cell::MEMORY_RESIDUAL_PROGRAM_PROFILE_V1;
use crate::memory_residual_cell::MEMORY_RESIDUAL_SCHEMA_V1;
use crate::memory_residual_cell::MemoryResidualCostV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Tensor {
    shape: Vec<usize>,
    f32le_hex: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Feature {
    canonical_text_sha256: String,
    feature_sha256: String,
    f32le_hex: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Wire {
    schema: String,
    kind: MemoryCellKindV1,
    address_profile: String,
    numeric_profile: String,
    output_profile: String,
    dimension: usize,
    rank: usize,
    minimum_margin: f64,
    encoder_sha256: String,
    owner_cut_sha256: String,
    parameter_sha256: String,
    checkpoint_sha256: String,
    training_receipt_sha256: String,
    #[serde(deserialize_with = "unique_map")]
    supports: BTreeMap<String, Vec<String>>,
    lineage_sources: Vec<String>,
    #[serde(deserialize_with = "unique_map")]
    features: BTreeMap<String, Feature>,
    #[serde(deserialize_with = "unique_map")]
    arrays: BTreeMap<String, Tensor>,
}

pub(super) struct ResidualData {
    pub kind: MemoryCellKindV1,
    pub digest: Digest32,
    pub parameter_digest: Digest32,
    pub head_digest: Digest32,
    pub encoder_digest: Digest32,
    pub owner_cut_digest: Digest32,
    pub output_profile: &'static str,
    pub minimum_margin: f64,
    pub rank: usize,
    pub supports: BTreeMap<String, Vec<String>>,
    pub lineage: Vec<String>,
    pub features: BTreeMap<String, Vec<f32>>,
    pub a: Vec<f32>,
    pub b: Vec<f32>,
    pub head_bias: Vec<f32>,
    pub head_weight: Vec<f32>,
    pub cost: MemoryResidualCostV1,
}

pub(super) fn load(bytes: &[u8], expected: Digest32) -> Result<ResidualData, AssociativeMemoryError> {
    use AssociativeMemoryError::BindingMismatch;
    use AssociativeMemoryError::InvalidArtifact;
    if bytes.is_empty() || bytes.len() > MAX_MEMORY_RESIDUAL_BYTES { return Err(InvalidArtifact); }
    if expected.is_zero() || Digest32::of_bytes(bytes) != expected { return Err(BindingMismatch); }
    let wire: Wire = serde_json::from_slice(bytes).map_err(|_| InvalidArtifact)?;
    let (width, output_profile) = match wire.kind {
        MemoryCellKindV1::Semantic => (12, MEMORY_RESIDUAL_POLICY_PROFILE_V1),
        MemoryCellKindV1::Procedure => (28, MEMORY_RESIDUAL_PROGRAM_PROFILE_V1),
        MemoryCellKindV1::Event => return Err(InvalidArtifact),
    };
    if wire.schema != MEMORY_RESIDUAL_SCHEMA_V1
        || wire.address_profile != MEMORY_RESIDUAL_ADDRESS_PROFILE_V1
        || wire.numeric_profile != MEMORY_RESIDUAL_NUMERIC_PROFILE_V1
        || wire.output_profile != output_profile || wire.dimension != 384
        || !(1..=64).contains(&wire.rank) || wire.arrays.len() != 4
        || !(1..=4096).contains(&wire.supports.len())
        || !wire.minimum_margin.is_finite() || wire.minimum_margin <= 0.0
        || wire.minimum_margin > 1_000_000.0
        || !wire.features.keys().eq(wire.supports.keys())
        || !valid_sources(&wire.lineage_sources, 65_536)
    { return Err(InvalidArtifact); }
    let encoder_digest = digest(&wire.encoder_sha256)?;
    let owner_cut_digest = digest(&wire.owner_cut_sha256)?;
    digest(&wire.checkpoint_sha256)?;
    digest(&wire.training_receipt_sha256)?;
    for (key, sources) in &wire.supports {
        digest(key)?;
        if !valid_sources(sources, 128)
            || sources.iter().any(|source| wire.lineage_sources.binary_search(source).is_err())
        { return Err(InvalidArtifact); }
    }
    let mut cost = MemoryResidualCostV1 {
        serialized_bytes: bytes.len() as u64, parameter_bytes: 0,
        head_parameter_bytes: 0, feature_bytes: 0,
        support_metadata_bytes: encoded_len(&wire.supports)?,
        lineage_metadata_bytes: encoded_len(&wire.lineage_sources)?,
        feature_metadata_bytes: encoded_len(&wire.features)?,
    };
    let mut parameters = Vec::new();
    let mut head = Vec::new();
    let mut arrays = BTreeMap::new();
    for (name, shape) in [
        ("A", vec![wire.rank, wire.dimension]),
        ("B", vec![wire.dimension, wire.rank]),
        ("head.bias", vec![width]),
        ("head.weight", vec![width, wire.dimension]),
    ] {
        let tensor = wire.arrays.get(name).ok_or(InvalidArtifact)?;
        if tensor.shape != shape { return Err(InvalidArtifact); }
        let length = shape.iter().try_fold(1_usize, |n, d| n.checked_mul(*d)).ok_or(InvalidArtifact)?;
        let (values, raw) = decode(&tensor.f32le_hex, length)?;
        let header = serde_json::to_vec(&(name, shape, "float32")).map_err(|_| InvalidArtifact)?;
        parameters.extend_from_slice(&header);
        parameters.extend_from_slice(&raw);
        cost.parameter_bytes += raw.len() as u64;
        if name.starts_with("head.") {
            head.extend_from_slice(&header);
            head.extend_from_slice(&raw);
            cost.head_parameter_bytes += raw.len() as u64;
        }
        arrays.insert(name, values);
    }
    let parameter_digest = Digest32::of_bytes(&parameters);
    if digest(&wire.parameter_sha256)? != parameter_digest { return Err(BindingMismatch); }
    let mut features = BTreeMap::new();
    for (key, feature) in wire.features {
        digest(&feature.canonical_text_sha256)?;
        let (values, raw) = decode(&feature.f32le_hex, wire.dimension)?;
        if digest(&feature.feature_sha256)? != Digest32::of_bytes(&raw) { return Err(BindingMismatch); }
        if values.iter().any(|value| !(-1.0..=1.0).contains(value)) { return Err(InvalidArtifact); }
        cost.feature_bytes += raw.len() as u64;
        features.insert(key, values);
    }
    Ok(ResidualData {
        kind: wire.kind, digest: expected, parameter_digest,
        head_digest: Digest32::of_parts(&[b"hepta.memory.residual-head.v1",
            output_profile.as_bytes(), encoder_digest.as_array(), &head]),
        encoder_digest, owner_cut_digest, output_profile,
        minimum_margin: wire.minimum_margin, rank: wire.rank,
        supports: wire.supports, lineage: wire.lineage_sources, features,
        a: arrays.remove("A").ok_or(InvalidArtifact)?,
        b: arrays.remove("B").ok_or(InvalidArtifact)?,
        head_bias: arrays.remove("head.bias").ok_or(InvalidArtifact)?,
        head_weight: arrays.remove("head.weight").ok_or(InvalidArtifact)?, cost,
    })
}

fn decode(hex: &str, count: usize) -> Result<(Vec<f32>, Vec<u8>), AssociativeMemoryError> {
    let invalid = AssociativeMemoryError::InvalidArtifact;
    if Some(hex.len()) != count.checked_mul(8) { return Err(invalid); }
    let mut raw = Vec::with_capacity(count * 4);
    for pair in hex.as_bytes().chunks_exact(2) {
        let mut byte = 0;
        for nibble in pair {
            byte = byte * 16 + match nibble {
                b'0'..=b'9' => nibble - b'0', b'a'..=b'f' => nibble - b'a' + 10,
                _ => return Err(invalid),
            };
        }
        raw.push(byte);
    }
    let values: Vec<f32> = raw.chunks_exact(4).map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]])).collect();
    if values.iter().any(|value| !value.is_finite()) { return Err(invalid); }
    Ok((values, raw))
}

fn digest(value: &str) -> Result<Digest32, AssociativeMemoryError> {
    if value.len() != 64 || value.bytes().any(|b| !matches!(b, b'0'..=b'9' | b'a'..=b'f')) {
        return Err(AssociativeMemoryError::InvalidArtifact);
    }
    value.parse::<Digest32>().ok().filter(|d| !d.is_zero()).ok_or(AssociativeMemoryError::InvalidArtifact)
}

fn valid_sources(values: &[String], cap: usize) -> bool {
    !values.is_empty() && values.len() <= cap && values.iter().all(|v| digest(v).is_ok())
        && values.windows(2).all(|pair| pair[0] < pair[1])
}

fn encoded_len<T: Serialize>(value: &T) -> Result<u64, AssociativeMemoryError> {
    serde_json::to_vec(value).map(|v| v.len() as u64).map_err(|_| AssociativeMemoryError::InvalidArtifact)
}

fn unique_map<'de, D, T>(deserializer: D) -> Result<BTreeMap<String, T>, D::Error>
where D: Deserializer<'de>, T: Deserialize<'de> {
    struct Unique<T>(PhantomData<T>);
    impl<'de, T: Deserialize<'de>> Visitor<'de> for Unique<T> {
        type Value = BTreeMap<String, T>;
        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("an object with unique keys")
        }
        fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
            let mut values = BTreeMap::new();
            while let Some((key, value)) = map.next_entry::<String, T>()? {
                if values.insert(key, value).is_some() {
                    return Err(serde::de::Error::custom("duplicate residual map key"));
                }
            }
            Ok(values)
        }
    }
    deserializer.deserialize_map(Unique(PhantomData))
}
