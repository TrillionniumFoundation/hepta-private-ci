//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective.  It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material.  A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartRecordV1;

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
        let running_generation = identity.spawn_generation.checked_add(1).ok_or_else(|| {
            AgentdError::Invalid("canonical intelligence lifecycle generation overflow".to_string())
        })?;
        if self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            // The immutable Body names the process; RunStart names its Running
            // Fleet epoch. Neither generation may substitute for the other.
            || self.request.snapshot.body_generation().get() != identity.spawn_generation
            || canonical_runtime_body_digest(&self.request.snapshot) != record.runtime_body_digest
            || self.request.snapshot.digest() != snapshot.artifact_set_digest
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || snapshot.generation != running_generation
            || snapshot.fence_digest.to_string()
                != crate::state::objective_run_fence(identity, running_generation)
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

pub(crate) fn canonical_runtime_body_digest(
    snapshot: &codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1,
) -> codex_hepta_types::Digest32 {
    let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
    body.extend_from_slice(snapshot.digest().as_array());
    body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
    codex_hepta_types::Digest32::of_bytes(&body)
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
