//! Private exact fields for the original canonical handoff codec.

use super::*;

const STAGES: [CanonicalStageV1; 7] = [CanonicalStageV1::ObjectiveValidated, CanonicalStageV1::UtilityEvaluated,
    CanonicalStageV1::NeuralSignalCollected, CanonicalStageV1::PromptPortfolioBuilt, CanonicalStageV1::IntuitionDecided,
    CanonicalStageV1::ContextCompiled, CanonicalStageV1::EvaluationAdmitted];

impl Envelope {
    pub(in crate::intelligence_product::canonical_prepared) fn capture(value: &IntelligenceHostEnvelopeV1) -> anyhow::Result<Self> {
        let AdvisoryDecisionV1::Selected { candidate_id, propensity } = &value.decision.decision else {
            anyhow::bail!("retained Ready envelope has no original selection");
        };
        let d = &value.decision;
        Ok(Self { run_id: value.run_id.to_string(), snapshot_digest: value.snapshot_digest.to_string(), objective_digest: value.objective_digest.to_string(),
            candidate_set_digest: value.candidate_set_digest.to_string(), utility_receipt_digest: value.utility_receipt_digest.to_string(),
            neural_receipt_digest: value.neural_receipt_digest.to_string(), prompt_receipt_digest: value.prompt_receipt_digest.to_string(),
            decision: Decision { run_id: d.run_id.to_string(), candidate_set_digest: d.candidate_set_digest.to_string(),
                intuition_receipt_digest: d.intuition_receipt_digest.to_string(), candidate_id: candidate_id.to_string(), propensity: propensity.raw(),
                decision_digest: d.decision_digest.to_string(), authority_denied: !d.authority.grants_any() },
            context_receipt_digest: value.context_receipt_digest.to_string(), context_binding_digest: value.context_binding_digest.to_string(),
            evaluation_receipt_digest: value.evaluation_receipt_digest.to_string(), trace_digest: value.trace_digest.to_string(),
            stage_trace: value.stage_trace.iter().map(|trace| Trace { stage: trace.stage as u8, producer: trace.producer.to_string(),
                predecessor_digest: trace.predecessor_digest.to_string(), output_digest: trace.output_digest.to_string() }).collect(),
            envelope_digest: value.envelope_digest.to_string(), authority_denied: !value.authority.grants_any() })
    }
    pub(in crate::intelligence_product::canonical_prepared) fn restore(self) -> anyhow::Result<IntelligenceHostEnvelopeV1> {
        anyhow::ensure!(self.authority_denied && self.decision.authority_denied && self.stage_trace.len() == 7,
            "retained envelope authority or trace count");
        let d = self.decision;
        Ok(IntelligenceHostEnvelopeV1 { run_id: StableId::new(self.run_id)?, snapshot_digest: self.snapshot_digest.parse()?,
            objective_digest: self.objective_digest.parse()?, candidate_set_digest: self.candidate_set_digest.parse()?,
            utility_receipt_digest: self.utility_receipt_digest.parse()?, neural_receipt_digest: self.neural_receipt_digest.parse()?,
            prompt_receipt_digest: self.prompt_receipt_digest.parse()?, decision: AdvisoryDecisionReceiptV1 {
                run_id: StableId::new(d.run_id)?, candidate_set_digest: d.candidate_set_digest.parse()?, intuition_receipt_digest: d.intuition_receipt_digest.parse()?,
                decision: AdvisoryDecisionV1::Selected { candidate_id: StableId::new(d.candidate_id)?, propensity: ProbabilityQ32::from_raw(d.propensity)? },
                decision_digest: d.decision_digest.parse()?, authority: AuthorityPosture::DENY_ALL },
            context_receipt_digest: self.context_receipt_digest.parse()?, context_binding_digest: self.context_binding_digest.parse()?,
            evaluation_receipt_digest: self.evaluation_receipt_digest.parse()?, trace_digest: self.trace_digest.parse()?,
            stage_trace: self.stage_trace.into_iter().map(|trace| Ok(CanonicalStageTraceV1 {
                stage: *STAGES.get(usize::from(trace.stage)).ok_or_else(|| anyhow::anyhow!("invalid retained stage"))?,
                producer: StableId::new(trace.producer)?, predecessor_digest: trace.predecessor_digest.parse()?, output_digest: trace.output_digest.parse()?,
            })).collect::<anyhow::Result<_>>()?, envelope_digest: self.envelope_digest.parse()?, authority: AuthorityPosture::DENY_ALL })
    }
}
