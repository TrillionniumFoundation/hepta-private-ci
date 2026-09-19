//! Agentd product caller for the unified intelligence V3 composition graph.
//!
//! Agentd owns only the host-handoff stage. Objective, evaluation, utility,
//! neuron, prompt, intuition, context and learning facts remain with their
//! registered owners and are delegated through typed upstream ports. The handoff
//! receipt is proposal-only and authority-free; actual Codex turn/model/effect
//! execution remains on the existing App Server spine.

use codex_hepta_intelligence::IntelligenceCompositionPortsV3;
use codex_hepta_intelligence::IntelligenceCompositionReceiptV3;
use codex_hepta_intelligence::IntelligencePipelineErrorV3;
use codex_hepta_intelligence::IntelligencePortDecisionV3;
use codex_hepta_intelligence::IntelligencePortFailureV3;
use codex_hepta_intelligence::IntelligencePortInputV3;
use codex_hepta_intelligence::IntelligencePortReceiptV3;
use codex_hepta_intelligence::IntelligenceRunRequestV3;
use codex_hepta_intelligence::run_composition_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub trait AgentdUpstreamIntelligencePortsV3 {
    fn validate_objective(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn admit_evaluation(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn build_legal_set(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn evaluate_utility(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn collect_neural_signal(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn build_prompt_portfolio(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn decide_intuition(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn compile_context(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;

    fn record_learning(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3>;
}

pub fn run_agentd_intelligence_v3<P: AgentdUpstreamIntelligencePortsV3>(
    request: IntelligenceRunRequestV3,
    upstream: &mut P,
) -> Result<IntelligenceCompositionReceiptV3, IntelligencePipelineErrorV3> {
    run_composition_v3(request, &mut AgentdIntelligencePortsV3 { upstream })
}

struct AgentdIntelligencePortsV3<'a, P> {
    upstream: &'a mut P,
}

impl<P: AgentdUpstreamIntelligencePortsV3> IntelligenceCompositionPortsV3
    for AgentdIntelligencePortsV3<'_, P>
{
    fn validate_objective(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.validate_objective(input)
    }

    fn admit_evaluation(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.admit_evaluation(input)
    }

    fn build_legal_set(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.build_legal_set(input)
    }

    fn evaluate_utility(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.evaluate_utility(input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.collect_neural_signal(input)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.build_prompt_portfolio(input)
    }

    fn decide_intuition(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.decide_intuition(input)
    }

    fn compile_context(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.compile_context(input)
    }

    fn handoff_to_host(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        let mut bytes = b"hepta.agentd.intelligence-handoff.v3\0".to_vec();
        push_id(&mut bytes, &input.run_id);
        bytes.extend_from_slice(input.snapshot_digest.as_array());
        bytes.extend_from_slice(input.predecessor_digest.as_array());
        bytes.extend_from_slice(&input.budget_micros.to_be_bytes());
        Ok(IntelligencePortReceiptV3 {
            stage: input.stage,
            producer: stable_id("runtime.agentd"),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: Digest32::of_bytes(&bytes),
            decision: IntelligencePortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn record_learning(
        &mut self,
        input: &IntelligencePortInputV3,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        self.upstream.record_learning(input)
    }
}

fn stable_id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("static Agentd identity invalid: {error:?}"))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "intelligence_v3_tests.rs"]
mod tests;
