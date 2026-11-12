//! Declaration/codec mechanisms only: no original B execution or Qualified
//! receipt is created by these metadata fixtures. Real owner tests are separate.

use codex_hepta_intelligence_eval::ClusterConfidencePlan;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::OpePlan;
use codex_hepta_intelligence_eval::ProductEvaluationPolicyContextV2;
use codex_hepta_intelligence_eval::ProductEvaluationPolicyInputV2;
use codex_hepta_intelligence_eval::ProductEvaluationPolicyV2;
use codex_hepta_intelligence_eval::ProductMetricSourceContractV1;
use codex_hepta_intelligence_eval::ProductMetricSourceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::TemporalFoldPlan;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::Arm;
use super::OriginalCircuitOnPolicyComparisonPolicyV2;
use super::OriginalCircuitOnPolicyEvaluationPolicyV2;
use super::OriginalCircuitOnPolicyPanelPolicyV2;
use super::Pair;
use crate::CellCostCoverageV1;
use crate::CellParameterCapacityV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: digest("policy-objective"),
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("original-cluster-assumptions"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 3,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().expect("complete temporal digest");
    plan
}

fn fold(name: &str, window: &str) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(name),
        training_principals: vec![id(&format!("{name}-train-z")), id(&format!("{name}-train-a"))],
        training_episodes: vec![id(&format!("{name}-train-episode"))],
        training_windows: vec![id(&format!("{name}-past"))],
        holdout_principals: vec![id(&format!("{name}-held-principal"))],
        holdout_episodes: vec![id(&format!("{name}-held-episode"))],
        holdout_windows: vec![id(window)],
        model_digest: digest(&format!("{name}-declared-model")),
        predictions_digest: digest(&format!("{name}-declared-predictions")),
    }
}

fn inputs() -> (ProductEvaluationPolicyContextV2, ProductEvaluationPolicyInputV2) {
    let context = ProductEvaluationPolicyContextV2 {
        plan_id: id("policy-plan"),
        objective_digest: digest("policy-objective"),
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 3,
        final_holdout_window_id: id("final-window"),
        candidate_temporal: temporal("candidate-eval"),
        baseline_temporal: temporal("baseline-eval"),
    };
    let input = ProductEvaluationPolicyInputV2 {
        claim_scope: EvaluationClaimScopeV1::Qualification,
        base_estimand_digest: digest("policy-base-estimand"),
        baseline_id: id("original-baseline"),
        metric_contracts: vec![
            MetricContractV1 { metric_id: id("a-primary"), direction: EvaluationDirectionV1::Maximize, safety_floor: None },
            MetricContractV1 { metric_id: id("b-retention"), direction: EvaluationDirectionV1::Minimize, safety_floor: Some(FixedQ32::ONE) },
            MetricContractV1 { metric_id: id("c-absolute"), direction: EvaluationDirectionV1::Maximize, safety_floor: Some(FixedQ32::ZERO) },
        ],
        metric_roles: vec![
            MetricRoleContractV2 { metric_id: id("a-primary"), role: MetricRoleV2::PrimarySuperiority { minimum_improvement: FixedQ32::ZERO } },
            MetricRoleContractV2 { metric_id: id("b-retention"), role: MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::from_raw(7) } },
            MetricRoleContractV2 { metric_id: id("c-absolute"), role: MetricRoleV2::AbsoluteConstraint },
        ],
        metric_sources: vec![
            ProductMetricSourceContractV1 { metric_id: id("a-primary"), source: ProductMetricSourceV1::Ips },
            ProductMetricSourceContractV1 { metric_id: id("b-retention"), source: ProductMetricSourceV1::Snips },
            ProductMetricSourceContractV1 { metric_id: id("c-absolute"), source: ProductMetricSourceV1::DoublyRobust },
        ],
        folds: vec![fold("fold-a", "final-window"), fold("fold-b", "other-window")],
    };
    (context, input)
}


fn declaration(name: &str, count: usize) -> OriginalCircuitOnPolicyEvaluationPolicyV2 {
    let (mut context, input) = inputs();
    context.plan_id = id(name);
    let product = ProductEvaluationPolicyV2::freeze(context, input).expect("fixed pure metadata");
    let mut policy = OriginalCircuitOnPolicyEvaluationPolicyV2 {
        legacy_rule: digest(&format!("{name}-rule-v1")),
        task: digest(&format!("{name}-task")),
        snapshot: id(&format!("{name}-snapshot")),
        ledger: digest(&format!("{name}-ledger")),
        product,
        comparison: OriginalCircuitOnPolicyComparisonPolicyV2 {
            capacity: CellParameterCapacityV1 {
                total_parameters: 100, trainable_parameters: 80, maximum_active_parameters: 60,
            },
            cumulative: CellTrainingBudgetV1 {
                examples_seen: 100, optimizer_steps: 10, parameter_updates: 20,
                compute_units: 10, compute_unit_contract: digest("original-compute-units").into_array(),
            },
            selective_update: CellSelectiveUpdateV1 {
                policy_digest: digest("original-update-policy").into_array(),
                eligibility_digest: digest("original-eligibility").into_array(),
                schedule_digest: digest("original-schedule").into_array(),
                maximum_parameters_per_step: 8,
            },
            baseline_training_receipt_digest: digest("original-baseline-receipt-reference").into_array(),
            cost_coverage: CellCostCoverageV1::wall_and_cpu(digest("original-cost-coverage").into_array()),
        },
        baseline: digest("original-baseline-bundle"),
        pairs: (0..count).map(|index| {
            let arm = |tag: &str| Arm {
                decision: id(&format!("{name}-{tag}-run-{index:02}")),
                principal: id(&format!("original-principal-{index:02}")),
                episode: id(&format!("{name}-{tag}-episode-{index:02}")),
                run: id(&format!("{name}-{tag}-run-{index:02}")),
            };
            Pair {
                id: id(&format!("{name}-pair-{index:02}")),
                input: digest(&format!("{name}-original-input-{index:02}")),
                protocol: digest("original-protocol"),
                candidate: arm("candidate"),
                baseline: arm("baseline"),
            }
        }).collect(),
    };
    policy.validate().expect("metadata identities");
    policy
}

#[test]
fn v2_full_comparison_and_pair_policy_roundtrip_is_canonical() {
    let original = declaration("primary", 2);
    let bytes = original.canonical_commitment_bytes().expect("full policy bytes");
    assert_eq!(bytes.len(), 2550);
    assert_eq!(declaration("retention", 2).canonical_commitment_bytes().expect("retention bytes").len(), 2582);
    let decoded = OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&bytes)
        .expect("strict complete metadata decoder");
    assert_eq!(decoded, original);
    assert_eq!(decoded.canonical_commitment_bytes().expect("stable"), bytes);
    assert_ne!(decoded.cohort_rule_digest().expect("V2 rule"), decoded.legacy_rule);
    assert_eq!(decoded.comparison.baseline_training_receipt_digest,
        digest("original-baseline-receipt-reference").into_array());
}

#[test]
fn v2_panel_profile_commits_every_comparison_and_real_pair_identity() {
    let primary = declaration("primary", 2);
    let retention = declaration("retention", 2);
    let original = OriginalCircuitOnPolicyPanelPolicyV2::freeze(primary.clone(), vec![retention.clone()])
        .expect("complete metadata panel");
    let expected = original.registration().evaluation_profile();
    for slot in 0..21 {
        let mut changed = primary.clone();
        match slot {
            0 => changed.comparison.capacity.total_parameters += 1,
            1 => changed.comparison.capacity.trainable_parameters -= 1,
            2 => changed.comparison.capacity.maximum_active_parameters -= 1,
            3 => changed.comparison.cumulative.examples_seen += 1,
            4 => changed.comparison.cumulative.optimizer_steps += 1,
            5 => changed.comparison.cumulative.parameter_updates += 1,
            6 => changed.comparison.cumulative.compute_units += 1,
            7 => changed.comparison.cumulative.compute_unit_contract = digest("changed-units").into_array(),
            8 => changed.comparison.selective_update.policy_digest = digest("changed-update").into_array(),
            9 => changed.comparison.selective_update.eligibility_digest = digest("changed-eligibility").into_array(),
            10 => changed.comparison.selective_update.schedule_digest = digest("changed-schedule").into_array(),
            11 => changed.comparison.selective_update.maximum_parameters_per_step += 1,
            12 => changed.comparison.baseline_training_receipt_digest = digest("changed-reference").into_array(),
            13 => changed.comparison.cost_coverage.metering_contract_digest = digest("changed-meter").into_array(),
            14 => changed.comparison.cost_coverage.required_metrics.push(crate::CellRequiredCostMetricV1::Energy),
            15 => changed.pairs[0].input = digest("changed-original-input"),
            16 => changed.pairs[0].protocol = digest("changed-original-protocol"),
            17 => {
                changed.pairs[0].candidate.principal = id("changed-real-principal");
                changed.pairs[0].baseline.principal = id("changed-real-principal");
            }
            18 => changed.pairs[0].candidate.episode = id("changed-real-episode"),
            19 => {
                changed.pairs[0].candidate.decision = id("changed-real-run");
                changed.pairs[0].candidate.run = id("changed-real-run");
            }
            20 => changed.snapshot = id("changed-original-snapshot"),
            _ => unreachable!(),
        }
        changed.validate().expect("changed metadata still structurally valid");
        let candidate = OriginalCircuitOnPolicyPanelPolicyV2::freeze(changed, vec![retention.clone()])
            .expect("changed full declaration");
        assert_ne!(candidate.registration().evaluation_profile(), expected, "slot {slot}");
    }
}

#[test]
fn v2_decoder_rejects_legacy_truncation_tail_and_duplicate_real_identity() {
    let original = declaration("primary", 2);
    let bytes = original.canonical_commitment_bytes().expect("metadata bytes");
    for length in [0, 1, bytes.len() / 2, bytes.len() - 1] {
        assert!(OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&bytes[..length]).is_err());
    }
    let mut tail = bytes.clone();
    tail.push(0);
    assert!(OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&tail).is_err());
    let mut legacy = bytes.clone();
    let offset = b"hepta.circuit.original-on-policy-evaluation-policy.v".len();
    legacy[offset] = b'1';
    assert!(OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&legacy).is_err());
    let mut duplicate = original.clone();
    duplicate.pairs[1].candidate = duplicate.pairs[0].candidate.clone();
    let duplicate = duplicate.canonical_commitment_bytes().expect("bytes alone confer no validation");
    assert!(OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(&duplicate).is_err());
}

#[test]
fn v2_declaration_rejects_known_impossible_complete_policy_contribution() {
    let primary = declaration("primary", 31);
    let retention = (0..16).map(|index| declaration(&format!("retention-{index:02}"), 31))
        .collect::<Vec<_>>();
    let contribution = std::iter::once(&primary).chain(&retention)
        .map(|policy| 8 + policy.canonical_commitment_bytes().expect("complete preimage").len())
        .sum::<usize>();
    assert!(contribution >= 9 * 8192);
    assert!(OriginalCircuitOnPolicyPanelPolicyV2::freeze(primary, retention).is_err());
    let small = OriginalCircuitOnPolicyPanelPolicyV2::freeze(
        declaration("small-primary", 1), vec![declaration("small-retention", 1)],
    ).expect("necessary bound, not proof the whole E body fits");
    assert_eq!(small.registration().retention().len(), 1);
}
