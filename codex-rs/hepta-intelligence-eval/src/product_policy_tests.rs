//! Pure metadata and encoding mechanisms, not actual B runs or adoption evidence.
use super::*;
use codex_hepta_types::FixedQ32;
use crate::ClusterConfidencePlan;
use crate::EvaluationDirectionV1;
use crate::MetricRoleV2;
use crate::OnPolicyArmBindingV1;
use crate::OnPolicyPairContractV1;
use crate::OpePlan;
use crate::ProductMetricSourceV1;
use crate::TemporalFoldPlan;

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

fn policy() -> ProductEvaluationPolicyV2 {
    let (context, input) = inputs();
    ProductEvaluationPolicyV2::freeze(context, input).expect("bounded original policy")
}

fn bindings() -> ProductEvaluationPolicyBindingsV2 {
    ProductEvaluationPolicyBindingsV2 {
        candidate_id: id("actual-candidate"),
        dataset_digest: digest("actual-dataset"),
        final_holdout_digest: digest("actual-manifest"),
        cell_estimand_digest: digest("actual-cell-estimand"),
    }
}

fn pairing() -> OnPolicyPairingContractV1 {
    OnPolicyPairingContractV1 {
        pairs: (0..2).map(|index| {
            let arm = |name: &str| OnPolicyArmBindingV1 {
                decision_id: id(&format!("{name}-run-{index}")),
                principal_lineage: id(&format!("original-principal-{index}")),
                episode_lineage: id(&format!("{name}-episode-{index}")),
                behavior_run_id: id(&format!("{name}-run-{index}")),
                model_digest: digest(&format!("{name}-model")),
            };
            OnPolicyPairContractV1 {
                pair_id: id(&format!("pair-{index}")),
                input_digest: digest(&format!("input-{index}")),
                protocol_digest: digest("original-protocol"),
                candidate: arm("candidate"),
                baseline: arm("baseline"),
            }
        }).collect(),
    }
}

#[test]
fn policy_v2_roundtrip_normalizes_only_order_and_preserves_every_value() {
    let original = policy();
    let bytes = original.canonical_commitment_bytes().expect("canonical metadata");
    assert_eq!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&bytes), Ok(original.clone()));
    let (context, mut input) = inputs();
    input.metric_contracts.reverse();
    input.metric_roles.reverse();
    input.metric_sources.reverse();
    input.folds.reverse();
    for fold in &mut input.folds {
        fold.training_principals.reverse();
    }
    assert_eq!(ProductEvaluationPolicyV2::freeze(context, input), Ok(original.clone()));
    assert_eq!(original.input.baseline_id, id("original-baseline"));
    assert_eq!(original.context.candidate_temporal.ope.maximum_weight, FixedQ32::from_raw(4_i64 << 32));
    assert_eq!(original.input.metric_roles[1].role, MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::from_raw(7) });
}

#[test]
fn policy_v2_all_pre_b_fields_change_the_commitment_or_are_rejected() {
    let original = policy();
    let expected = original.digest().expect("original digest");
    for slot in 0..49 {
        let mut context = original.context.clone();
        let mut input = original.input.clone();
        match slot {
            0 => context.plan_id = id("changed-plan"),
            1 => context.objective_digest = digest("changed-objective"),
            2 => context.family_alpha_ppm += 1,
            3 => context.simultaneous_comparisons += 1,
            4 => context.final_holdout_window_id = id("changed-window"),
            5 => input.claim_scope = EvaluationClaimScopeV1::SystemLongitudinal,
            6 => input.base_estimand_digest = digest("changed-base"),
            7 => input.baseline_id = id("changed-baseline"),
            8 => input.metric_contracts[0].metric_id = id("changed-metric"),
            9 => input.metric_contracts[0].direction = EvaluationDirectionV1::Minimize,
            10 => input.metric_contracts[0].safety_floor = Some(FixedQ32::from_raw(11)),
            11 => input.metric_roles[0].metric_id = id("changed-role"),
            12 => input.metric_roles[0].role = MetricRoleV2::PrimarySuperiority { minimum_improvement: FixedQ32::from_raw(1) },
            13 => input.metric_roles[1].role = MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::from_raw(8) },
            14 => input.metric_sources[0].metric_id = id("changed-source"),
            15 => input.metric_sources[0].source = ProductMetricSourceV1::DoublyRobust,
            16 => input.folds[0].fold_id = id("changed-fold"),
            17 => input.folds[0].training_principals.push(id("changed-train-principal")),
            18 => input.folds[0].training_episodes.push(id("changed-train-episode")),
            19 => input.folds[0].training_windows.push(id("changed-train-window")),
            20 => input.folds[0].holdout_principals.push(id("changed-held-principal")),
            21 => input.folds[0].holdout_episodes.push(id("changed-held-episode")),
            22 => input.folds[0].holdout_windows.push(id("changed-held-window")),
            23 => input.folds[0].model_digest = digest("changed-declared-model"),
            24 => input.folds[0].predictions_digest = digest("changed-declared-predictions"),
            25..=46 => {
                let baseline = slot >= 36;
                let plan = if baseline { &mut context.baseline_temporal } else { &mut context.candidate_temporal };
                match (slot - 25) % 11 {
                    0 => plan.plan_digest = digest("changed-plan-digest"),
                    1 => plan.evaluation_id = id("changed-evaluation"),
                    2 => plan.objective_digest = digest("changed-temporal-objective"),
                    3 => plan.fold.plan_digest = digest("changed-fold-plan"),
                    4 => plan.fold.fold_id = id("changed-temporal-fold"),
                    5 => plan.fold.training_watermark += 1,
                    6 => plan.fold.evaluation_start += 1,
                    7 => plan.fold.minimum_per_action += 1,
                    8 => plan.ope.plan_digest = digest("changed-ope-plan"),
                    9 => plan.ope.outcome_watermark += 1,
                    _ => plan.ope.maximum_weight = FixedQ32::from_raw(3_i64 << 32),
                }
                // A field remains committed even when its complete temporal
                // digest is validly recomputed; no caller clock is introduced.
                if (slot - 25) % 11 != 0 {
                    plan.plan_digest = plan.canonical_digest().expect("mutated full temporal digest");
                }
            }
            47 => input.metric_roles[2].role = MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::ZERO },
            _ => input.folds.push(fold("fold-c", "third-window")),
        }
        if let Ok(changed) = ProductEvaluationPolicyV2::freeze(context, input) {
            assert_ne!(changed.digest().expect("changed digest"), expected, "slot {slot}");
        }
    }
    for arm in 0..2 {
        for slot in 0..7 {
            let mut context = original.context.clone();
            let plan = if arm == 0 { &mut context.candidate_temporal } else { &mut context.baseline_temporal };
            match slot {
                0 => plan.ope.minimum_rows += 1,
                1 => plan.ope.minimum_ess = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
                2 => plan.confidence.plan_digest = digest("changed-confidence-plan"),
                3 => plan.confidence.assumptions_digest = digest("changed-assumptions"),
                4 => plan.confidence.family_alpha_ppm += 1,
                5 => plan.confidence.simultaneous_comparisons += 1,
                _ => plan.confidence.minimum_clusters += 1,
            }
            plan.plan_digest = plan.canonical_digest().expect("mutated full temporal digest");
            if let Ok(changed) = ProductEvaluationPolicyV2::freeze(context, original.input.clone()) {
                assert_ne!(changed.digest().expect("changed digest"), expected, "arm {arm} slot {slot}");
            }
        }
    }
}

#[test]
fn policy_v2_strict_decode_refuses_noncanonical_malformed_and_unbounded_metadata() {
    let original = policy();
    let bytes = original.canonical_commitment_bytes().expect("canonical");
    for cut in 0..bytes.len() {
        assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&bytes[..cut]).is_err(), "cut {cut}");
    }
    let mut extra = bytes.clone();
    extra.push(0);
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&extra).is_err());
    let mut version = bytes.clone();
    version[0] ^= 1;
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&version).is_err());
    let mut reordered = original.input.clone();
    reordered.metric_roles.reverse();
    let raw = codec::encode(&original.context, &reordered).expect("bounded noncanonical input");
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&raw).is_err());
    let mut duplicate = original.input.clone();
    duplicate.metric_roles[1] = duplicate.metric_roles[0].clone();
    let raw = codec::encode(&original.context, &duplicate).expect("bounded duplicate input");
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&raw).is_err());
    let metric = b"a-primary";
    let offsets: Vec<_> = bytes.windows(metric.len()).enumerate()
        .filter_map(|(offset, value)| (value == metric).then_some(offset)).collect();
    assert_eq!(offsets.len(), 3);
    // Direction, optional floor, role and metric source each reject unknown tags.
    for offset in [offsets[0] + metric.len(), offsets[0] + metric.len() + 1,
        offsets[1] + metric.len(), offsets[2] + metric.len()] {
        let mut invalid = bytes.clone();
        invalid[offset] = 255;
        assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&invalid).is_err());
    }
    let mut count_overflow = bytes.clone();
    count_overflow[offsets[0] - 6..offsets[0] - 2].fill(255);
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&count_overflow).is_err());
    let mut invalid_id = bytes.clone();
    invalid_id[offsets[0] - 2..offsets[0]].fill(0);
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&invalid_id).is_err());
    let mut oversized = original.input.clone();
    oversized.folds[0].training_episodes = (0..20_000).map(|index| id(&format!("large-episode-{index}"))).collect();
    assert!(ProductEvaluationPolicyV2::freeze(original.context.clone(), oversized).is_err());
    assert!(ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&vec![0; 131_073]).is_err());
}

#[test]
fn policy_v2_remote_metadata_matches_original_local_freeze_without_releasing_data() {
    let original = policy();
    let bindings = bindings();
    let pairing = pairing();
    let local = original.instantiate(&bindings, &pairing).expect("original freezer");
    let remote = original.expected_commitment_bytes(&bindings, &pairing).expect("raw expected bytes");
    assert_eq!(remote.plan(), super::super::product_plan_commitment_bytes(&local).expect("original plan bytes"));
    assert_eq!(remote.estimand(), super::super::plan_estimand_commitment_bytes(&local).expect("original estimand bytes"));
    assert_eq!(remote.roles(), role_contract_commitment_bytes(&mut local.metric_contracts.clone(), &mut local.metric_roles.clone()).expect("original role bytes"));
    assert_eq!(local.frozen_plan.authority, codex_hepta_types::AuthorityPosture::DENY_ALL);
    let cold = ProductEvaluationPolicyV2::from_canonical_commitment_bytes(&original.canonical_commitment_bytes().expect("policy bytes")).expect("metadata decode");
    assert_eq!(cold.expected_commitment_bytes(&bindings, &pairing), Ok(remote));
    assert_eq!(cold.instantiate(&bindings, &pairing), Ok(local));
}

#[test]
fn policy_v2_late_bindings_cannot_change_policy_or_reuse_old_plan_bytes() {
    let original = policy();
    let before = original.digest().expect("pre-B digest");
    let pair = pairing();
    let expected = original.expected_commitment_bytes(&bindings(), &pair).expect("original bindings");
    for slot in 0..4 {
        let mut changed = bindings();
        match slot {
            0 => changed.candidate_id = id("different-actual-candidate"),
            1 => changed.dataset_digest = digest("different-actual-dataset"),
            2 => changed.final_holdout_digest = digest("different-actual-manifest"),
            _ => changed.cell_estimand_digest = digest("different-actual-cell"),
        }
        assert_ne!(original.expected_commitment_bytes(&changed, &pair).expect("new bindings").plan(), expected.plan(), "late slot {slot}");
        assert_eq!(original.digest().expect("unchanged policy"), before);
    }
    for slot in 0..3 {
        let mut invalid = bindings();
        match slot {
            0 => invalid.dataset_digest = Digest32::ZERO,
            1 => invalid.final_holdout_digest = Digest32::ZERO,
            _ => invalid.cell_estimand_digest = Digest32::ZERO,
        }
        assert!(original.instantiate(&invalid, &pair).is_err());
        assert!(original.expected_commitment_bytes(&invalid, &pair).is_err());
    }
    let mut changed_pair = pair.clone();
    changed_pair.pairs[0].input_digest = digest("different-input");
    assert_ne!(original.expected_commitment_bytes(&bindings(), &changed_pair).expect("different input").plan(), expected.plan());
    changed_pair.pairs[1].candidate.behavior_run_id = changed_pair.pairs[0].candidate.behavior_run_id.clone();
    assert!(original.expected_commitment_bytes(&bindings(), &changed_pair).is_err());
}

#[test]
fn policy_v2_keeps_original_role_fold_and_temporal_rejections() {
    for slot in 0..12 {
        let (mut context, mut input) = inputs();
        match slot {
            0 => input.metric_roles[0].role = MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::ZERO },
            1 => input.metric_roles[0].role = MetricRoleV2::PrimarySuperiority { minimum_improvement: FixedQ32::from_raw(-1) },
            2 => input.metric_roles[1].role = MetricRoleV2::NonInferiority { maximum_regression: FixedQ32::from_raw(-1) },
            3 => input.metric_contracts[2].safety_floor = None,
            4 => input.metric_contracts[1].metric_id = input.metric_contracts[0].metric_id.clone(),
            5 => { input.metric_sources.pop(); },
            6 => input.folds[0].training_principals = input.folds[0].holdout_principals.clone(),
            7 => input.folds[0].training_windows.push(context.final_holdout_window_id.clone()),
            8 => input.folds[1].holdout_episodes = input.folds[0].holdout_episodes.clone(),
            9 => input.folds[0].model_digest = Digest32::ZERO,
            10 => context.baseline_temporal.evaluation_id = context.candidate_temporal.evaluation_id.clone(),
            _ => context.candidate_temporal.plan_digest = Digest32::ZERO,
        }
        assert!(ProductEvaluationPolicyV2::freeze(context, input).is_err(), "original rejection {slot}");
    }
}

#[test]
fn policy_v2_shared_and_paired_original_commitment_bytes_remain_exact() {
    // Fixed pre-change FDE encoders projected independently from their complete
    // raw field order. These are codec vectors, not runtime B observations.
    let original = policy();
    let binding = bindings();
    let shared = super::super::freeze_product_evaluation_plan_v1(
        original.bound_plan(&binding), original.input.metric_roles.clone(),
        original.input.metric_sources.clone(), &original.context.candidate_temporal,
        &original.context.baseline_temporal,
    ).expect("legacy SharedBehavior freeze");
    let paired = original.instantiate(&binding, &pairing()).expect("original paired freeze");
    assert_eq!(shared.frozen_plan.plan_digest.to_string(), "f27f101e19c7f4302d4edaf0d9d4b79a30019e1bfc0a25b28ec15c6929db5f84");
    assert_eq!(paired.frozen_plan.plan_digest.to_string(), "836cf09bc96ba96122798efc5535fef36ca61dfe47a84c9d640de3c64a95f119");
    assert_eq!(Digest32::of_bytes(&super::super::product_plan_commitment_bytes(&shared).expect("legacy plan")).to_string(), "d4ca86dc405b8f07ae4bc1547372784e42d4044339e659d8f42b495d47a27735");
    assert_eq!(Digest32::of_bytes(&super::super::plan_estimand_commitment_bytes(&shared).expect("legacy estimand")).to_string(), "fce0ff3a02a654ebbd219a309b1e27afdd51632eed008ef41944f18f6b619782");
    assert_eq!(Digest32::of_bytes(&super::super::product_plan_commitment_bytes(&paired).expect("paired plan")).to_string(), "9ddb817ecb5f44e88e075effe27d1f76b69939e2548035ccb57bb22648beb31a");
    assert_eq!(Digest32::of_bytes(&super::super::plan_estimand_commitment_bytes(&paired).expect("paired estimand")).to_string(), "3d099f76023824e58b354ba4cb6a9c0f57f90da191d8c516f50f3b94f89a87df");
    assert_eq!(shared.metric_roles, original.input.metric_roles);
    assert_eq!(shared.metric_contracts, original.input.metric_contracts);
    assert_eq!(shared.metric_sources, original.input.metric_sources);
}
