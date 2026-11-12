//! Synthetic paired mechanism data. The identities, keys and outcomes below
//! are unit fixtures, not deployed B tasks, original Source custody or efficacy.
use super::super::*;
use pretty_assertions::assert_eq;
use crate::OnPolicyArmBindingV1;
use crate::OnPolicyArmProvenanceV1;
use crate::OnPolicyEvaluationArmInputsV1;
use crate::OnPolicyPairContractV1;
use crate::OnPolicyPairingContractV1;
use crate::OnPolicyTemporalComparisonInputsV1;
use crate::freeze_paired_on_policy_product_evaluation_plan_v1;

pub(super) struct PairedProvider {
    pub(super) manifest: Digest32,
    pub(super) pairing_digest: Digest32,
    pub(super) inputs: Option<OnPolicyTemporalComparisonInputsV1>,
    pub(super) releases: usize,
    pub(super) shared_releases: usize,
}

impl FinalHoldoutProviderV1 for PairedProvider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.shared_releases += 1;
        Err(ProductProviderErrorV1::Rejected)
    }

    fn release_paired_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
        pairing: &OnPolicyPairingContractV1,
    ) -> Result<OnPolicyTemporalComparisonInputsV1, ProductProviderErrorV1> {
        if receipt.sequence == 0
            || pairing.digest().map_err(|_| ProductProviderErrorV1::Rejected)? != self.pairing_digest
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.releases += 1;
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

pub(super) struct PairedHarness {
    pub(super) original: Harness,
    pub(super) pairing: OnPolicyPairingContractV1,
    pub(super) provider: PairedProvider,
}

impl PairedHarness {
    pub(super) fn new(count: usize, equal_outcomes: bool, one_principal: bool) -> Self {
        let mut original = Harness::new();
        // This fixture explicitly preregisters IPS before outcomes are released.
        // Alpha, original primary threshold and weight cap four remain unchanged.
        original.fixture.sources[0].source = ProductMetricSourceV1::Ips;
        let training = original.fixture.provider.inputs.as_ref()
            .expect("unreleased original training fixture").training.clone();
        let mut candidate = empty_arm();
        let mut baseline = empty_arm();
        let mut pairs = Vec::new();
        for index in 0..count {
            let principal = if one_principal {
                id("paired-one-original-principal")
            } else {
                id(&format!("paired-original-principal-{index}"))
            };
            let input_digest = digest(&format!("paired-frozen-input-{index}"));
            let protocol_digest = digest("paired-frozen-protocol");
            let candidate_binding = binding("candidate", index, principal.clone());
            let baseline_binding = binding("baseline", index, principal);
            add_arm(
                &mut candidate, &candidate_binding, input_digest, protocol_digest,
                true, equal_outcomes,
            );
            add_arm(
                &mut baseline, &baseline_binding, input_digest, protocol_digest,
                false, equal_outcomes,
            );
            pairs.push(OnPolicyPairContractV1 {
                pair_id: id(&format!("original-pair-{index}")),
                input_digest,
                protocol_digest,
                candidate: candidate_binding,
                baseline: baseline_binding,
            });
        }
        let pairing = OnPolicyPairingContractV1 { pairs };
        original.frozen = freeze_paired_on_policy_product_evaluation_plan_v1(
            original.fixture.cross_fold.clone(),
            original.fixture.roles.clone(),
            original.fixture.sources.clone(),
            &original.fixture.candidate_plan,
            &original.fixture.baseline_plan,
            pairing.clone(),
        ).expect("separately frozen original paired mode");
        let provider = PairedProvider {
            manifest: original.fixture.provider.manifest,
            pairing_digest: pairing.digest().expect("paired fixture contract"),
            inputs: Some(OnPolicyTemporalComparisonInputsV1 {
                training, candidate, baseline,
                snapshot_ids: vec![id("paired-original-snapshot")],
                future_window_ids: vec![id("final-window")],
            }),
            releases: 0,
            shared_releases: 0,
        };
        Self { original, pairing, provider }
    }

    pub(super) fn run(&mut self) -> Result<ProductTemporalEvaluationReceiptV1, Error> {
        let original = &mut self.original;
        let at = original.now;
        let clock = || Ok(at);
        original.runner.evaluate_or_readback_temporal_comparison(
            &ProductEvaluationExecutionRequestV1 {
                plan: &original.frozen,
                candidate_plan: &original.fixture.candidate_plan,
                baseline_plan: &original.fixture.baseline_plan,
                evaluator: &original.context.evaluator,
                verifier: &original.verifier,
                clock: &clock,
            },
            &mut self.provider,
            &mut original.executions,
            &mut original.attestor,
        )
    }

    pub(super) fn qualify(
        &self,
        executed: &ProductTemporalEvaluationReceiptV1,
    ) -> ProductQualificationReceiptV1 {
        let original = &self.original;
        let bundle = original.runner.qualification_bundle(executed, &original.context)
            .expect("original evaluator execution bundle");
        let (context, signed, verifier) = signed_context(&bundle, &original.fixture.roles);
        let mut sink = Sink::default();
        let receipt = original.runner.qualify_and_persist(
            executed, &context, &signed, ProductTimingEvidenceV1::Qualification,
            &verifier, 50, &mut sink,
        ).expect("original signed qualification owner");
        assert_eq!(sink.persisted, vec![receipt.publication_digest]);
        receipt
    }
}

fn empty_arm() -> OnPolicyEvaluationArmInputsV1 {
    OnPolicyEvaluationArmInputsV1 {
        targets: Vec::new(), observations: Vec::new(),
        assignments: Vec::new(), provenance: Vec::new(),
    }
}

fn binding(arm: &str, index: usize, principal_lineage: StableId) -> OnPolicyArmBindingV1 {
    let run = id(&format!("original-{arm}-run-{index}"));
    OnPolicyArmBindingV1 {
        decision_id: run.clone(),
        principal_lineage,
        episode_lineage: id(&format!("original-{arm}-episode-{index}")),
        behavior_run_id: run,
        model_digest: digest(&format!("original-{arm}-model")),
    }
}

fn add_arm(
    arm: &mut OnPolicyEvaluationArmInputsV1,
    binding: &OnPolicyArmBindingV1,
    input_digest: Digest32,
    protocol_digest: Digest32,
    candidate: bool,
    equal_outcomes: bool,
) {
    let chosen = if candidate { id("a") } else { id("b") };
    arm.targets.push(HeldOutTarget {
        decision_id: binding.decision_id.clone(),
        principal_lineage: binding.principal_lineage.clone(),
        episode_lineage: binding.episode_lineage.clone(),
        window_id: id("final-window"),
        decision_at: if candidate { 20 } else { 21 },
        actions: vec![id("a"), id("b")],
    });
    arm.observations.push(OpeRow {
        decision_id: binding.decision_id.clone(),
        chosen_action: chosen.clone(),
        complete_candidates: true,
        actions: ["a", "b"].into_iter().map(|name| {
            let action_id = id(name);
            let probability = ProbabilityQ32::from_raw(if action_id == chosen { 1_u64 << 32 } else { 0 })
                .expect("actual deterministic fixture probability");
            OpeAction {
                action_id,
                behavior_probability: probability,
                evaluation_probability: probability,
                predicted_outcome: FixedQ32::ZERO,
            }
        }).collect(),
        finalized_outcome: Some(if candidate || equal_outcomes { FixedQ32::ONE } else { FixedQ32::ZERO }),
        outcome_observed_at: if candidate { 50 } else { 49 },
        outcome_evidence: digest(&format!("outcome-for-{}", binding.behavior_run_id)),
        outcome_model_evidence: digest("ignored-original-prediction-input"),
    });
    arm.assignments.push(ClusterAssignment {
        decision_id: binding.decision_id.clone(),
        cluster_id: binding.principal_lineage.clone(),
    });
    arm.provenance.push(OnPolicyArmProvenanceV1 {
        decision_id: binding.decision_id.clone(),
        episode_lineage: binding.episode_lineage.clone(),
        behavior_run_id: binding.behavior_run_id.clone(),
        model_digest: binding.model_digest,
        input_digest,
        protocol_digest,
        checkpoint_before: Digest32::ZERO,
        source_evidence_digest: digest(&format!("source-for-{}", binding.behavior_run_id)),
        execution_evidence_digest: digest(&format!("execution-for-{}", binding.behavior_run_id)),
    });
}
