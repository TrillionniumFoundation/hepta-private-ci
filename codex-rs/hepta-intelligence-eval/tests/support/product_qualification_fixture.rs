#![allow(clippy::unwrap_used)]
//! Product-qualification observations are synthetic test data, not field efficacy.
//! The holdout CAS and evidence publication use real temporary files and fsync.
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use std::io::Write;
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    objective: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    use ed25519_dalek::Signer;
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("fixture.{}", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: objective,
        authority_epoch: principal.authority_epoch,
        issued_at: principal.authenticated_at,
        expires_at: principal.expires_at - 1,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    signed
}

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
    release_count: usize,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if receipt.sequence == 0 {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.release_count += 1;
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

struct Fixture {
    cross_fold: CrossFoldPlanV1,
    roles: Vec<MetricRoleContractV2>,
    sources: Vec<ProductMetricSourceContractV1>,
    candidate_plan: TemporalEvaluationPlan,
    baseline_plan: TemporalEvaluationPlan,
    provider: Provider,
}

fn temporal_plan(name: &str, objective: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
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
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = match plan.canonical_digest() {
        Ok(digest) => digest,
        Err(error) => panic!("canonical temporal plan: {error}"),
    };
    plan
}

fn fixture(objective: Digest32, candidate_id: StableId) -> Fixture {
    let manifest = digest("final-holdout");
    let candidate_plan = temporal_plan("candidate-evaluation", objective);
    let baseline_plan = temporal_plan("baseline-evaluation", objective);
    let cross_fold = CrossFoldPlanV1 {
        plan_id: id("product-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id,
        baseline_id: id("baseline"),
        objective_digest: objective,
        dataset_digest: digest("dataset"),
        estimand_digest: digest("task-success-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-success"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-principal-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("past-a")],
                holdout_principals: vec![id("holdout-principal-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("final-window")],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-principal-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("past-b")],
                holdout_principals: vec![id("holdout-principal-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id("other-window")],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: manifest,
    };
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-success"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![ProductMetricSourceContractV1 {
        metric_id: id("task-success"),
        source: ProductMetricSourceV1::DoublyRobust,
    }];

    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("train-{action}-{index}")),
                principal_lineage: id(&format!("train-principal-{action}-{index}")),
                episode_lineage: id(&format!("train-episode-{action}-{index}")),
                window_id: id(&format!("train-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest(&format!("training-evidence-{action}-{index}")),
            });
        }
    }

    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    // Fixed before observations: 2,048 independent held-out decisions from a
    // balanced behavior policy. Candidate always chooses the rewarding action;
    // baseline chooses the other action. The existing conservative Hoeffding
    // intervals, alpha, weight ceiling and strict superiority gate are unchanged.
    for index in 0..2048 {
        let decision = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let make = |candidate: bool| OpeRow {
            decision_id: decision.clone(),
            chosen_action: id(if index % 2 == 0 { "a" } else { "b" }),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        1 << 32
                    } else {
                        0
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        0
                    } else {
                        1 << 32
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(if index % 2 == 0 {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            }),
            outcome_observed_at: 50,
            outcome_evidence: digest(&format!("heldout-outcome-{index}")),
            outcome_model_evidence: digest("ignored-model"),
        };
        candidate_observations.push(make(true));
        baseline_observations.push(make(false));
        assignments.push(ClusterAssignment {
            decision_id: decision,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Fixture {
        cross_fold,
        roles,
        sources,
        candidate_plan,
        baseline_plan,
        provider: Provider {
            manifest,
            inputs: Some(TemporalComparisonInputsV1 {
                training,
                targets,
                candidate_observations,
                baseline_observations,
                assignments,
                snapshot_ids: vec![id("snapshot-1")],
                future_window_ids: vec![id("final-window")],
            }),
            release_count: 0,
        },
    }
}

struct DurableSink(std::fs::File);
impl ProductQualificationEvidenceSinkV1 for DurableSink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"hepta.agentd.test-qualification-publication.v1".to_vec();
        bytes.extend_from_slice(execution.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        bytes.extend_from_slice(decision.authentication_digest.as_array());
        self.0
            .write_all(&bytes)
            .and_then(|()| self.0.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub struct QualificationCase {
    pub objective: Digest32,
    pub dataset: Digest32,
    pub candidate: StableId,
    pub baseline: StableId,
    pub snapshot_ids: Vec<StableId>,
}

#[derive(Clone, Debug)]
pub struct Qualified {
    pub receipt: ProductQualificationReceiptV1,
    pub bundle: IndependentEvaluationBundleV1,
    pub roles: Vec<MetricRoleContractV2>,
    pub evidence: SignedEvaluationEvidenceV1,
}

pub fn qualify(
    case: QualificationCase,
    verifier: &LearningEvidenceVerifierV1,
    generator: AuthenticatedPrincipalV1,
    evaluator: AuthenticatedPrincipalV1,
    keys: (&SigningKey, &SigningKey),
    now: u64,
) -> Qualified {
    qualify_with_sink(case, verifier, generator, evaluator, keys, now, |_| {
        Box::new(DurableSink(tempfile::tempfile().unwrap()))
    })
}

pub fn qualify_with_sink(
    case: QualificationCase,
    verifier: &LearningEvidenceVerifierV1,
    generator: AuthenticatedPrincipalV1,
    evaluator: AuthenticatedPrincipalV1,
    keys: (&SigningKey, &SigningKey),
    now: u64,
    sink_for_payload: impl FnOnce(&[u8]) -> Box<dyn ProductQualificationEvidenceSinkV1>,
) -> Qualified {
    let mut f = fixture(case.objective, case.candidate);
    f.cross_fold.dataset_digest = case.dataset;
    f.cross_fold.baseline_id = case.baseline;
    f.provider.inputs.as_mut().unwrap().snapshot_ids = case.snapshot_ids;
    let plan = freeze_product_evaluation_plan_v1(
        f.cross_fold,
        f.roles.clone(),
        f.sources,
        &f.candidate_plan,
        &f.baseline_plan,
    )
    .unwrap();
    let scope = digest("product-holdout.fixture");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(tempfile::tempfile().unwrap(), scope).unwrap();
    let mut issuer =
        HoldoutFenceIssuerV1::resume(id("fixture-owner"), digest("host-authority"), None).unwrap();
    let fence = issuer.issue(digest("fixture-lease")).unwrap();
    let owner = FencedFinalHoldoutOwnerV1::initialize(store, scope, fence).unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = runner
        .evaluate_temporal_comparison(&plan, &f.candidate_plan, &f.baseline_plan, &mut f.provider)
        .unwrap();
    assert_eq!(f.provider.release_count, 1);
    let context = ProductQualificationContextV1 {
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            verifier,
            &generator,
            keys.0,
            LearningEvidenceRoleV1::Generator,
            case.objective,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            verifier,
            &evaluator,
            keys.1,
            LearningEvidenceRoleV1::Evaluator,
            case.objective,
            &evaluation_signing_payload_v2(&bundle, &f.roles).unwrap(),
        ),
    };
    let publication_payload = runner
        .qualification_publication_payload(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            verifier,
            now,
        )
        .unwrap();
    let mut sink = sink_for_payload(&publication_payload);
    let receipt = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            verifier,
            now,
            sink.as_mut(),
        )
        .unwrap();
    assert_eq!(
        receipt.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        "fixture observations did not qualify: {:?}",
        bundle.metrics
    );
    Qualified {
        receipt,
        bundle,
        roles: f.roles,
        evidence,
    }
}
