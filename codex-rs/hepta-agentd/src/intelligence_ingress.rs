//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective.  It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material.  A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
}

impl AgentdIntelligenceInvocationV1 {
    /// Bind the original run's selected configuration and admission horizon.
    /// This digest is an identity, not authentication or selection authority.
    pub fn configuration_digest(record: &RunStartRecordV1) -> Digest32 {
        let snapshot = &record.snapshot;
        let run = snapshot.run_id.as_str().as_bytes();
        Digest32::of_parts(&[
            b"hepta.agentd.run-start-configuration.v1\0",
            &(run.len() as u64).to_be_bytes(),
            run,
            snapshot.objective_digest.as_array(),
            snapshot.hard_constraint_digest.as_array(),
            snapshot.preference_state_digest.as_array(),
            snapshot.model_tuple_digest.as_array(),
            snapshot.prompt_registry_digest.as_array(),
            snapshot.artifact_set_digest.as_array(),
            record.runtime_body_digest.as_array(),
            record.objective_function_v1_digest.as_array(),
            record.admission.profile_digest.as_array(),
            record.admission.admitted_source_digest.as_array(),
            record.authentication.signed_body_digest.as_array(),
            snapshot.fence_digest.as_array(),
            &snapshot.authority_epoch.to_be_bytes(),
            &snapshot.generation.to_be_bytes(),
            &record.admission.deadline_unix_micros.to_be_bytes(),
            &record.authentication.expires_at_ms.to_be_bytes(),
        ])
    }

    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let snapshot = &record.snapshot;
        if self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || snapshot.generation != identity.spawn_generation
            || self.request.snapshot.configuration_digest() != Self::configuration_digest(record)
            || self.inputs.neural_tick.body_digest != record.runtime_body_digest
            || self.inputs.prompt_request.registry_snapshot_digest
                != snapshot.prompt_registry_digest
            || self.inputs.objective_envelope.intent_digest != record.admission.intent_digest
            || self.inputs.objective_context.selected_profile_digest
                != record.admission.profile_digest
            || self.inputs.objective_profile.digest().ok() != Some(record.admission.profile_digest)
            || !matches!(&self.inputs.objective_context.source_authentication,
                ObjectiveSourceAuthenticationV1::AuthorizedAdapter { source_identity, source_digest }
                    if source_identity == &record.authentication.issuer_id
                        && source_digest == &record.admission.supplied_source_digest)
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners.  Request/wire callers cannot provide this
/// object and therefore cannot substitute policy, model, artifact, trust, or
/// currentness inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}
