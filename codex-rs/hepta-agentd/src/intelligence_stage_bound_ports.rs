//! Stage-local dataflow closure for the canonical intelligence product path.
//!
//! The existing owner adapters remain the only algorithm callers. This wrapper
//! mutates only the successor request identity/binding fields immediately before
//! the owner call, using the actual output digest returned by the predecessor.
//! It therefore closes semantic substitution without introducing another
//! facade, store, owner, or execution spine.

use super::super::*;

pub(super) struct StageBoundAgentdOwnerPortsV1 {
    inner: AgentdOwnerPortsV1,
    prompt_output: Option<Digest32>,
    intuition_output: Option<Digest32>,
}

impl StageBoundAgentdOwnerPortsV1 {
    pub(super) fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            inner: AgentdOwnerPortsV1::new(value, evaluation_session, telemetry),
            prompt_output: None,
            intuition_output: None,
        }
    }

    fn reject(stage: CanonicalStageV1, label: &'static str) -> CanonicalPortFailureV1 {
        AgentdOwnerPortsV1::reject(stage, label)
    }
}

impl CanonicalOwnerPortsV1 for StageBoundAgentdOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        CanonicalOwnerPortsV1::validate_objective(&mut self.inner, input)
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        CanonicalOwnerPortsV1::evaluate_utility(&mut self.inner, input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        CanonicalOwnerPortsV1::collect_neural_signal(&mut self.inner, input)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = self
            .inner
            .prompt_request
            .as_mut()
            .ok_or_else(|| Self::reject(input.stage, "prompt request"))?;
        bind_prompt_request_v1(
            request,
            input.predecessor_digest,
            input.candidate_set_digest,
        )
        .map_err(|label| Self::reject(input.stage, label))?;
        let receipt = CanonicalOwnerPortsV1::build_prompt_portfolio(&mut self.inner, input)?;
        self.prompt_output = Some(receipt.output_digest);
        Ok(receipt)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        if self.prompt_output != Some(input.predecessor_digest) {
            return Err(Self::reject(input.stage, "prompt predecessor"));
        }
        let request = self
            .inner
            .intuition_request
            .as_mut()
            .ok_or_else(|| Self::reject(input.stage, "intuition request"))?;
        bind_intuition_request_v1(
            request,
            input.predecessor_digest,
            input.candidate_set_digest,
        )
        .map_err(|label| Self::reject(input.stage, label))?;
        let receipt = CanonicalOwnerPortsV1::decide_intuition(&mut self.inner, input)?;
        self.intuition_output = Some(receipt.output_digest);
        Ok(receipt)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let prompt_output = self
            .prompt_output
            .ok_or_else(|| Self::reject(input.stage, "prompt output"))?;
        let intuition_output = self
            .intuition_output
            .ok_or_else(|| Self::reject(input.stage, "intuition output"))?;
        if intuition_output != input.predecessor_digest {
            return Err(Self::reject(input.stage, "intuition predecessor"));
        }
        let request = self
            .inner
            .context_request
            .as_mut()
            .ok_or_else(|| Self::reject(input.stage, "context request"))?;
        bind_context_request_v1(
            request,
            prompt_output,
            intuition_output,
            input.candidate_set_digest,
        )
        .map_err(|label| Self::reject(input.stage, label))?;
        CanonicalOwnerPortsV1::compile_context(&mut self.inner, input)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        CanonicalOwnerPortsV1::evaluate_candidate(&mut self.inner, input)
    }
}

pub(super) fn bind_prompt_request_v1(
    request: &mut OptimizationRequest,
    neural_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    let binding = stage_binding_digest_v1(
        b"hepta.agentd.intelligence.prompt-request.v1\0",
        neural_output,
        candidate_set_digest,
    )?;
    request.decision_id = stage_binding_id_v1("prompt", binding)?;
    Ok(())
}

pub(super) fn bind_intuition_request_v1(
    request: &mut CalibratedDecisionRequestV1,
    prompt_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    let binding = stage_binding_digest_v1(
        b"hepta.agentd.intelligence.intuition-request.v1\0",
        prompt_output,
        candidate_set_digest,
    )?;
    request.decision_id = stage_binding_id_v1("intuition", binding)?;
    request.state_digest = binding;
    Ok(())
}

pub(super) fn bind_context_request_v1(
    request: &mut CompilationRequest,
    prompt_output: Digest32,
    intuition_output: Digest32,
    candidate_set_digest: Digest32,
) -> Result<(), &'static str> {
    let binding = stage_binding_digest_v1(
        b"hepta.agentd.intelligence.context-request.v1\0",
        intuition_output,
        candidate_set_digest,
    )?;
    request.compilation_id = stage_binding_id_v1("context", binding)?;
    upsert_binding_item(
        request,
        ContextItem {
            item_id: stage_binding_id_v1("prompt-output", prompt_output)?,
            role: ContextRole::UntrustedEvidence,
            content_digest: prompt_output,
            source_digest: candidate_set_digest,
            token_count: 1,
            contains_secret: false,
        },
    )?;
    upsert_binding_item(
        request,
        ContextItem {
            item_id: stage_binding_id_v1("intuition-output", intuition_output)?,
            role: ContextRole::UntrustedEvidence,
            content_digest: intuition_output,
            source_digest: prompt_output,
            token_count: 1,
            contains_secret: false,
        },
    )?;
    Ok(())
}

fn upsert_binding_item(
    request: &mut CompilationRequest,
    expected: ContextItem,
) -> Result<(), &'static str> {
    match request
        .items
        .iter()
        .find(|item| item.item_id == expected.item_id)
    {
        Some(existing) if existing == &expected => Ok(()),
        Some(_) => Err("context stage binding substitution"),
        None => {
            request.items.push(expected);
            Ok(())
        }
    }
}

fn stage_binding_digest_v1(
    domain: &[u8],
    predecessor: Digest32,
    candidate_set_digest: Digest32,
) -> Result<Digest32, &'static str> {
    if predecessor.is_zero() || candidate_set_digest.is_zero() {
        return Err("stage binding digest");
    }
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn stage_binding_id_v1(kind: &str, digest: Digest32) -> Result<StableId, &'static str> {
    StableId::new(format!("intelligence.{kind}.{digest}"))
        .map_err(|_| "stage binding identity")
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
        let mut left = OptimizationRequest {
            decision_id: id("old.prompt"),
            objective_digest: digest("objective"),
            registry_snapshot_digest: digest("registry"),
            budget: 1,
            maximum_selected: 1,
            candidates: Vec::new(),
        };
        let mut right = left.clone();
        bind_prompt_request_v1(&mut left, digest("neural.left"), digest("set"))
            .expect("left binding");
        bind_prompt_request_v1(&mut right, digest("neural.right"), digest("set"))
            .expect("right binding");
        assert_ne!(left.decision_id, right.decision_id);
    }

    #[test]
    fn context_binding_is_idempotent_and_substitution_fails() {
        let mut request = CompilationRequest {
            compilation_id: id("old.context"),
            run_snapshot_digest: digest("snapshot"),
            objective_digest: digest("objective"),
            token_budget: 8,
            items: Vec::new(),
        };
        bind_context_request_v1(
            &mut request,
            digest("prompt"),
            digest("intuition"),
            digest("set"),
        )
        .expect("first binding");
        let first = request.clone();
        bind_context_request_v1(
            &mut request,
            digest("prompt"),
            digest("intuition"),
            digest("set"),
        )
        .expect("idempotent binding");
        assert_eq!(request, first);
        request.items[0].content_digest = digest("substitution");
        assert!(
            bind_context_request_v1(
                &mut request,
                digest("prompt"),
                digest("intuition"),
                digest("set")
            )
            .is_err()
        );
    }
}
