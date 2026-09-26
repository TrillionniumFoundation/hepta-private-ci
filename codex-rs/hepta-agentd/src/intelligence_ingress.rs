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

/// Exact durable RunStart identity inherited by the prepared intelligence run.
///
/// The request digest is a domain-separated digest of the complete immutable
/// RunStart publication, not a digest reconstructed by the cognition runner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRunIdentityV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub objective_digest: Digest32,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
    pub deadline_ms: u64,
}

impl AgentdIntelligenceRunIdentityV1 {
    /// Derive the only accepted physical-run identity from the durable record.
    pub fn from_run_start(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<Self, AgentdError> {
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || record.admission.authority.grants_any()
            || record.snapshot.objective_digest.is_zero()
            || record.runtime_body_digest.is_zero()
            || record.snapshot.artifact_set_digest.is_zero()
            || record.snapshot.authority_epoch == 0
            || record.snapshot.generation == 0
            || record.objective_semantic_bytes.is_empty()
            || record.objective_function_v1_bytes.is_empty()
            || record.objective_function_v1_digest.is_zero()
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence requires one complete deny-all compiled RunStart"
                    .to_string(),
            ));
        }
        let running_generation = identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))?;
        if record.snapshot.generation != running_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "canonical intelligence RunStart generation {} does not match Running generation {running_generation}",
                record.snapshot.generation
            )));
        }
        let expected_fence = objective_run_fence_digest_v1(
            identity.agent_id.as_str(),
            identity.spawn_generation,
            record.snapshot.generation,
        );
        if record.snapshot.fence_digest != expected_fence {
            return Err(AgentdError::GenerationFenced(
                "canonical intelligence RunStart fence does not match agent process identity"
                    .to_string(),
            ));
        }
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .filter(|value| *value != 0)
            .ok_or_else(|| AgentdError::Invalid("RunStart deadline overflow".to_string()))?;
        Ok(Self {
            run_id: record.snapshot.run_id.clone(),
            request_digest: run_start_identity_digest_v1(record)?,
            objective_digest: record.snapshot.objective_digest,
            body_digest: record.runtime_body_digest,
            artifact_set_digest: record.snapshot.artifact_set_digest,
            authority_epoch: record.snapshot.authority_epoch,
            generation: record.snapshot.generation,
            fence_digest: record.snapshot.fence_digest,
            deadline_ms,
        })
    }

    pub(crate) fn validate_process_binding(
        &self,
        agent_id: &str,
        spawn_generation: u64,
    ) -> Result<(), AgentdError> {
        let running_generation = spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))?;
        if self.generation != running_generation
            || self.fence_digest
                != objective_run_fence_digest_v1(agent_id, spawn_generation, self.generation)
        {
            return Err(AgentdError::GenerationFenced(
                "prepared intelligence run is not bound to this Agentd generation".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn validate_request(
        &self,
        request: &CanonicalIntelligenceRunRequestV1,
    ) -> Result<(), AgentdError> {
        if self.run_id != request.run_id
            || self.objective_digest != request.snapshot.objective_digest()
            || self.authority_epoch != request.snapshot.authority_epoch()
            || self.generation != request.snapshot.body_generation().get()
            || self.objective_digest != request.legal_candidates.state_digest
        {
            return Err(AgentdError::Invalid(
                "canonical request does not inherit its durable RunStart identity".to_string(),
            ));
        }
        Ok(())
    }
}

/// One canonical fence algorithm for ObjectiveStart publication, invocation
/// validation, runner preparation and coordinator-bound admission.
#[must_use]
pub fn objective_run_fence_digest_v1(
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

fn run_start_identity_digest_v1(record: &RunStartRecordV1) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.agentd.intelligence-run-start-identity.v1\0".to_vec();
    push_id(&mut bytes, &record.authentication.issuer_id)?;
    bytes.extend_from_slice(&record.authentication.key_epoch.to_be_bytes());
    push_id(&mut bytes, &record.authentication.message_id)?;
    bytes.extend_from_slice(&record.authentication.sequence.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(record.authentication.scope_digest.as_array());
    bytes.extend_from_slice(record.authentication.signed_body_digest.as_array());
    bytes.extend_from_slice(&record.authentication.signature);

    push_id(&mut bytes, &record.admission.profile_id)?;
    bytes.extend_from_slice(&record.admission.profile_revision.to_be_bytes());
    for digest in [
        record.admission.profile_digest,
        record.admission.supplied_source_digest,
        record.admission.intent_digest,
        record.admission.admitted_source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&record.admission.observed_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&record.admission.deadline_unix_micros.to_be_bytes());

    push_id(&mut bytes, &record.snapshot.run_id)?;
    for digest in [
        record.snapshot.objective_digest,
        record.snapshot.hard_constraint_digest,
        record.snapshot.preference_state_digest,
        record.snapshot.model_tuple_digest,
        record.snapshot.prompt_registry_digest,
        record.snapshot.artifact_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&record.snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    bytes.extend_from_slice(record.snapshot.fence_digest.as_array());
    bytes.extend_from_slice(record.runtime_body_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&record.objective_semantic_bytes).as_array());
    bytes.extend_from_slice(record.objective_function_v1_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&record.objective_function_v1_bytes).as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| AgentdError::Invalid("stable identity is too large".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
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

/// Concrete host-owned provider backed by one typed factory.
///
/// The factory supplies the seven owner values. The provider itself overwrites
/// the run identity with the exact durable RunStart binding, validates the final
/// invocation and only then returns it to Agentd.
pub struct HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    factory: F,
}

impl<F> HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    #[must_use]
    pub const fn new(factory: F) -> Self {
        Self { factory }
    }
}

impl<F> AgentdIntelligenceInvocationProviderV1
    for HostOwnedAgentdIntelligenceInvocationProviderV1<F>
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send
        + Sync,
{
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let mut invocation = (self.factory)(identity, record)?;
        invocation.inputs.run_identity = Some(AgentdIntelligenceRunIdentityV1::from_run_start(
            identity, record,
        )?);
        invocation.validate(identity, record)?;
        Ok(invocation)
    }
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object
/// and therefore cannot substitute policy, model, artifact, trust, currentness
/// or physical-run identity inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}
