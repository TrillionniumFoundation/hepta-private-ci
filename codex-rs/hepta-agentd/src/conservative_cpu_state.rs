//! Closed state of the abstention-only CPU composition. No active preference
//! update, prompt factor, model installation or answer permission is represented.
use codex_hepta_agent_components::ndu::AxisValue;
use codex_hepta_agent_components::ndu::PreferenceState;
use codex_hepta_agent_components::ndu::SubjectClass;
use codex_hepta_agent_components::prompt_registry::PromptRegistry;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ConservativeCpuStateModeV1 {
    InactiveForConservativeAbstentionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConservativeCpuStateV1 {
    subject_id: StableId,
    preference: PreferenceState,
    prompt_registry_digest: Digest32,
    artifact_set_digest: Digest32,
}

impl ConservativeCpuStateV1 {
    /// The three payload hashes are supplied by the opaque, currently verified
    /// installed E/S/CURRENT reader. This value itself grants no authority.
    pub fn from_current_payloads(
        subject_id: StableId,
        payload_digests: [Digest32; 3],
    ) -> Result<Self, AgentdError> {
        if payload_digests.iter().any(|digest| digest.is_zero()) {
            return Err(AgentdError::Invalid("missing installed CPU payload".into()));
        }
        let preference = PreferenceState::genesis(
            subject_id.clone(),
            SubjectClass::Agent,
            vec![AxisValue {
                axis: StableId::new("utility.safe-abstain")
                    .map_err(|error| AgentdError::Invalid(error.to_string()))?,
                value: FixedQ32::ZERO,
            }],
        )
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let mut bytes = b"hepta.agentd.conservative-current-cpu-payload-set.v1\0".to_vec();
        for payload in payload_digests {
            bytes.extend_from_slice(payload.as_array());
        }
        Ok(Self {
            subject_id,
            preference,
            prompt_registry_digest: PromptRegistry::canonical_empty_snapshot_digest()
                .map_err(|error| AgentdError::Invalid(error.to_string()))?,
            artifact_set_digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }
    pub fn preference_state_digest(&self) -> Digest32 {
        self.preference.state_digest
    }
    pub fn prompt_registry_digest(&self) -> Digest32 {
        self.prompt_registry_digest
    }
    pub fn artifact_set_digest(&self) -> Digest32 {
        self.artifact_set_digest
    }
    pub fn mode(&self) -> ConservativeCpuStateModeV1 {
        ConservativeCpuStateModeV1::InactiveForConservativeAbstentionV1
    }
}
