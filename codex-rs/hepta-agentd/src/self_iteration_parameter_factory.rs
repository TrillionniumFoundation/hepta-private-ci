//! Candidate construction through the existing governed parameter owner. The
//! durable proposal/anchor is committed before its generation can be frozen.

use std::future::Future;

use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;

use super::*;

/// The host's generation compiler prepares immutable source material from the
/// model proposal, actual current parameter/ledger frontiers and its frozen test
/// plan. After governed admission it builds +1/+2 durable Neuron generations and
/// signs their exact frozen identity using the installed Generator credential.
/// These capabilities stay outside request data and model text.
pub trait AgentdGovernedParameterGenerationCompilerV1: Send {
    fn bind_round(
        &mut self,
        _round: AgentdSelfIterationRoundV1,
        _canonical: crate::CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        Err(invalid(
            "generation compiler has no installed canonical round port",
        ))
    }

    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError>;

    /// A compiler with any original intent or task must remain conservative.
    fn validate_before_candidate_effects(
        &mut self,
        _envelope: &IterationEnvelopeV1,
        _proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<AgentdSelfIterationCandidateEffectAdmissionV1, AgentdError>> + Send
    {
        std::future::ready(Ok(
            AgentdSelfIterationCandidateEffectAdmissionV1::ConservativeUnknown,
        ))
    }

    /// Pure inspection of installed materials and exact advice, without prepare.
    fn recovery_request(
        &self,
        _envelope: &IterationEnvelopeV1,
        _proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<Option<ParameterPlasticityProductRequestV1>, AgentdError>> + Send
    {
        std::future::ready(Ok(None))
    }

    /// Open only complete original generation stores and immutable G publication.
    /// Partial stores or unknown issuance remain None; creating them is forbidden.
    fn materialize_completed(
        &mut self,
        _envelope: IterationEnvelopeV1,
        _proposal: &SelfIterationModelAssessmentV1,
        _admitted: &ParameterPlasticityProductReceiptV1,
    ) -> impl Future<Output = Result<Option<AgentdSelfIterationCandidateV1>, AgentdError>> + Send
    {
        std::future::ready(Ok(None))
    }

    fn prepare(
        &mut self,
        envelope: &IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<ParameterPlasticityProductRequestV1, AgentdError>> + Send;

    fn materialize(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
        admitted: &ParameterPlasticityProductReceiptV1,
    ) -> impl Future<Output = Result<AgentdSelfIterationCandidateV1, AgentdError>> + Send;
}

/// A concrete proposal producer bound to #1138's sole plasticity runtime owner.
/// It cannot create another writer or bypass current owner-store resolution.
pub struct AgentdGovernedParameterCandidateAssemblerV1<C> {
    producer: crate::PlasticityRuntimeHandleV1,
    compiler: C,
}
impl<C: AgentdGovernedParameterGenerationCompilerV1>
    AgentdGovernedParameterCandidateAssemblerV1<C>
{
    pub fn new(producer: crate::PlasticityRuntimeHandleV1, compiler: C) -> Self {
        Self { producer, compiler }
    }
}
impl<C: AgentdGovernedParameterGenerationCompilerV1> AgentdSelfIterationCandidateAssemblerV1
    for AgentdGovernedParameterCandidateAssemblerV1<C>
{
    fn bind_round(
        &mut self,
        round: AgentdSelfIterationRoundV1,
        canonical: crate::CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        self.compiler.bind_round(round, canonical)
    }
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        self.compiler.describe(envelope)
    }
    fn validate_before_candidate_effects(
        &mut self,
        envelope: &IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> impl Future<Output = Result<AgentdSelfIterationCandidateEffectAdmissionV1, AgentdError>> + Send
    {
        self.compiler
            .validate_before_candidate_effects(envelope, proposal)
    }
    async fn recover_completed(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<Option<AgentdSelfIterationCandidateV1>, AgentdError> {
        self.recover_governed_completed(envelope, proposal).await
    }
    async fn assemble(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        let request = self.compiler.prepare(&envelope, proposal).await?;
        let expected_proposal = request.proposal_id.clone();
        let expected_generation = request.admission.candidate_generation.get();
        if request.admission.objective_digest != envelope.objective_digest {
            return Err(invalid("parameter factory objective binding"));
        }
        let now: u64 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| invalid("parameter factory clock"))?
            .as_millis()
            .try_into()
            .map_err(|_| invalid("parameter factory clock overflow"))?;
        let receipt = self
            .producer
            .propose_parameter(request, now)
            .await
            .map_err(|error| invalid(format!("governed parameter owner: {error}")))?;
        recovery::validate_receipt(&receipt, &expected_proposal, expected_generation)?;
        let candidate = self
            .compiler
            .materialize(envelope.clone(), proposal, &receipt)
            .await?;
        recovery::validate_candidate(&candidate, &envelope, &receipt, expected_generation)?;
        Ok(candidate)
    }
}

#[path = "self_iteration_parameter_recovery.rs"]
mod recovery;
