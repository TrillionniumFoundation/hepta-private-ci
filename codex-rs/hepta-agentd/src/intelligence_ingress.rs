//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

/// Exact durable ObjectiveStart identity inherited by the prepared run.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRunStartBindingV1 {
    pub request_digest: Digest32,
    pub runtime_body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub fence_digest: Digest32,
    pub run_start_binding_digest: Digest32,
    pub generation: u64,
    pub deadline_ms: u64,
}

impl AgentdIntelligenceRunStartBindingV1 {
    pub fn from_record(record: &RunStartRecordV1) -> Result<Self, AgentdError> {
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or_else(|| AgentdError::Invalid("objective deadline overflow".to_string()))?;
        if record.snapshot.generation == 0 || deadline_ms == 0 {
            return Err(AgentdError::Invalid(
                "objective run-start generation or deadline is invalid".to_string(),
            ));
        }
        Ok(Self {
            request_digest: record.admission.admitted_source_digest,
            runtime_body_digest: record.runtime_body_digest,
            artifact_set_digest: record.snapshot.artifact_set_digest,
            fence_digest: record.snapshot.fence_digest,
            run_start_binding_digest: run_start_binding_digest(record)?,
            generation: record.snapshot.generation,
            deadline_ms,
        })
    }
}

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
        let run_start = AgentdIntelligenceRunStartBindingV1::from_record(record)?;
        let expected_fence = crate::lane_b_runtime::run_fence_digest(
            identity.agent_id.as_str(),
            identity.spawn_generation,
            snapshot.generation,
        );
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || self.request.run_id != snapshot.run_id
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.snapshot.configuration_digest() != run_start.run_start_binding_digest
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || self.inputs.run_start != run_start
            || run_start.fence_digest.to_string() != expected_fence
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

fn run_start_binding_digest(record: &RunStartRecordV1) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.agentd.intelligence-run-start-binding.v1\0".to_vec();
    push_id(&mut bytes, &record.snapshot.run_id)?;
    for digest in [
        record.snapshot.objective_digest,
        record.snapshot.hard_constraint_digest,
        record.snapshot.preference_state_digest,
        record.snapshot.model_tuple_digest,
        record.snapshot.prompt_registry_digest,
        record.snapshot.artifact_set_digest,
        record.snapshot.fence_digest,
        record.runtime_body_digest,
        record.admission.profile_digest,
        record.admission.supplied_source_digest,
        record.admission.intent_digest,
        record.admission.admitted_source_digest,
        record.objective_function_v1_digest,
        record.authentication.scope_digest,
        record.authentication.signed_body_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &record.admission.profile_id)?;
    bytes.extend_from_slice(&record.admission.profile_revision.to_be_bytes());
    bytes.extend_from_slice(&record.admission.observed_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&record.admission.deadline_unix_micros.to_be_bytes());
    bytes.push(u8::from(record.admission.authority.grants_any()));
    bytes.extend_from_slice(&record.snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    push_id(&mut bytes, &record.authentication.issuer_id)?;
    bytes.extend_from_slice(&record.authentication.key_epoch.to_be_bytes());
    push_id(&mut bytes, &record.authentication.message_id)?;
    bytes.extend_from_slice(&record.authentication.sequence.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.signature);
    bytes.push(match record.disposition {
        RunStartObjectiveDispositionV1::Compiled => 0,
        RunStartObjectiveDispositionV1::ExplicitAbstain => 1,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| AgentdError::Invalid("run-start identity is too long".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}
