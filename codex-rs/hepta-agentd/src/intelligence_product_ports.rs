//! Concrete owner calls and the ephemeral outputs consumed by later stages.
//! Prompt realization delivery remains an owner-backed integration requirement;
//! a receipt digest is not fabricated prompt content or delivery evidence.

use std::collections::BTreeSet;

use super::*;

pub(super) struct AgentdOwnerPortsV1 {
    telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    objective_envelope: Option<ObjectiveSourceEnvelopeV1>,
    objective_profile: Option<ObjectiveAdmissionProfileV1>,
    objective_context: Option<ObjectiveAdmissionContextV1>,
    utility_contributions: Option<ContributionSet>,
    utility_profile: Option<UtilityProfile>,
    utility_scalarization: Option<Option<ScalarizationProfile>>,
    utility_policy: Option<EvaluationPolicyV1>,
    neural_config: Option<SparseConfig>,
    neural_tick: Option<SparseTick>,
    neural_previous: Option<Option<SparseCheckpoint>>,
    prompt_request: Option<OptimizationRequest>,
    prompt_delivery: Option<PreparedPromptDeliveryV1>,
    intuition_request: Option<CalibratedDecisionRequestV1>,
    context_request: Option<CompilationRequest>,
    evaluation_request: Option<EvaluationRequest>,
    evaluation_session: Option<AgentdEvaluationSessionV1>,
    selected_candidate: Option<StableId>,
    legal_candidates: BTreeSet<StableId>,
    feasible_candidates: Option<BTreeSet<StableId>>,
    utility_output: Option<Digest32>,
    neural_output: Option<Digest32>,
    prompt_output: Option<Digest32>,
}

impl AgentdOwnerPortsV1 {
    pub(super) fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        let legal_candidates = value
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect();
        Self {
            telemetry,
            objective_envelope: Some(value.objective_envelope),
            objective_profile: Some(value.objective_profile),
            objective_context: Some(value.objective_context),
            utility_contributions: Some(value.utility_contributions),
            utility_profile: Some(value.utility_profile),
            utility_scalarization: Some(value.utility_scalarization),
            utility_policy: Some(value.utility_policy),
            neural_config: Some(value.neural_config),
            neural_tick: Some(value.neural_tick),
            neural_previous: Some(value.neural_previous),
            prompt_request: Some(value.prompt_request),
            prompt_delivery: value.prompt_delivery,
            intuition_request: Some(value.intuition_request),
            context_request: Some(value.context_request),
            evaluation_request: Some(value.evaluation_request),
            evaluation_session,
            selected_candidate: None,
            legal_candidates,
            feasible_candidates: None,
            utility_output: None,
            neural_output: None,
            prompt_output: None,
        }
    }

    fn reject(stage: CanonicalStageV1, label: &'static str) -> CanonicalPortFailureV1 {
        let evidence = format!("hepta.agentd.intelligence.owner-failure.v1:{stage:?}:{label}");
        CanonicalPortFailureV1 {
            class: CanonicalPortFailureClassV1::Rejected,
            evidence_digest: Digest32::of_bytes(evidence.as_bytes()),
        }
    }

    fn receipt(
        input: &CanonicalPortInputV1,
        owner: &str,
        output_digest: Digest32,
        decision: CanonicalPortDecisionV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        if output_digest.is_zero() {
            return Err(Self::reject(input.stage, "zero output"));
        }
        let producer =
            StableId::new(owner).map_err(|_| Self::reject(input.stage, "producer identity"))?;
        Ok(CanonicalPortReceiptV1 {
            stage: input.stage,
            producer,
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn within_budget(
        &self,
        input: &CanonicalPortInputV1,
        started: Instant,
    ) -> Result<(), CanonicalPortFailureV1> {
        let elapsed = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        self.telemetry.record_stage_latency(input.stage, elapsed);
        if elapsed > input.budget_micros {
            return Err(CanonicalPortFailureV1 {
                class: CanonicalPortFailureClassV1::TimedOut,
                evidence_digest: Digest32::of_bytes(
                    format!(
                        "hepta.agentd.intelligence.stage-timeout.v1:{:?}:{elapsed}:{}",
                        input.stage, input.budget_micros,
                    )
                    .as_bytes(),
                ),
            });
        }
        Ok(())
    }

    fn take<T>(
        slot: &mut Option<T>,
        stage: CanonicalStageV1,
        label: &'static str,
    ) -> Result<T, CanonicalPortFailureV1> {
        slot.take().ok_or_else(|| Self::reject(stage, label))
    }
}

fn bind_stage_digest(
    supplied: Digest32,
    actual: Digest32,
    stage: CanonicalStageV1,
) -> Result<Digest32, CanonicalPortFailureV1> {
    if actual.is_zero() || (!supplied.is_zero() && supplied != actual) {
        return Err(AgentdOwnerPortsV1::reject(
            stage,
            "actual predecessor substitution",
        ));
    }
    // Zero is an unmaterialized host template, not an admitted owner receipt.
    // The real owner receives only the actual nonzero value and validates it.
    Ok(actual)
}

fn validate_utility_universe(
    expected: &BTreeSet<StableId>,
    actual: &BTreeSet<StableId>,
) -> Result<(), CanonicalPortFailureV1> {
    if !expected.is_subset(actual)
        || actual
            .iter()
            .any(|candidate| !expected.contains(candidate) && candidate.as_str() != "abstain")
    {
        return Err(AgentdOwnerPortsV1::reject(
            CanonicalStageV1::UtilityEvaluated,
            "utility candidate universe",
        ));
    }
    Ok(())
}

impl CanonicalOwnerPortsV1 for AgentdOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let envelope = Self::take(
            &mut self.objective_envelope,
            input.stage,
            "objective envelope",
        )?;
        let profile = Self::take(
            &mut self.objective_profile,
            input.stage,
            "objective profile",
        )?;
        let context = Self::take(
            &mut self.objective_context,
            input.stage,
            "objective context",
        )?;
        let started = Instant::now();
        let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context);
        self.within_budget(input, started)?;
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
        Self::receipt(
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
        let set = Self::take(
            &mut self.utility_contributions,
            input.stage,
            "utility contributions",
        )?;
        if set.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility objective"));
        }
        let actual = set
            .contributions
            .iter()
            .map(|value| value.candidate_id.clone())
            .collect();
        validate_utility_universe(&self.legal_candidates, &actual)?;
        let profile = Self::take(&mut self.utility_profile, input.stage, "utility profile")?;
        let scalarization = Self::take(
            &mut self.utility_scalarization,
            input.stage,
            "utility scalarization",
        )?;
        let policy = Self::take(&mut self.utility_policy, input.stage, "utility policy")?;
        let started = Instant::now();
        let receipt = evaluate_candidates_with_policy(set, profile, scalarization, policy);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "utility evaluation"))?;
        if receipt.base.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility receipt objective"));
        }
        // The NDU owner places only feasible candidates in evaluated_candidates;
        // its separate rejected_candidates records every hard/risk/resource veto.
        self.feasible_candidates = Some(
            receipt
                .base
                .evaluated_candidates
                .iter()
                .map(|candidate| candidate.candidate_id.clone())
                .collect(),
        );
        self.utility_output = Some(receipt.evaluation_digest_v2);
        Self::receipt(
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
        let config = Self::take(&mut self.neural_config, input.stage, "neural config")?;
        let mut tick = Self::take(&mut self.neural_tick, input.stage, "neural tick")?;
        let previous = Self::take(&mut self.neural_previous, input.stage, "neural previous")?;
        let actual_utility = self
            .utility_output
            .ok_or_else(|| Self::reject(input.stage, "missing actual utility"))?;
        if tick.objective_digest != input.objective_digest
            || input.predecessor_digest != actual_utility
        {
            return Err(Self::reject(input.stage, "neural binding"));
        }
        tick.ndu_digest = bind_stage_digest(tick.ndu_digest, actual_utility, input.stage)?;
        let started = Instant::now();
        let result = sparse_tick(&config, &tick, previous.as_ref());
        self.within_budget(input, started)?;
        let (_, receipt) = result.map_err(|_| Self::reject(input.stage, "neural tick"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "neural authority"));
        }
        self.neural_output = Some(receipt.checkpoint_after);
        Self::receipt(
            input,
            "neuron.runtime",
            receipt.checkpoint_after,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.prompt_request, input.stage, "prompt request")?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "prompt objective"));
        }
        if self.neural_output != Some(input.predecessor_digest) {
            return Err(Self::reject(input.stage, "prompt neural predecessor"));
        }
        if let Some(delivery) = self.prompt_delivery.as_ref() {
            if delivery.objective_digest() != input.objective_digest {
                return Err(Self::reject(input.stage, "prompt delivery objective"));
            }
            let started = Instant::now();
            let binding = prompt_binding::validate_prompt_delivery_v1(delivery)
                .map_err(|_| Self::reject(input.stage, "owner-backed prompt delivery"))?;
            self.within_budget(input, started)?;
            self.prompt_output = Some(binding.prompt_stage_digest);
            return Self::receipt(
                input,
                "prompt.optimizer",
                binding.prompt_stage_digest,
                CanonicalPortDecisionV1::Continue,
            );
        }
        let started = Instant::now();
        let receipt = optimize(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "prompt optimization"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "prompt authority"));
        }
        self.prompt_output = Some(receipt.receipt_digest);
        Self::receipt(
            input,
            "prompt.optimizer",
            receipt.receipt_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let mut request = Self::take(
            &mut self.intuition_request,
            input.stage,
            "intuition request",
        )?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "intuition objective"));
        }
        let neural = self
            .neural_output
            .ok_or_else(|| Self::reject(input.stage, "missing actual neural state"))?;
        let prompt = self
            .prompt_output
            .ok_or_else(|| Self::reject(input.stage, "missing actual prompt output"))?;
        if input.predecessor_digest != prompt {
            return Err(Self::reject(input.stage, "intuition prompt predecessor"));
        }
        let actual_state = if self.prompt_delivery.is_some() {
            prompt_binding::prompt_conditioned_state_digest_v1(neural, prompt)
        } else {
            neural
        };
        request.state_digest = bind_stage_digest(request.state_digest, actual_state, input.stage)?;
        let feasible = self
            .feasible_candidates
            .as_ref()
            .ok_or_else(|| Self::reject(input.stage, "missing actual utility feasibility"))?;
        if request.candidates.iter().any(|candidate| {
            candidate.legal && !candidate.hard_veto && !feasible.contains(&candidate.candidate_id)
        }) {
            return Err(Self::reject(
                input.stage,
                "intuition bypassed utility infeasibility",
            ));
        }
        let started = Instant::now();
        let receipt = decide_calibrated_v2(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "intuition decision"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "intuition authority"));
        }
        let decision = match &receipt.disposition {
            CalibratedDispositionV1::Selected(candidate_id) => {
                let probability = receipt
                    .propensities
                    .iter()
                    .find(|row| &row.candidate_id == candidate_id)
                    .map(|row| row.probability)
                    .filter(|value| value.raw() > 0)
                    .ok_or_else(|| Self::reject(input.stage, "selected propensity"))?;
                self.selected_candidate = Some(candidate_id.clone());
                CanonicalPortDecisionV1::Selected {
                    candidate_id: candidate_id.clone(),
                    propensity: probability,
                }
            }
            CalibratedDispositionV1::Abstained(_) => CanonicalPortDecisionV1::Abstained,
            CalibratedDispositionV1::SlowPath(_) => CanonicalPortDecisionV1::SlowPath,
        };
        Self::receipt(input, "intuition.policy", receipt.receipt_digest, decision)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.context_request, input.stage, "context request")?;
        if request.objective_digest != input.objective_digest
            || request.run_snapshot_digest != input.snapshot_digest
        {
            return Err(Self::reject(input.stage, "context binding"));
        }
        if let Some(delivery) = self.prompt_delivery.as_ref() {
            if delivery.objective_digest() != input.objective_digest {
                return Err(Self::reject(input.stage, "prompt delivery objective"));
            }
            let started = Instant::now();
            let binding = prompt_binding::validate_prompt_delivery_v1(delivery)
                .map_err(|_| Self::reject(input.stage, "owner-backed context delivery"))?;
            self.within_budget(input, started)?;
            if self.prompt_output != Some(binding.prompt_stage_digest) {
                return Err(Self::reject(input.stage, "prompt/context substitution"));
            }
            return Self::receipt(
                input,
                "context.compiler",
                binding.context_attachment_digest,
                CanonicalPortDecisionV1::Continue,
            );
        }
        let started = Instant::now();
        let receipt = compile(request);
        self.within_budget(input, started)?;
        let receipt = receipt.map_err(|_| Self::reject(input.stage, "context compile"))?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "context authority"));
        }
        Self::receipt(
            input,
            "context.compiler",
            receipt.context_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(
            &mut self.evaluation_request,
            input.stage,
            "evaluation request",
        )?;
        if request.objective_digest != input.objective_digest
            || self.selected_candidate.as_ref() != Some(&request.candidate_id)
        {
            return Err(Self::reject(input.stage, "evaluation binding"));
        }
        let session = Self::take(
            &mut self.evaluation_session,
            input.stage,
            "signed evaluation",
        )?;
        let started = Instant::now();
        let now = wall_clock_ms().map_err(|_| Self::reject(input.stage, "evaluation clock"))?;
        let receipt = session.evaluate(input, &request.candidate_id, now);
        self.within_budget(input, started)?;
        let receipt = receipt
            .map_err(|_| Self::reject(input.stage, "signed evaluation binding or evidence"))?;
        Self::receipt(
            input,
            "learning.eval",
            receipt,
            CanonicalPortDecisionV1::Continue,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(values: &[&str]) -> BTreeSet<StableId> {
        values
            .iter()
            .map(|value| StableId::new(*value).expect("id"))
            .collect()
    }

    #[test]
    fn utility_universe_rejects_foreign_and_missing_candidates() {
        let expected = ids(&["action.a", "action.b"]);
        assert!(
            validate_utility_universe(&expected, &ids(&["action.a", "action.b", "abstain"]))
                .is_ok()
        );
        assert!(
            validate_utility_universe(&expected, &ids(&["action.a", "action.b", "foreign"]))
                .is_err()
        );
        assert!(validate_utility_universe(&expected, &ids(&["action.a", "abstain"])).is_err());
    }

    #[test]
    fn actual_stage_outputs_fill_templates_but_reject_substitution() {
        let actual = Digest32::of_bytes(b"actual owner result");
        let other = Digest32::of_bytes(b"other owner result");
        let stage = CanonicalStageV1::IntuitionDecided;
        assert_eq!(
            bind_stage_digest(Digest32::ZERO, actual, stage).expect("template"),
            actual
        );
        assert_eq!(
            bind_stage_digest(actual, actual, stage).expect("matching input"),
            actual
        );
        assert!(bind_stage_digest(other, actual, stage).is_err());
        assert!(bind_stage_digest(Digest32::ZERO, Digest32::ZERO, stage).is_err());
    }
}
