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
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError>;

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
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        self.compiler.describe(envelope)
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
        if receipt.disposition != ParameterPlasticityDispositionV1::UpdateCandidates
            || receipt.proposal.proposal_id != expected_proposal
            || receipt.proposal.candidate_generation.get() != expected_generation
            || receipt.proposal.authority.grants_any()
            || receipt.registry.authority.grants_any()
            || receipt.composition_digest.is_zero()
            || receipt.registry.proposal_digest != receipt.proposal.proposal_digest
            || receipt.registry.sequence != receipt.committed_registry_anchor.sequence
            || receipt.registry.frame_digest != receipt.committed_registry_anchor.frame_digest
        {
            return Err(invalid(
                "parameter proposal has no anchored admissible update",
            ));
        }
        let candidate = self
            .compiler
            .materialize(envelope.clone(), proposal, &receipt)
            .await?;
        if candidate.envelope != envelope
            || candidate.successor.generation().map_err(control_error)? != expected_generation
            || candidate.base_generation != receipt.proposal.baseline_generation.get()
            || candidate.governed_proposal_digest != receipt.proposal.proposal_digest
            || candidate.governed_anchor_digest != receipt.committed_registry_anchor.frame_digest
            || candidate.governed_composition_digest != receipt.composition_digest
            || !receipt.proposal.candidates.iter().any(|value| {
                value.candidate_id == candidate.candidate.candidate_id
                    && value.kind == ParameterCandidateKindV2::Update
            })
        {
            return Err(invalid(
                "compiled generation changed governed parameter proposal",
            ));
        }
        self_iteration_candidate_payload_v1(&candidate)?;
        Ok(candidate)
    }
}
