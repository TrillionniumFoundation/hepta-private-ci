//! Versioned nonlinear parameter payload. Features are a declared immutable
//! encoder cache, never answer records. The host authenticates current sources;
//! a training-receipt digest binds evidence but does not prove model quality.

use std::collections::BTreeMap;
use std::fmt;
use std::marker::PhantomData;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryPolicyV1;
use codex_hepta_cognitive_types::MemoryInventoryProgramV1;
use codex_hepta_cognitive_types::MemoryInventoryValueV1;
use codex_hepta_neuron::MemoryResidualAbstentionV1;
use codex_hepta_neuron::MemoryResidualPredictionV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::MapAccess;
use serde::de::Visitor;

pub(crate) const SCHEMA: &str = "hepta.memory.mlp-native.v12";
const ADDRESS: &str = "hepta.memory.frozen-feature-cache.v12";
const NUMERIC: &str = "hepta.memory.f32-f64-relu-mlp.v12";
const MAX_BYTES: usize = 32 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Tensor {
    shape: Vec<usize>,
    f32le_hex: String,
}

#[derive(Deserialize)]
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
    hidden: usize,
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

pub(crate) struct MemoryMlpCellV12 {
    wire: Wire,
    pub digest: Digest32,
    pub parameters_digest: Digest32,
    pub head_digest: Digest32,
    pub encoder_digest: Digest32,
    pub owner_cut_digest: Digest32,
    features: BTreeMap<String, Vec<f32>>,
    arrays: BTreeMap<String, Vec<f32>>,
}

impl MemoryMlpCellV12 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES || Digest32::of_bytes(bytes) != expected {
            return Err("V12 MLP payload size or digest mismatch".to_string());
        }
        let mut wire: Wire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        let (width, profile) = match wire.kind {
            MemoryCellKindV1::Semantic => (12, "hepta.memory.inventory-policy.bits12.v1"),
            MemoryCellKindV1::Procedure => (28, "hepta.memory.inventory-program.ops4x7.v1"),
            MemoryCellKindV1::Event => return Err("V12 event prediction forbidden".to_string()),
        };
        if wire.schema != SCHEMA || wire.address_profile != ADDRESS || wire.numeric_profile != NUMERIC
            || wire.output_profile != profile || !(1..=384).contains(&wire.dimension)
            || !(1..=256).contains(&wire.hidden) || wire.arrays.len() != 4
            || !(1..=4096).contains(&wire.supports.len())
            || !wire.features.keys().eq(wire.supports.keys())
            || !wire.minimum_margin.is_finite() || !(0.0..=1_000_000.0).contains(&wire.minimum_margin)
            || wire.minimum_margin == 0.0 || !valid_sources(&wire.lineage_sources)
        {
            return Err("V12 MLP profile, dimensions or dependencies invalid".to_string());
        }
        let encoder_digest = digest(&wire.encoder_sha256)?;
        let owner_cut_digest = digest(&wire.owner_cut_sha256)?;
        digest(&wire.checkpoint_sha256)?;
        digest(&wire.training_receipt_sha256)?;
        for (key, sources) in &wire.supports {
            digest(key)?;
            if sources.len() != 1 || !valid_sources(sources)
                || sources.iter().any(|source| wire.lineage_sources.binary_search(source).is_err())
            {
                return Err("V12 MLP invalid support lineage".to_string());
            }
        }
        let mut arrays = BTreeMap::new();
        let mut parameters = Vec::new();
        let mut head = Vec::new();
        for (name, shape) in [
            ("head.bias", vec![width]),
            ("head.weight", vec![width, wire.hidden]),
            ("hidden.bias", vec![wire.hidden]),
            ("hidden.weight", vec![wire.hidden, wire.dimension]),
        ] {
            let tensor = wire.arrays.get(name).ok_or("V12 MLP tensor missing")?;
            if tensor.shape != shape { return Err("V12 MLP tensor shape differs".to_string()); }
            let (values, raw) = decode(&tensor.f32le_hex, shape.iter().product())?;
            let header = serde_json::to_vec(&(name, &shape, "float32")).map_err(|error| error.to_string())?;
            parameters.extend_from_slice(&header);
            parameters.extend_from_slice(&raw);
            if name.starts_with("head.") {
                head.extend_from_slice(&header);
                head.extend_from_slice(&raw);
            }
            arrays.insert(name.to_string(), values);
        }
        let parameters_digest = Digest32::of_bytes(&parameters);
        if digest(&wire.parameter_sha256)? != parameters_digest {
            return Err("V12 MLP parameter digest differs".to_string());
        }
        let mut features = BTreeMap::new();
        for (address, feature) in &wire.features {
            digest(&feature.canonical_text_sha256)?;
            let (values, raw) = decode(&feature.f32le_hex, wire.dimension)?;
            if digest(&feature.feature_sha256)? != Digest32::of_bytes(&raw)
                || values.iter().any(|value| !(-1.0..=1.0).contains(value))
            {
                return Err("V12 MLP feature binding or range differs".to_string());
            }
            features.insert(address.clone(), values);
        }
        // The selected envelope already retains exact original bytes for wake.
        // Keep only decoded tensors, rather than another hex cache, in memory.
        wire.arrays.clear();
        wire.features.clear();
        Ok(Self {
            wire, digest: expected, parameters_digest, encoder_digest, owner_cut_digest,
            head_digest: Digest32::of_parts(&[b"hepta.memory.mlp-head.v12", profile.as_bytes(), encoder_digest.as_array(), &head]),
            arrays, features,
        })
    }

    pub fn kind(&self) -> MemoryCellKindV1 { self.wire.kind }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> { &self.wire.supports }
    pub fn lineage_sources(&self) -> &[String] { &self.wire.lineage_sources }
    pub fn output_profile(&self) -> &str { &self.wire.output_profile }
    pub fn numeric_profile(&self) -> &str { NUMERIC }
    pub fn address_profile(&self) -> &str { ADDRESS }

    pub fn predict(&self, key: &str) -> Result<MemoryResidualPredictionV1, String> {
        if key.is_empty() || key.len() > 4096 { return Err("V12 MLP query bound".to_string()); }
        let mut result = MemoryResidualPredictionV1 {
            kind: self.kind(), value: None, logits: Vec::new(), minimum_margin: 0.0,
            source_ids: Vec::new(), artifact_digest: self.digest.to_string(),
            parameter_digest: self.parameters_digest.to_string(),
            abstain: Some(MemoryResidualAbstentionV1::OutsideWrittenSupport),
        };
        let address = Digest32::of_bytes(key.as_bytes()).to_string();
        let Some(sources) = self.supports().get(&address) else { return Ok(result); };
        let features = self.features.get(&address).ok_or("V12 MLP missing features")?;
        let mut hidden: Vec<f64> = self.arrays["hidden.bias"].iter().copied().map(f64::from).collect();
        for (row, value) in hidden.iter_mut().enumerate() {
            for (column, feature) in features.iter().enumerate() {
                *value += f64::from(self.arrays["hidden.weight"][row * self.wire.dimension + column]) * f64::from(*feature);
            }
            *value = value.max(0.0);
        }
        result.logits = self.arrays["head.bias"].iter().copied().map(f64::from).collect();
        for (row, value) in result.logits.iter_mut().enumerate() {
            for (column, feature) in hidden.iter().enumerate() {
                *value += f64::from(self.arrays["head.weight"][row * self.wire.hidden + column]) * feature;
            }
        }
        if result.logits.iter().any(|value| !value.is_finite()) {
            return Err("V12 MLP nonfinite inference".to_string());
        }
        let value = match self.kind() {
            MemoryCellKindV1::Semantic => {
                result.minimum_margin = result.logits.iter().map(|value| value.abs()).fold(f64::INFINITY, f64::min);
                let mut values = [0_u8; 3];
                for (group, value) in values.iter_mut().enumerate() {
                    for bit in 0..4 {
                        if result.logits[4 * group + bit] >= 0.0 { *value |= 1 << bit; }
                    }
                }
                MemoryInventoryValueV1::Semantic(MemoryInventoryPolicyV1 { reserve: values[0], pack: values[1], limit: values[2] })
            }
            MemoryCellKindV1::Procedure => {
                let mut opcodes = [0_u8; 4];
                result.minimum_margin = f64::INFINITY;
                for (group, opcode) in opcodes.iter_mut().enumerate() {
                    let scores = &result.logits[7 * group..7 * (group + 1)];
                    let mut winner = 0;
                    for index in 1..7 { if scores[index] > scores[winner] { winner = index; } }
                    let runner = scores.iter().enumerate().filter(|(index, _)| *index != winner).map(|(_, value)| *value).fold(f64::NEG_INFINITY, f64::max);
                    result.minimum_margin = result.minimum_margin.min(scores[winner] - runner);
                    *opcode = winner as u8;
                }
                MemoryInventoryValueV1::Procedure(MemoryInventoryProgramV1 { opcodes })
            }
            MemoryCellKindV1::Event => return Err("V12 MLP event prediction forbidden".to_string()),
        };
        result.abstain = Some(MemoryResidualAbstentionV1::BelowSelectionMargin);
        if result.minimum_margin >= self.wire.minimum_margin {
            result.value = Some(value);
            result.source_ids.clone_from(sources);
            result.abstain = None;
        }
        Ok(result)
    }
}

fn decode(hex: &str, count: usize) -> Result<(Vec<f32>, Vec<u8>), String> {
    if Some(hex.len()) != count.checked_mul(8) { return Err("V12 MLP tensor byte count".to_string()); }
    let mut raw = Vec::with_capacity(count * 4);
    for pair in hex.as_bytes().chunks_exact(2) {
        let mut byte = 0;
        for nibble in pair {
            byte = byte * 16 + match nibble {
                b'0'..=b'9' => nibble - b'0', b'a'..=b'f' => nibble - b'a' + 10,
                _ => return Err("V12 MLP hex encoding".to_string()),
            };
        }
        raw.push(byte);
    }
    let values: Vec<f32> = raw.chunks_exact(4).map(|bytes| f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])).collect();
    if values.iter().any(|value| !value.is_finite()) { return Err("V12 MLP nonfinite parameters".to_string()); }
    Ok((values, raw))
}

fn digest(value: &str) -> Result<Digest32, String> {
    if value.len() != 64 || value.bytes().any(|byte| !matches!(byte, b'0'..=b'9' | b'a'..=b'f')) {
        return Err("V12 MLP digest encoding".to_string());
    }
    value.parse::<Digest32>().ok().filter(|digest| !digest.is_zero()).ok_or_else(|| "V12 MLP empty digest".to_string())
}

fn valid_sources(values: &[String]) -> bool {
    !values.is_empty() && values.len() <= 4096 && values.iter().all(|value| digest(value).is_ok())
        && values.windows(2).all(|pair| pair[0] < pair[1])
}

fn unique_map<'de, D, T>(deserializer: D) -> Result<BTreeMap<String, T>, D::Error>
where D: Deserializer<'de>, T: Deserialize<'de> {
    struct Unique<T>(PhantomData<T>);
    impl<'de, T: Deserialize<'de>> Visitor<'de> for Unique<T> {
        type Value = BTreeMap<String, T>;
        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("an object with unique MLP keys")
        }
        fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
            let mut values = BTreeMap::new();
            while let Some((key, value)) = map.next_entry::<String, T>()? {
                if values.insert(key, value).is_some() { return Err(serde::de::Error::custom("duplicate MLP map key")); }
            }
            Ok(values)
        }
    }
    deserializer.deserialize_map(Unique(PhantomData))
}
