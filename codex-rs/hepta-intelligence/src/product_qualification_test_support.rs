//! Real estimator execution with locked, fsynced CAS and publication fixtures.
//! These synthetic observations verify wiring; they are not empirical evidence.
use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) struct DurableSink {
    file: File,
}
impl DurableSink {
    pub(super) fn new() -> Self {
        Self {
            file: tempfile::tempfile().unwrap(),
        }
    }
    pub(super) fn assert_publication(&mut self, digest: Digest32) {
        self.file.seek(SeekFrom::Start(0)).unwrap();
        let mut bytes = Vec::new();
        self.file.read_to_end(&mut bytes).unwrap();
        assert_eq!(Digest32::of_bytes(&bytes), digest);
    }
}
impl ProductQualificationEvidenceSinkV1 for DurableSink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"test.product-publication.v1".to_vec();
        for digest in [
            execution,
            decision.decision.evidence_digest,
            decision.authentication_digest,
            decision.trust_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            &decision.decision.evaluation_id,
            &decision.decision.candidate_id,
            &decision.decision.baseline_id,
        ] {
            bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
            bytes.extend_from_slice(value.as_str().as_bytes());
        }
        bytes.push(match decision.decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
            IndependentEvaluationDispositionV1::Ineligible => 1,
            IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
        });
        self.file
            .write_all(&bytes)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
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
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        assert!(receipt.sequence > 0);
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

fn temporal_plan(name: &str, objective_digest: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest,
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold")),
            fold_id: id(name),
            training_watermark: 5,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 50,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(3_i64 << 31),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("independent-fixture-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

pub(super) fn evaluate(
    cross_fold: CrossFoldPlanV1,
    roles: Vec<MetricRoleContractV2>,
    snapshot_ids: Vec<StableId>,
    future_window_ids: Vec<StableId>,
) -> (
    ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    ProductTemporalEvaluationReceiptV1,
) {
    let candidate = temporal_plan("fixture-candidate", cross_fold.objective_digest);
    let baseline = temporal_plan("fixture-baseline", cross_fold.objective_digest);
    let sources = cross_fold
        .metric_contracts
        .iter()
        .map(|metric| ProductMetricSourceContractV1 {
            metric_id: metric.metric_id.clone(),
            source: ProductMetricSourceV1::DoublyRobust,
        })
        .collect();
    let frozen = freeze_product_evaluation_plan_v1(
        cross_fold.clone(),
        roles,
        sources,
        &candidate,
        &baseline,
    )
    .unwrap();
    let binding = digest("fixture-holdout-owner");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(tempfile::tempfile().unwrap(), binding).unwrap();
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        binding,
        HoldoutWriterFenceV1 {
            owner_id: id("fixture-eval-owner"),
            generation: 1,
            lease_digest: digest("fixture-lease"),
        },
    )
    .unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let initial = runner.holdout_anchor();
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("train-{action}-{index}")),
                principal_lineage: id(&format!("train-principal-{action}-{index}")),
                episode_lineage: id(&format!("train-episode-{action}-{index}")),
                window_id: id(&format!("train-window-{action}-{index}")),
                action_id: id(action),
                observed_at: 5,
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                evidence_digest: digest("fixture-training-outcome"),
            });
        }
    }
    let longitudinal = cross_fold.claim_scope == EvaluationClaimScopeV1::SystemLongitudinal;
    let window_snapshots = if longitudinal {
        future_window_ids
            .iter()
            .enumerate()
            .map(|(index, window)| ProductWindowSnapshotBindingV1 {
                window_id: window.clone(),
                snapshot_id: snapshot_ids[index + 1].clone(),
            })
            .collect()
    } else {
        vec![]
    };
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
            window_id: if longitudinal {
                future_window_ids[index % future_window_ids.len()].clone()
            } else {
                cross_fold.final_holdout_window_id.clone()
            },
            decision_at: if longitudinal && index % 2 == 1 {
                26
            } else {
                20
            },
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
            outcome_observed_at: if longitudinal {
                if index % 2 == 0 { 25 } else { 40 }
            } else {
                50
            },
            outcome_evidence: digest("fixture-heldout-outcome"),
            outcome_model_evidence: digest("ignored-caller-model"),
        };
        candidate_observations.push(observation(3 << 30, 1 << 30));
        baseline_observations.push(observation(1 << 30, 3 << 30));
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    let mut provider = Provider {
        manifest: cross_fold.final_holdout_digest,
        inputs: Some(TemporalComparisonInputsV1 {
            training_snapshot_id: if longitudinal {
                Some(snapshot_ids[0].clone())
            } else {
                None
            },
            window_snapshots,
            training,
            targets,
            candidate_observations,
            baseline_observations,
            assignments,
            snapshot_ids,
            future_window_ids,
        }),
    };
    let temporal = runner
        .evaluate_temporal_comparison(&frozen, &candidate, &baseline, &mut provider)
        .unwrap();
    assert_ne!(initial, runner.holdout_anchor());
    assert!(provider.inputs.is_none());
    (runner, temporal)
}
