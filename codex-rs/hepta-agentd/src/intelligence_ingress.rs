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
use crate::AgentdIntelligenceDecisionPlanV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdIntelligenceOwnerInputsV1;
use crate::agentd_objective_fence;

/// Exact durable identity inherited by a prepared canonical intelligence run.
///
/// Every field is copied from the already-authenticated `RunStartRecordV1`.
/// The canonical runner may derive additional advisory receipts, but it may not
/// replace the request, body, artifact, deadline, generation or fence identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdRunStartBindingV1 {
    run_id: StableId,
    request_digest: Digest32,
    objective_digest: Digest32,
    hard_constraint_digest: Digest32,
    preference_state_digest: Digest32,
    model_tuple_digest: Digest32,
    prompt_registry_digest: Digest32,
    artifact_set_digest: Digest32,
    runtime_body_digest: Digest32,
    objective_function_v1_digest: Digest32,
    profile_digest: Digest32,
    intent_digest: Digest32,
    authority_epoch: u64,
    generation: u64,
    fence_digest: Digest32,
    deadline_ms: u64,
    binding_digest: Digest32,
}

impl AgentdRunStartBindingV1 {
    pub fn from_record(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<Self, AgentdError> {
        validate_record_identity(identity, record)?;
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or_else(|| AgentdError::Invalid("run-start deadline overflow".to_string()))?;
        let snapshot = &record.snapshot;
        let mut bytes = b"hepta.agentd.intelligence-run-start-binding.v1\0".to_vec();
        push_id(&mut bytes, &snapshot.run_id)?;
        for digest in [
            record.admission.admitted_source_digest,
            snapshot.objective_digest,
            snapshot.hard_constraint_digest,
            snapshot.preference_state_digest,
            snapshot.model_tuple_digest,
            snapshot.prompt_registry_digest,
            snapshot.artifact_set_digest,
            record.runtime_body_digest,
            record.objective_function_v1_digest,
            record.admission.profile_digest,
            record.admission.intent_digest,
            snapshot.fence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
        bytes.extend_from_slice(&deadline_ms.to_be_bytes());
        Ok(Self {
            run_id: snapshot.run_id.clone(),
            request_digest: record.admission.admitted_source_digest,
            objective_digest: snapshot.objective_digest,
            hard_constraint_digest: snapshot.hard_constraint_digest,
            preference_state_digest: snapshot.preference_state_digest,
            model_tuple_digest: snapshot.model_tuple_digest,
            prompt_registry_digest: snapshot.prompt_registry_digest,
            artifact_set_digest: snapshot.artifact_set_digest,
            runtime_body_digest: record.runtime_body_digest,
            objective_function_v1_digest: record.objective_function_v1_digest,
            profile_digest: record.admission.profile_digest,
            intent_digest: record.admission.intent_digest,
            authority_epoch: snapshot.authority_epoch,
            generation: snapshot.generation,
            fence_digest: snapshot.fence_digest,
            deadline_ms,
            binding_digest: Digest32::of_bytes(&bytes),
        })
    }

    fn validate_record(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let current = Self::from_record(identity, record)?;
        if self != &current {
            return Err(AgentdError::Invalid(
                "canonical intelligence run-start binding changed after construction".to_string(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn body_digest(&self) -> Digest32 {
        self.runtime_body_digest
    }

    #[must_use]
    pub const fn artifact_set_digest(&self) -> Digest32 {
        self.artifact_set_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn fence_digest(&self) -> Digest32 {
        self.fence_digest
    }

    #[must_use]
    pub const fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.binding_digest
    }
}

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
    run_start: AgentdRunStartBindingV1,
    decision_plan: Option<AgentdIntelligenceDecisionPlanV1>,
}

impl AgentdIntelligenceInvocationV1 {
    /// Compatibility constructor for focused source tests. Product capability
    /// advertisement requires `new_product` and a durable learning host.
    pub fn new(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<Self, AgentdError> {
        Self::construct(identity, record, request, inputs, None)
    }

    pub fn new_product(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        decision_plan: AgentdIntelligenceDecisionPlanV1,
    ) -> Result<Self, AgentdError> {
        Self::construct(identity, record, request, inputs, Some(decision_plan))
    }

    fn construct(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        decision_plan: Option<AgentdIntelligenceDecisionPlanV1>,
    ) -> Result<Self, AgentdError> {
        let value = Self {
            request,
            inputs,
            run_start: AgentdRunStartBindingV1::from_record(identity, record)?,
            decision_plan,
        };
        value.validate(identity, record)?;
        Ok(value)
    }

    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        self.run_start.validate_record(identity, record)?;
        let snapshot = &record.snapshot;
        if self.request.run_id != snapshot.run_id
            || &self.request.run_id != self.run_start.run_id()
            || self.request.snapshot.objective_digest() != snapshot.objective_digest
            || self.request.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.request.snapshot.body_generation().get() != snapshot.generation
            || self.request.legal_candidates.state_digest != snapshot.objective_digest
            || self.run_start.objective_digest() != snapshot.objective_digest
            || self.run_start.authority_epoch() != snapshot.authority_epoch
            || self.run_start.generation() != snapshot.generation
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation does not match the durable RunStart identity"
                    .to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        CanonicalIntelligenceRunRequestV1,
        AgentdIntelligenceOwnerInputsV1,
        AgentdRunStartBindingV1,
        Option<AgentdIntelligenceDecisionPlanV1>,
    ) {
        (
            self.request,
            self.inputs,
            self.run_start,
            self.decision_plan,
        )
    }
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object
/// and therefore cannot substitute policy, model, artifact, trust, learning or
/// currentness inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    /// Stable digest of the host-owned provider profile. The default is
    /// deliberately invalid so capability advertisement fails closed for
    /// incomplete legacy implementations.
    fn profile_digest(&self) -> Digest32 {
        Digest32::ZERO
    }

    /// Product learning owner attached to this exact provider profile. A
    /// provider without it remains a compatibility/source-test profile.
    fn learning_host(&self) -> Option<std::sync::Arc<AgentdIntelligenceLearningHostV1>> {
        None
    }

    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;
}

fn validate_record_identity(
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
) -> Result<(), AgentdError> {
    let snapshot = &record.snapshot;
    let running_generation = identity
        .spawn_generation
        .checked_add(1)
        .ok_or_else(|| AgentdError::Invalid("spawn generation overflow".to_string()))?;
    let expected_fence = agentd_objective_fence(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        snapshot.generation,
    )
    .map_err(|error| AgentdError::Invalid(format!("run-start fence: {error:?}")))?;
    let required_digests = [
        record.admission.admitted_source_digest,
        snapshot.objective_digest,
        snapshot.hard_constraint_digest,
        snapshot.preference_state_digest,
        snapshot.model_tuple_digest,
        snapshot.prompt_registry_digest,
        snapshot.artifact_set_digest,
        record.runtime_body_digest,
        record.objective_function_v1_digest,
        record.admission.profile_digest,
        record.admission.intent_digest,
        snapshot.fence_digest,
    ];
    if record.disposition != RunStartObjectiveDispositionV1::Compiled
        || record.admission.authority.grants_any()
        || snapshot.authority_epoch == 0
        || snapshot.generation != running_generation
        || snapshot.fence_digest.to_string() != expected_fence
        || record.admission.deadline_unix_micros == 0
        || record.objective_function_v1_bytes.is_empty()
        || required_digests.into_iter().any(|digest| digest.is_zero())
    {
        return Err(AgentdError::Invalid(
            "durable RunStart is not a current, complete, authority-free canonical identity"
                .to_string(),
        ));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdError> {
    let encoded = value.as_str().as_bytes();
    let length = u32::try_from(encoded.len())
        .map_err(|_| AgentdError::Invalid("run-start identifier is too large".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(encoded);
    Ok(())
}
