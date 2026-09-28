//! Final stage-to-stage identity binding for the canonical product runner.
//!
//! The native owner adapters consume the actual NDU, Neuron and Prompt outputs.
//! This wrapper closes the final Intuition -> Context edge without replacing any
//! owner algorithm: the context owner still produces its native output, while
//! the canonical context-stage identity additionally binds the actual intuition
//! receipt, candidate-set identity and selected candidate.

use super::super::*;

pub(super) struct StageBoundAgentdOwnerPortsV1 {
    inner: super::super::AgentdOwnerPortsV1,
    intuition_output: Option<Digest32>,
    selected_candidate: Option<StableId>,
}

impl StageBoundAgentdOwnerPortsV1 {
    pub(super) fn new(
        inputs: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            inner: super::super::AgentdOwnerPortsV1::new(
                inputs,
                evaluation_session,
                telemetry,
            ),
            intuition_output: None,
            selected_candidate: None,
        }
    }
}

impl CanonicalOwnerPortsV1 for StageBoundAgentdOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.validate_objective(input)
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.evaluate_utility(input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.collect_neural_signal(input)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.build_prompt_portfolio(input)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let receipt = self.inner.decide_intuition(input)?;
        self.intuition_output = Some(receipt.output_digest);
        self.selected_candidate = match &receipt.decision {
            CanonicalPortDecisionV1::Selected { candidate_id, .. } => {
                Some(candidate_id.clone())
            }
            CanonicalPortDecisionV1::Continue
            | CanonicalPortDecisionV1::Abstained
            | CanonicalPortDecisionV1::SlowPath => None,
        };
        Ok(receipt)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let actual_intuition = self.intuition_output.ok_or_else(|| {
            stage_failure(
                input.stage,
                "context missing actual intuition predecessor",
            )
        })?;
        if input.predecessor_digest != actual_intuition {
            return Err(stage_failure(
                input.stage,
                "context intuition predecessor substitution",
            ));
        }
        let selected_candidate = self.selected_candidate.as_ref().ok_or_else(|| {
            stage_failure(input.stage, "context missing selected candidate")
        })?;

        let mut receipt = self.inner.compile_context(input)?;
        receipt.output_digest = context_stage_digest_v1(
            receipt.output_digest,
            actual_intuition,
            input.candidate_set_digest,
            selected_candidate,
        )
        .map_err(|_| stage_failure(input.stage, "context stage identity"))?;
        Ok(receipt)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.evaluate_candidate(input)
    }
}

fn stage_failure(
    stage: CanonicalStageV1,
    label: &'static str,
) -> CanonicalPortFailureV1 {
    CanonicalPortFailureV1 {
        class: CanonicalPortFailureClassV1::Rejected,
        evidence_digest: Digest32::of_bytes(
            format!("hepta.agentd.intelligence.stage-binding.v1:{stage:?}:{label}")
                .as_bytes(),
        ),
    }
}

pub(super) fn context_stage_digest_v1(
    native_context_digest: Digest32,
    intuition_receipt_digest: Digest32,
    candidate_set_digest: Digest32,
    selected_candidate: &StableId,
) -> Result<Digest32, CanonicalIntelligenceError> {
    if native_context_digest.is_zero()
        || intuition_receipt_digest.is_zero()
        || candidate_set_digest.is_zero()
    {
        return Err(CanonicalIntelligenceError::EmptyDigest(
            "context stage dependency",
        ));
    }
    let mut bytes = b"hepta.agentd.intelligence-context-stage.v1\0".to_vec();
    bytes.extend_from_slice(native_context_digest.as_array());
    bytes.extend_from_slice(intuition_receipt_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    let selected = selected_candidate.as_str().as_bytes();
    let length =
        u32::try_from(selected.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(selected);
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn successor_request_bindings_change_with_real_predecessor() {
        let native_context = digest("context");
        let intuition = digest("intuition");
        let candidates = digest("candidates");
        let selected = id("candidate.a");
        let baseline =
            context_stage_digest_v1(native_context, intuition, candidates, &selected)
                .expect("baseline");

        assert_ne!(
            baseline,
            context_stage_digest_v1(
                native_context,
                digest("other-intuition"),
                candidates,
                &selected,
            )
            .expect("changed intuition")
        );
        assert_ne!(
            baseline,
            context_stage_digest_v1(
                digest("other-context"),
                intuition,
                candidates,
                &selected,
            )
            .expect("changed context")
        );
    }

    #[test]
    fn context_binding_is_idempotent_and_substitution_fails() {
        let native_context = digest("context");
        let intuition = digest("intuition");
        let candidates = digest("candidates");
        let selected = id("candidate.a");
        let baseline =
            context_stage_digest_v1(native_context, intuition, candidates, &selected)
                .expect("baseline");

        assert_eq!(
            baseline,
            context_stage_digest_v1(native_context, intuition, candidates, &selected)
                .expect("same inputs")
        );
        assert_ne!(
            baseline,
            context_stage_digest_v1(
                native_context,
                intuition,
                digest("other-candidates"),
                &selected,
            )
            .expect("changed candidate set")
        );
        assert_ne!(
            baseline,
            context_stage_digest_v1(
                native_context,
                intuition,
                candidates,
                &id("candidate.b"),
            )
            .expect("changed selection")
        );
        assert!(
            context_stage_digest_v1(
                Digest32::ZERO,
                intuition,
                candidates,
                &selected,
            )
            .is_err()
        );
    }
}
