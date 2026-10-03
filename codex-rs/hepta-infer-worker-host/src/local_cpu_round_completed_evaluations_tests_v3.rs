//! Untrusted public vectors exercise the material join and sole original codec;
//! only the actual completed reader can enter the production opaque API.
use super::*;
use codex_hepta_agent_components::intelligence::decode_parameter_plasticity_request_v1;
use codex_hepta_agent_components::intelligence::encode_parameter_plasticity_request_v1;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_types::FixedQ32;
#[path = "local_cpu_round_materials_test_fixture_v3.rs"]
mod fixture;
type TestResult = Result<(), Box<dyn std::error::Error>>;
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn evaluation(
    materials: &CpuNeuronRoundMaterialsV3,
) -> Result<CandidateEvaluationAdmissionV1, Box<dyn std::error::Error>> {
    let request = materials.request();
    let candidate = materials.candidates()[0].candidate_id.clone();
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("original.utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let fold = |a: &str, b: &str| CrossFoldPartitionV1 {
        fold_id: id(&format!("fold.{a}")),
        training_principals: vec![id(&format!("actor.{b}"))],
        training_episodes: vec![id(&format!("episode.{b}"))],
        training_windows: vec![id(&format!("train.{a}"))],
        holdout_principals: vec![id(&format!("actor.{a}"))],
        holdout_episodes: vec![id(&format!("episode.{a}"))],
        holdout_windows: vec![id(&format!("holdout.{a}"))],
        model_digest: digest(a),
        predictions_digest: digest(b),
    };
    let frozen_plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("original.frozen.plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: candidate.clone(),
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            dataset_digest: request.admission.dataset_digest,
            estimand_digest: digest("actual estimand vector"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("original.utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: None,
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![fold("one", "two"), fold("two", "one")],
            final_holdout_window_id: id("holdout.two"),
            final_holdout_digest: digest("actual original holdout vector"),
        },
        roles.clone(),
    )?;
    let holdout_use = FinalHoldoutRegistry::new().consume(&frozen_plan)?;
    let actor = |principal: StableId, key: &[u8]| AuthenticatedPrincipalV1 {
        principal_id: principal,
        credential_chain_digest: Digest32::of_bytes(key),
        signing_key_digest: Digest32::of_bytes(&[key, b"key"].concat()),
        scope_digest: materials.baseline.scope.scope_digest,
        authority_epoch: 1,
        authenticated_at: 1000,
        expires_at: 100_000,
    };
    let bundle = IndependentEvaluationBundleV1 {
        evaluation_id: id("original.evaluation.vector"),
        candidate_id: candidate,
        baseline_id: request.admission.baseline_id.clone(),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        generator: actor(request.generator_attestation.principal_id.clone(), b"g"),
        evaluator: actor(id("independent.evaluator.vector"), b"e"),
        frozen_plan,
        holdout_use,
        objective_digest: request.admission.objective_digest,
        dataset_digest: request.admission.dataset_digest,
        estimand_digest: digest("actual estimand vector"),
        estimate_receipt_digest: digest("whole estimate"),
        support_audit_digest: digest("whole support"),
        confidence_receipt_digest: digest("whole confidence"),
        retention_receipt_digests: vec![digest("whole retention")],
        unlearning_receipt_digest: digest("whole unlearning"),
        snapshot_ids: vec![id("snapshot.one"), id("snapshot.two")],
        future_window_ids: vec![id("holdout.one"), id("holdout.two")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricGateV1 {
            metric_id: id("original.utility"),
            direction: EvaluationDirectionV1::Maximize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(80),
                upper: FixedQ32::from_raw(90),
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(50),
                upper: FixedQ32::from_raw(60),
            },
            safety_floor: None,
            support_digest: digest("metric support"),
        }],
    };
    let mut evaluator_bundle = request.admission_attestation.clone();
    evaluator_bundle.role = LearningEvidenceRoleV1::Evaluator;
    evaluator_bundle.principal_id = bundle.evaluator.principal_id.clone();
    evaluator_bundle.signature = [0x74; 64];
    Ok(CandidateEvaluationAdmissionV1 {
        bundle,
        metric_roles: roles,
        evidence: SignedEvaluationEvidenceV1 {
            generator_plan: request.generator_attestation.clone(),
            evaluator_bundle,
        },
    })
}

#[test]
fn complete_e_frontier_is_inside_the_sole_original_request_and_survives_cold_raw_codec()
-> TestResult {
    let fixture = fixture::Fixture::new("/protected/rounds".into())?;
    let round = fixture.round("actual.goal.one", 1)?;
    let materials = fixture.derive(&round)?;
    let original = materials.request.clone();
    let evaluation = evaluation(&materials)?;
    let joined = materials.attach_complete_evaluation_frontier(vec![evaluation.clone()])?;
    let mut expected = original;
    expected.evaluations = vec![evaluation.clone()];
    assert_eq!(joined.request(), &expected);
    let bytes = encode_parameter_plasticity_request_v1(joined.request())?;
    assert_eq!(decode_parameter_plasticity_request_v1(&bytes)?, expected);
    let mut replaced = evaluation.clone();
    replaced.evidence.evaluator_bundle.signature[43] ^= 1;
    assert!(
        fixture
            .derive(&round)?
            .attach_complete_evaluation_frontier(vec![])
            .is_err()
    );
    assert!(
        fixture
            .derive(&round)?
            .attach_complete_evaluation_frontier(vec![evaluation.clone(), evaluation])
            .is_err()
    );
    assert!(
        joined
            .attach_complete_evaluation_frontier(vec![replaced])
            .is_err(),
        "an existing whole receipt cannot be silently replaced"
    );
    Ok(())
}

#[test]
fn completed_frontier_cannot_change_original_candidate_baseline_dataset_or_generator() -> TestResult
{
    let fixture = fixture::Fixture::new("/protected/rounds".into())?;
    let round = fixture.round("actual.goal.one", 1)?;
    for field in 0..5 {
        let materials = fixture.derive(&round)?;
        let mut value = evaluation(&materials)?;
        match field {
            0 => value.bundle.candidate_id = id("foreign.candidate"),
            1 => value.bundle.baseline_id = id("foreign.baseline"),
            2 => value.bundle.objective_digest = digest("foreign objective"),
            3 => value.bundle.dataset_digest = digest("foreign dataset"),
            4 => value.bundle.generator.principal_id = id("foreign.generator"),
            _ => unreachable!(),
        }
        assert!(
            materials
                .attach_complete_evaluation_frontier(vec![value])
                .is_err()
        );
    }
    Ok(())
}
