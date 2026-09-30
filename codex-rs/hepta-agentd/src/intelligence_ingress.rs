//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_agent_components::intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;
pub use crate::intelligence_run_identity::AgentdIntelligenceRunIdentityV1;

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
        let expected = AgentdIntelligenceRunIdentityV1::from_run_start(identity, record)?;
        let Some(actual) = self.inputs.run_identity.as_ref() else {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation omitted durable RunStart identity".to_string(),
            ));
        };
        if actual != &expected {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation substituted durable RunStart identity"
                    .to_string(),
            ));
        }
        actual.validate_request(&self.request)
    }
}

pub(crate) fn running_generation(spawn_generation: u64) -> Result<u64, AgentdError> {
    spawn_generation
        .checked_add(1)
        .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))
}

pub(crate) use crate::intelligence_run_identity::objective_run_fence_digest_v1;

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
