//! Full original port input bytes; decoding grants no execution or admission.
use crate::CanonicalIntelligenceError;
use crate::CanonicalPortInputV1;
use crate::CanonicalStageV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1: usize = 16 * 1024;
const SCHEMA: &str = "hepta.intelligence.canonical-port-input-material.v1";
#[derive(Serialize, Deserialize)]
#[serde(remote = "CanonicalStageV1", rename_all = "snake_case")]
enum Stage {
    ObjectiveValidated,
    UtilityEvaluated,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    EvaluationAdmitted,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CanonicalPortInputV1", deny_unknown_fields)]
struct Port {
    #[serde(with = "id")]
    run_id: StableId,
    #[serde(with = "digest")]
    snapshot_digest: Digest32,
    #[serde(with = "digest")]
    objective_digest: Digest32,
    #[serde(with = "digest")]
    candidate_set_digest: Digest32,
    #[serde(with = "digest")]
    predecessor_digest: Digest32,
    budget_micros: u64,
    #[serde(with = "Stage")]
    stage: CanonicalStageV1,
}
#[derive(Serialize)]
struct Borrowed<'a> {
    schema: &'static str,
    #[serde(with = "Port")]
    port: &'a CanonicalPortInputV1,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Owned {
    schema: String,
    #[serde(with = "Port")]
    port: CanonicalPortInputV1,
}
fn invalid() -> CanonicalIntelligenceError {
    CanonicalIntelligenceError::InvalidSnapshot("canonical port material")
}
pub fn encode_canonical_port_input_material_v1(
    input: &CanonicalPortInputV1,
) -> Result<Vec<u8>, CanonicalIntelligenceError> {
    let bytes = serde_json::to_vec(&Borrowed {
        schema: SCHEMA,
        port: input,
    })
    .map_err(|_| invalid())?;
    if bytes.len() > MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1 {
        return Err(invalid());
    }
    Ok(bytes)
}
pub fn decode_canonical_port_input_material_v1(
    bytes: &[u8],
) -> Result<CanonicalPortInputV1, CanonicalIntelligenceError> {
    if bytes.is_empty() || bytes.len() > MAX_CANONICAL_PORT_INPUT_MATERIAL_BYTES_V1 {
        return Err(invalid());
    }
    let owned: Owned = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if owned.schema != SCHEMA || encode_canonical_port_input_material_v1(&owned.port)? != bytes {
        return Err(invalid());
    }
    Ok(owned.port)
}
mod id {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &StableId,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(value.as_str())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<StableId, D::Error> {
        StableId::new(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}
mod digest {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Digest32,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.to_string())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Digest32, D::Error> {
        let text = String::deserialize(deserializer)?;
        let value: Digest32 = text.parse().map_err(serde::de::Error::custom)?;
        if value.to_string() != text {
            return Err(serde::de::Error::custom("noncanonical port digest"));
        }
        Ok(value)
    }
}
#[cfg(test)]
#[path = "canonical_port_material_v1_tests.rs"]
mod tests;
