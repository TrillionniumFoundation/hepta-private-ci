//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_agent_components::intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agent_components::types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
}

impl AgentdIntelligenceInvocationV1 {
    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let snapshot = &record.snapshot;
        let running_generation = running_generation(identity.spawn_generation)?;
        if self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || snapshot.generation != running_generation
            || snapshot.fence_digest
                != objective_run_fence_digest_v1(
                    identity.agent_id.as_str(),
                    identity.spawn_generation,
                    running_generation,
                )
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

fn running_generation(spawn_generation: u64) -> Result<u64, AgentdError> {
    spawn_generation
        .checked_add(1)
        .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))
}

/// One fence algorithm for ObjectiveStart publication and canonical preparation.
///
/// `spawn_generation` identifies the process launch. `current_generation` is
/// the Running Fleet lifecycle generation inherited by the durable RunStart.
pub(crate) fn objective_run_fence_digest_v1(
    agent_id: &str,
    spawn_generation: u64,
    current_generation: u64,
) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(agent_id.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object
/// and therefore cannot substitute policy, model, artifact, trust, or
/// currentness inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn running_generation_is_the_next_fleet_epoch() {
        assert_eq!(running_generation(7).expect("running generation"), 8);
        assert!(running_generation(u64::MAX).is_err());
    }

    #[test]
    fn objective_fence_binds_process_launch_and_current_generation_separately() {
        let expected = objective_run_fence_digest_v1("agent.example", 7, 8);
        assert_ne!(
            expected,
            objective_run_fence_digest_v1("agent.example", 8, 8)
        );
        assert_ne!(
            expected,
            objective_run_fence_digest_v1("agent.example", 7, 9)
        );
        assert_ne!(expected, objective_run_fence_digest_v1("agent.other", 7, 8));
    }
}
