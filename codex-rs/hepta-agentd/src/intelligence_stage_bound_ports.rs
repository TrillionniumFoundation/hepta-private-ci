//! Stage-local dataflow closure for the canonical intelligence product path.
//!
//! The existing owner adapters remain the only algorithm callers. This wrapper
//! binds the actual compiled Objective, utility feasibility, Neural output,
//! Prompt output and Intuition output into the successor owner request. A
//! receipt predecessor alone is never treated as semantic authorization.

use std::collections::BTreeSet;

use super::super::*;

pub(super) struct StageBoundAgentdOwnerPortsV1 {
    inner: AgentdOwnerPortsV1,
    legal_candidates: BTreeSet<StableId>,
    feasible_candidates: Option<BTreeSet<StableId>>,
    prompt_output: Option<Digest32>,
    intuition_output: Option<Digest32>,
}

impl StageBoundAgentdOwnerPortsV1 {
    pub(super) fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        // The runner has already proved equality with the canonical legal set.
        // Retain the IDs here so the compiled Objective and NDU owners become
        // hard semantic boundaries, not merely adjacent receipt producers.
        let legal_candidates = value
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect();
        Self {
            inner: AgentdOwnerPortsV1::new(value, evaluation_session, telemetry),
            legal_candidates,
            feasible_candidates: None,
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
        let envelope = AgentdOwnerPortsV1::take(
            &mut self.inner.objective_envelope,
            input.stage,
            "objective envelope",
        )?;
        let profile = AgentdOwnerPortsV1::take(
            &mut self.inner.objective_profile,
            input.stage,
            "objective profile",
        )?;
        let context = AgentdOwnerPortsV1::take(
            &mut self.inner.objective_context,
            input.stage,
            "objective context",
        )?;
        let started = Instant::now();
        let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context);
        self.inner.within_budget(input, started)?;
        let outcome = outcome.map_err(|_| Self::reject(input.stage, "objective admission"))?;
        if outcome.receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "objective authority"));
        }
        let receipt = outcome
            .compile_result
            .map_err(|_| Self::reject(input.stage, "objective conflict"))?;
        if receipt.disposition != CompileDisposition::Compiled
            || receipt.objective.semantic_digest != input.objective_digest
        {
            return Err(Self::reject(input.stage, "objective binding"));
        }
        let compiled_legal = receipt
            .objective
            .legal_actions
            .iter()
            .map(|action| action.id.clone())
            .collect::<BTreeSet<_>>();
        validate_objective_candidate_universe(&self.legal_candidates, &compiled_legal)
            .map_err(|label| Self::reject(input.stage, label))?;
        AgentdOwnerPortsV1::receipt(
            input,
            "objective.compiler",
            receipt.objective.semantic_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let set = AgentdOwnerPortsV1::take(
            &mut self.inner.utility_contributions,
            input.stage,
            "utility contributions",
        )?;
        if set.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility objective"));
        }
        let actual_candidates = set
            .contributions
            .iter()
            .map(|contribution| contribution.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        validate_utility_candidate_universe(&self.legal_candidates, &actual_candidates)
            .map_err(|label| Self::reject(input.stage, label))?;
        let profile = AgentdOwnerPortsV1::take(
            &mut self.inner.utility_profile,
            input.stage,
            "utility profile",
        )?;
        let scalarization = AgentdOwnerPortsV1::take(
            &mut self.inner.utility_scalarization,
            input.stage,
            "utility scalarization",
        )?;
        let policy = AgentdOwnerPortsV1::take(
            &mut self.inner.utility_policy,
            input.stage,
            "utility policy",
        )?;
        let started = Instant::now();
        let receipt = evaluate_candidates_with_policy(set, profile, scalarization, policy);
        self.inner.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "utility evaluation"))?;
        if receipt.base.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility receipt objective"));
        }
        self.feasible_candidates = Some(
            receipt
                .base
                .evaluated_candidates
                .iter()
                .map(|candidate| candidate.candidate_id.clone())
                .collect(),
        );
        AgentdOwnerPortsV1::receipt(
            input,
            "utility.ndu",
            receipt.evaluation_digest_v2,
            CanonicalPortDecisionV1::Continue,
        )
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
        let feasible = self
            .feasible_candidates
            .as_ref()
            .ok_or_else(|| Self::reject(input.stage, "utility feasibility"))?;
        let violates_feasibility = self
            .inner
            .intuition_request
            .as_ref()
            .ok_or_else(|| Self::reject(input.stage, "intuition request"))?
            .candidates
            .iter()
            .any(|candidate| {
                candidate.legal
                    && !candidate.hard_veto
                    && !feasible.contains(&candidate.candidate_id)
            });
        if violates_feasibility {
            return Err(Self::reject(
                input.stage,
                "intuition bypassed utility infeasibility",
            ));
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

fn validate_objective_candidate_universe(
    canonical: &BTreeSet<StableId>,
    compiled_legal: &BTreeSet<StableId>,
) -> Result<(), &'static str> {
    if canonical.is_empty() || !canonical.is_subset(compiled_legal) {
        return Err("objective legal candidate binding");
    }
    Ok(())
}

fn validate_utility_candidate_universe(
    canonical: &BTreeSet<StableId>,
    utility: &BTreeSet<StableId>,
) -> Result<(), &'static str> {
    if !canonical.is_subset(utility)
        || utility
            .iter()
            .any(|candidate| !canonical.contains(candidate) && candidate.as_str() != "abstain")
    {
        return Err("utility candidate universe");
    }
    Ok(())
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

    fn ids(values: &[&str]) -> BTreeSet<StableId> {
        values.iter().map(|value| id(value)).collect()
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
    fn objective_action_domain_is_a_hard_candidate_upper_bound() {
        assert!(
            validate_objective_candidate_universe(
                &ids(&["action.read"]),
                &ids(&["action.read", "action.write"])
            )
            .is_ok()
        );
        assert!(
            validate_objective_candidate_universe(
                &ids(&["action.read", "action.network"]),
                &ids(&["action.read"])
            )
            .is_err()
        );
    }

    #[test]
    fn utility_candidate_universe_rejects_hidden_actions_but_allows_abstain() {
        assert!(
            validate_utility_candidate_universe(
                &ids(&["action.read"]),
                &ids(&["action.read", "abstain"])
            )
            .is_ok()
        );
        assert!(
            validate_utility_candidate_universe(
                &ids(&["action.read"]),
                &ids(&["action.read", "action.hidden", "abstain"])
            )
            .is_err()
        );
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
