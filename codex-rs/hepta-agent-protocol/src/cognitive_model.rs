//! Read-only installation observations from the actual generation-bound ranker.
//! A successful readback revalidates CURRENT and selection lifetime. It neither
//! grants final use nor promises that the model will remain current afterward.

use serde::Deserialize;
use serde::Serialize;

pub const COGNITIVE_MODEL_STATUS_CAPABILITY: &str = "cognitive.model.status";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveModelIdentity {
    pub artifact_id: String,
    pub artifact_generation: u64,
    pub payload_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveModelReadback {
    pub spawn_generation: u64,
    pub model: CognitiveModelIdentity,
    pub source_manifest_sha256: Option<String>,
    pub selection_sha256: Option<String>,
    pub evaluated_predecessor: Option<CognitiveModelIdentity>,
    pub current_owner_trust_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveModelStatus {
    /// None means this generation has no configured learned ranker. A configured
    /// ranker that fails revalidation returns a control error instead of None.
    pub installed: Option<CognitiveModelReadback>,
}

impl crate::AgentdRequest {
    pub fn cognitive_model_status(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: crate::AgentdMethod::CognitiveModelStatus,
        }
    }
}
