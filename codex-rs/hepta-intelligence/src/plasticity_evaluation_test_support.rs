//! Real owner-runner test composition; deterministic observations are fixtures,
//! not measured learning efficacy or production persistence evidence.
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::Mutex;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Default)]
struct MemoryCas(Arc<Mutex<Option<FinalHoldoutCasRecordV1>>>);

impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let state = self
            .0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        if state
            .as_ref()
            .is_some_and(|record| record.binding != binding)
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        Ok(state.clone())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        let mut state = self
            .0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        if next.binding != binding || state.as_ref().map(|record| record.state_digest) != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        *state = Some(next.clone());
        Ok(())
    }
}

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

#[derive(Default)]
struct Sink;

impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"test.evaluated-shadow.product-evidence".to_vec();
        bytes.extend_from_slice(execution_digest.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub(super) fn qualify(
    mut plan: CrossFoldPlanV1,
    roles: Vec<MetricRoleContractV2>,
    generator: AuthenticatedPrincipalV1,
    evaluator: AuthenticatedPrincipalV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
    sign: impl Fn(LearningEvidenceRoleV1, &[u8]) -> SignedLearningEvidenceV1,
) -> Result<ProductQualificationReceiptV1, ProductEvaluationError> {
    let candidate = temporal_plan("candidate", plan.objective_digest);
    let baseline = temporal_plan("baseline", plan.objective_digest);
    // Keep the real frozen K-fold lineage while releasing this fixture's exact
    // final-window observations only through the fenced owner.
    plan.final_holdout_window_id = id("window-1");
    plan.final_holdout_digest = digest("test-holdout");
    plan.folds
        .last_mut()
        .expect("fixture folds")
        .holdout_windows = vec![id("window-1")];
    let sources = plan
        .metric_contracts
        .iter()
        .map(|metric| ProductMetricSourceContractV1 {
            metric_id: metric.metric_id.clone(),
            source: ProductMetricSourceV1::DoublyRobust,
        })
        .collect();
    let frozen =
        freeze_product_evaluation_plan_v1(plan, roles.clone(), sources, &candidate, &baseline)?;
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        MemoryCas::default(),
        digest("test-holdout-owner"),
        HoldoutWriterFenceV1 {
            owner_id: id("learning.eval"),
            generation: 1,
            lease_digest: digest("fixture-lease"),
        },
    )?;
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = runner.evaluate_temporal_comparison(
        &frozen,
        &candidate,
        &baseline,
        &mut provider_inputs(id("snapshot-1")),
    )?;
    let context = ProductQualificationContextV1 {
        generator,
        evaluator,
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = runner.qualification_bundle(&temporal, &context)?;
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            LearningEvidenceRoleV1::Generator,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            LearningEvidenceRoleV1::Evaluator,
            &evaluation_signing_payload_v2(&bundle, &roles)?,
        ),
    };
    runner.qualify_and_persist(
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        verifier,
        now,
        &mut Sink,
    )
}

fn temporal_plan(name: &str, objective_digest: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(&format!("{name}-evaluation")),
        objective_digest,
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope-plan")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(3_i64 << 31),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

fn provider_inputs(snapshot_id: StableId) -> Provider {
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("training-{action}-{index}")),
                principal_lineage: id(&format!("training-principal-{action}-{index}")),
                episode_lineage: id(&format!("training-episode-{action}-{index}")),
                window_id: id(&format!("training-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest("training-outcome"),
            });
        }
    }

    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..1024 {
        let decision_id = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("held-principal-{index}")),
            episode_lineage: id(&format!("held-episode-{index}")),
            window_id: id("window-1"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let observation = |a_probability: u64, b_probability: u64| OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(a_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(b_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("held-out-outcome"),
            outcome_model_evidence: digest("ignored-caller-model"),
        };
        candidate_observations.push(observation(3 << 30, 1 << 30));
        baseline_observations.push(observation(1 << 30, 3 << 30));
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Provider {
        manifest: digest("test-holdout"),
        inputs: Some(TemporalComparisonInputsV1 {
            training,
            targets,
            candidate_observations,
            baseline_observations,
            assignments,
            snapshot_ids: vec![snapshot_id],
            future_window_ids: vec![id("window-1")],
        }),
    }
}
