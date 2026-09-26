//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use std::sync::Arc;

use crate::AgentdAuthenticatedIntuitionInputV1;
use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_prompt_optimizer::OptimizationRequest;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;
use crate::AgentdSignedEvaluationV2;

type RequestOwnerV1 = dyn Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<CanonicalIntelligenceRunRequestV1, AgentdError>
    + Send
    + Sync;
type ObjectiveOwnerV1 = dyn Fn(
        &AgentdIdentity,
        &RunStartRecordV1,
    ) -> Result<
        (
            ObjectiveSourceEnvelopeV1,
            ObjectiveAdmissionProfileV1,
            ObjectiveAdmissionContextV1,
        ),
        AgentdError,
    > + Send
    + Sync;
type UtilityOwnerV1 = dyn Fn(
        &AgentdIdentity,
        &RunStartRecordV1,
    ) -> Result<
        (
            ContributionSet,
            UtilityProfile,
            Option<ScalarizationProfile>,
            EvaluationPolicyV1,
        ),
        AgentdError,
    > + Send
    + Sync;
type NeuronOwnerV1 = dyn Fn(
        &AgentdIdentity,
        &RunStartRecordV1,
    ) -> Result<(SparseConfig, SparseTick, Option<SparseCheckpoint>), AgentdError>
    + Send
    + Sync;
type PromptOwnerV1 = dyn Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<OptimizationRequest, AgentdError>
    + Send
    + Sync;
type IntuitionOwnerV1 = dyn Fn(
        &AgentdIdentity,
        &RunStartRecordV1,
    ) -> Result<AgentdAuthenticatedIntuitionInputV1, AgentdError>
    + Send
    + Sync;
type ContextOwnerV1 = dyn Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<CompilationRequest, AgentdError>
    + Send
    + Sync;
type EvaluationOwnerV1 = dyn Fn(
        &AgentdIdentity,
        &RunStartRecordV1,
    ) -> Result<(EvaluationRequest, Option<AgentdSignedEvaluationV2>), AgentdError>
    + Send
    + Sync;

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
}

impl AgentdIntelligenceInvocationV1 {
    /// Compose host-installed owner readers into the canonical invocation seam.
    /// This constructor does not bootstrap or qualify the ordinary daemon profile.
    ///
    /// The closures are installed by the trusted host at daemon composition
    /// time. Request bytes cannot replace them, and every ObjectiveStart causes
    /// all owners to be read again against the same durable RunStart record.
    #[allow(clippy::too_many_arguments)]
    pub fn authoritative_provider<R, O, U, N, P, I, C, E>(
        request_owner: R,
        objective_owner: O,
        utility_owner: U,
        neuron_owner: N,
        prompt_owner: P,
        intuition_owner: I,
        context_owner: C,
        evaluation_owner: E,
    ) -> Arc<dyn AgentdIntelligenceInvocationProviderV1>
    where
        R: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<CanonicalIntelligenceRunRequestV1, AgentdError>
            + Send
            + Sync
            + 'static,
        O: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<
                (
                    ObjectiveSourceEnvelopeV1,
                    ObjectiveAdmissionProfileV1,
                    ObjectiveAdmissionContextV1,
                ),
                AgentdError,
            > + Send
            + Sync
            + 'static,
        U: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<
                (
                    ContributionSet,
                    UtilityProfile,
                    Option<ScalarizationProfile>,
                    EvaluationPolicyV1,
                ),
                AgentdError,
            > + Send
            + Sync
            + 'static,
        N: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            )
                -> Result<(SparseConfig, SparseTick, Option<SparseCheckpoint>), AgentdError>
            + Send
            + Sync
            + 'static,
        P: Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<OptimizationRequest, AgentdError>
            + Send
            + Sync
            + 'static,
        I: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<AgentdAuthenticatedIntuitionInputV1, AgentdError>
            + Send
            + Sync
            + 'static,
        C: Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<CompilationRequest, AgentdError>
            + Send
            + Sync
            + 'static,
        E: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
            )
                -> Result<(EvaluationRequest, Option<AgentdSignedEvaluationV2>), AgentdError>
            + Send
            + Sync
            + 'static,
    {
        Arc::new(AuthoritativeInvocationProviderV1 {
            request_owner: Arc::new(request_owner),
            objective_owner: Arc::new(objective_owner),
            utility_owner: Arc::new(utility_owner),
            neuron_owner: Arc::new(neuron_owner),
            prompt_owner: Arc::new(prompt_owner),
            intuition_owner: Arc::new(intuition_owner),
            context_owner: Arc::new(context_owner),
            evaluation_owner: Arc::new(evaluation_owner),
        })
    }

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

    fn require_run_identity(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        if record.snapshot.generation != identity.spawn_generation
            || record.snapshot.fence_digest
                != crate::objective_runtime::objective_fence(identity, identity.spawn_generation)
        {
            return Err(AgentdError::Invalid(
                "canonical input production requires the exact Agentd identity and generation"
                    .to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        Self::require_run_identity(identity, record)?;
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

struct AuthoritativeInvocationProviderV1 {
    request_owner: Arc<RequestOwnerV1>,
    objective_owner: Arc<ObjectiveOwnerV1>,
    utility_owner: Arc<UtilityOwnerV1>,
    neuron_owner: Arc<NeuronOwnerV1>,
    prompt_owner: Arc<PromptOwnerV1>,
    intuition_owner: Arc<IntuitionOwnerV1>,
    context_owner: Arc<ContextOwnerV1>,
    evaluation_owner: Arc<EvaluationOwnerV1>,
}

impl AgentdIntelligenceInvocationProviderV1 for AuthoritativeInvocationProviderV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        // Reject cross-Agent and stale-generation requests before touching any owner.
        AgentdIntelligenceInvocationV1::require_run_identity(identity, record)?;
        let request = (self.request_owner)(identity, record)?;
        let (objective_envelope, objective_profile, objective_context) =
            (self.objective_owner)(identity, record)?;
        let (utility_contributions, utility_profile, utility_scalarization, utility_policy) =
            (self.utility_owner)(identity, record)?;
        let (neural_config, neural_tick, neural_previous) = (self.neuron_owner)(identity, record)?;
        let prompt_request = (self.prompt_owner)(identity, record)?;
        let intuition = (self.intuition_owner)(identity, record)?;
        let context_request = (self.context_owner)(identity, record)?;
        let (evaluation_request, signed_evaluation) = (self.evaluation_owner)(identity, record)?;
        let invocation = AgentdIntelligenceInvocationV1 {
            request,
            inputs: AgentdIntelligenceOwnerInputsV1 {
                objective_envelope,
                objective_profile,
                objective_context,
                utility_contributions,
                utility_profile,
                utility_scalarization,
                utility_policy,
                neural_config,
                neural_tick,
                neural_previous,
                prompt_request,
                intuition,
                context_request,
                evaluation_request,
                signed_evaluation,
            },
        };
        invocation.validate(identity, record)?;
        Ok(invocation)
    }
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
