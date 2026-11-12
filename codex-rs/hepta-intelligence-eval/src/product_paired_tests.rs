//! Mechanism coverage for explicitly frozen paired inputs. These tests retain
//! the original fenced holdout, execution signature and Qualification owners.
//! Their synthetic identities and outcomes are not actual B-task evidence.
use super::*;
use crate::ProductComparisonModeV1;
use crate::freeze_paired_on_policy_product_evaluation_plan_v1;

#[path = "product_paired_support_tests.rs"]
mod support;
use support::PairedHarness;

#[test]
fn paired_default_provider_refuses_after_one_original_consumption() {
    let mut test = PairedHarness::new(2, false, false);
    let before = test.original.runner.holdout_anchor();
    assert_eq!(
        test.original.run(),
        Err(Error::Evaluation(ProductEvaluationError::Provider(
            ProductProviderErrorV1::Rejected,
        ))),
    );
    assert_ne!(test.original.runner.holdout_anchor(), before);
    let consumed = test.original.runner.holdout_anchor();
    assert!(matches!(test.original.executions.state, Some((_, State::Pending))));
    test.original.reopen();
    let recovered = test.original.runner.holdout_anchor();
    assert_ne!(recovered, consumed);
    assert_eq!(test.original.run(), Err(Error::Pending));
    assert_eq!(test.original.runner.holdout_anchor(), recovered);
    assert_eq!((test.original.fixture.provider.release_count, test.original.attestor.calls), (0, 0));
    assert_eq!((test.provider.releases, test.provider.shared_releases), (0, 0));
}

#[test]
fn paired_original_estimators_and_qualification_keep_the_frozen_thresholds() {
    let mut test = PairedHarness::new(512, false, false);
    let before = test.original.runner.holdout_anchor();
    let executed = test.run().expect("same original execution and signatures");
    assert_ne!(test.original.runner.holdout_anchor(), before);
    assert_eq!((test.provider.releases, test.provider.shared_releases), (1, 0));
    assert_eq!(test.original.attestor.calls, 1);
    assert!(executed.paired_input_digest.is_some_and(|digest| !digest.is_zero()));
    assert_eq!(executed.candidate.estimate.point.ips, FixedQ32::ONE);
    assert_eq!(executed.baseline.estimate.point.ips, FixedQ32::ZERO);
    assert_eq!(executed.candidate.estimate.point.maximum_observed_weight, FixedQ32::ONE);
    assert_eq!(executed.baseline.estimate.point.maximum_observed_weight, FixedQ32::ONE);
    assert_eq!(executed.candidate.estimate.cluster_count, 512);
    assert_eq!(executed.baseline.estimate.cluster_count, 512);
    assert_eq!(test.original.fixture.candidate_plan.ope.maximum_weight, FixedQ32::from_raw(4_i64 << 32));
    assert_eq!(test.original.fixture.candidate_plan.confidence.family_alpha_ppm, 50_000);
    assert_eq!(executed.product_plan.metric_roles, test.original.fixture.roles);
    assert!(executed.metrics[0].candidate.lower > executed.metrics[0].baseline.upper);
    let qualified = test.qualify(&executed);
    assert_eq!(
        qualified.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
    );
    assert!(!qualified.authority.grants_any());
    assert!(!executed.authority.grants_any());
    let consumed = test.original.runner.holdout_anchor();
    assert_eq!(test.run().expect("original signed completion readback"), executed);
    assert_eq!(test.original.runner.holdout_anchor(), consumed);
    assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 1));
}

#[test]
fn paired_equal_outcomes_do_not_pass_original_primary_superiority() {
    let mut test = PairedHarness::new(512, true, false);
    let executed = test.run().expect("two original equal-outcome arms");
    assert_eq!(executed.candidate.estimate.point.ips, executed.baseline.estimate.point.ips);
    let qualified = test.qualify(&executed);
    assert_eq!(
        qualified.decision.decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible,
    );
    assert!(!qualified.authority.grants_any());
    assert_eq!((test.provider.releases, test.provider.shared_releases), (1, 0));
}

#[test]
fn paired_identity_source_state_and_probability_changes_stay_pending() {
    for change in [
        "model", "run", "checkpoint", "input", "protocol", "copied-outcome",
        "empty-source", "empty-execution", "missing-row", "duplicate-row",
        "split-cluster", "soft-policy", "unsupported-policy", "missing-outcome",
    ] {
        let mut test = PairedHarness::new(2, false, false);
        let inputs = test.provider.inputs.as_mut().expect("unreleased paired fixture");
        match change {
            "model" => inputs.candidate.provenance[0].model_digest = digest("wrong-model"),
            "run" => inputs.candidate.provenance[0].behavior_run_id = id("wrong-run"),
            "checkpoint" => inputs.candidate.provenance[0].checkpoint_before = digest("not-empty"),
            "input" => inputs.candidate.provenance[0].input_digest = digest("wrong-input"),
            "protocol" => inputs.candidate.provenance[0].protocol_digest = digest("wrong-protocol"),
            "copied-outcome" => {
                inputs.baseline.observations[0].outcome_evidence = inputs.candidate.observations[0].outcome_evidence;
            }
            "empty-source" => inputs.candidate.provenance[0].source_evidence_digest = Digest32::ZERO,
            "empty-execution" => inputs.candidate.provenance[0].execution_evidence_digest = Digest32::ZERO,
            "missing-row" => { inputs.candidate.observations.pop(); }
            "duplicate-row" => {
                inputs.candidate.targets[1] = inputs.candidate.targets[0].clone();
            }
            "split-cluster" => inputs.candidate.assignments[0].cluster_id = id("invented-arm-cluster"),
            "soft-policy" => {
                let half = ProbabilityQ32::from_raw(1_u64 << 31).expect("half");
                for action in &mut inputs.candidate.observations[0].actions {
                    action.behavior_probability = half;
                    action.evaluation_probability = half;
                }
            }
            "unsupported-policy" => {
                inputs.candidate.observations[0].actions[1].evaluation_probability =
                    ProbabilityQ32::from_raw(1_u64 << 32).expect("one");
            }
            "missing-outcome" => inputs.candidate.observations[0].finalized_outcome = None,
            _ => unreachable!(),
        }
        let before = test.original.runner.holdout_anchor();
        assert!(matches!(test.run(), Err(Error::Evaluation(_))), "{change}");
        assert_ne!(test.original.runner.holdout_anchor(), before, "{change}");
        assert_eq!((test.provider.releases, test.provider.shared_releases), (1, 0), "{change}");
        assert_eq!(test.original.attestor.calls, 0, "{change}");
        let consumed = test.original.runner.holdout_anchor();
        assert_eq!(test.run(), Err(Error::Pending), "{change}");
        assert_eq!(test.original.runner.holdout_anchor(), consumed, "{change}");
        assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 0), "{change}");
    }
}

#[test]
fn paired_contract_and_temporal_protocol_are_fixed_before_consumption() {
    for change in ["pair", "decision", "episode", "run", "principal", "same-model"] {
        let test = PairedHarness::new(2, false, false);
        let mut pairing = test.pairing.clone();
        match change {
            "pair" => pairing.pairs[1].pair_id = pairing.pairs[0].pair_id.clone(),
            "decision" => pairing.pairs[1].candidate.decision_id = pairing.pairs[0].candidate.decision_id.clone(),
            "episode" => pairing.pairs[1].candidate.episode_lineage = pairing.pairs[0].candidate.episode_lineage.clone(),
            "run" => pairing.pairs[1].candidate.behavior_run_id = pairing.pairs[0].candidate.behavior_run_id.clone(),
            "principal" => pairing.pairs[0].baseline.principal_lineage = id("different-original-principal"),
            "same-model" => pairing.pairs[0].baseline.model_digest = pairing.pairs[0].candidate.model_digest,
            _ => unreachable!(),
        }
        let before = test.original.runner.holdout_anchor();
        assert!(freeze_paired_on_policy_product_evaluation_plan_v1(
            test.original.fixture.cross_fold.clone(),
            test.original.fixture.roles.clone(),
            test.original.fixture.sources.clone(),
            &test.original.fixture.candidate_plan,
            &test.original.fixture.baseline_plan,
            pairing,
        ).is_err(), "{change}");
        assert_eq!(test.original.runner.holdout_anchor(), before);
        assert!(test.original.executions.state.is_none());
    }
    let mut test = PairedHarness::new(2, false, false);
    let mut changed = test.original.fixture.baseline_plan.clone();
    changed.ope.maximum_weight = FixedQ32::ONE;
    changed.plan_digest = changed.canonical_digest().expect("changed complete plan digest");
    assert!(freeze_paired_on_policy_product_evaluation_plan_v1(
        test.original.fixture.cross_fold.clone(),
        test.original.fixture.roles.clone(),
        test.original.fixture.sources.clone(),
        &test.original.fixture.candidate_plan,
        &changed,
        test.pairing.clone(),
    ).is_err());
    test.original.fixture.baseline_plan = changed;
    let before = test.original.runner.holdout_anchor();
    assert!(matches!(test.run(), Err(Error::Evaluation(ProductEvaluationError::Binding(_)))));
    assert_eq!(test.original.runner.holdout_anchor(), before);
    assert!(test.original.executions.state.is_none());
    assert_eq!((test.provider.releases, test.original.attestor.calls), (0, 0));
}

#[test]
fn paired_one_actual_principal_is_not_split_into_independent_clusters() {
    let mut test = PairedHarness::new(4, false, true);
    assert_eq!(
        test.run(),
        Err(Error::Evaluation(ProductEvaluationError::Temporal(
            crate::TemporalEvaluationError::Confidence(
                crate::ClusterConfidenceError::InsufficientClusters,
            ),
        ))),
    );
    assert_eq!(test.run(), Err(Error::Pending));
    assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 0));
}

#[test]
fn paired_signed_completion_lost_ack_cold_reads_without_release_or_resign() {
    let mut test = PairedHarness::new(2, false, false);
    test.original.executions.lost = LostAck::Complete;
    assert_eq!(test.run(), Err(Error::Store(StoreError::Indeterminate)));
    let mut original = test.original.attestor.original.clone().expect("original signed paired execution");
    original.execution_evaluator = Some(test.original.context.evaluator.clone());
    let encoded = execution_codec::encode_execution(&original).expect("new bounded paired body");
    assert_eq!(&encoded[..8], b"HPEXRP01");
    let mut tail = Vec::new();
    for digest in [
        original.estimate_receipt_digest, original.support_audit_digest,
        original.confidence_receipt_digest, original.execution_digest, original.receipt_seal,
    ] {
        tail.extend_from_slice(digest.as_array());
    }
    assert_eq!(&encoded[encoded.len() - 160..], tail.as_slice());
    for size in [0, 7, 39, 71, encoded.len() - 1] {
        assert!(execution_codec::decode_execution(&encoded[..size], &test.original.frozen, &original.holdout).is_err());
    }
    let mut changed = encoded.clone();
    changed[40] ^= 1;
    assert!(execution_codec::decode_execution(&changed, &test.original.frozen, &original.holdout).is_err());
    let mut trailing = encoded;
    trailing.push(0);
    assert!(execution_codec::decode_execution(&trailing, &test.original.frozen, &original.holdout).is_err());
    test.original.reopen();
    let current = test.original.runner.holdout_anchor();
    assert_eq!(test.original.readback().expect("original cold paired readback"), original);
    assert_eq!(test.original.readback().expect("second independent readback"), original);
    assert_eq!(test.original.runner.holdout_anchor(), current);
    assert_eq!((test.provider.releases, test.provider.shared_releases), (1, 0));
    assert_eq!(test.original.attestor.calls, 1);
    test.original.now = 91;
    assert!(matches!(test.original.readback(), Err(Error::Evaluation(ProductEvaluationError::Signed(_)))));
    assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 1));
}

#[test]
fn paired_changed_execution_body_cannot_replace_original_signature() {
    let mut test = PairedHarness::new(2, false, false);
    test.run().expect("original paired completion");
    let (key, State::Completed(bytes)) = test.original.executions.state.as_mut().expect("completed")
    else { panic!("expected original completion") };
    let (mut signed, body) = execution_codec::decode_envelope(bytes).expect("original envelope");
    let mut changed = body.to_vec();
    changed[40] ^= 1;
    let mut payload = b"hepta.intelligence-eval.signed-execution.v1".to_vec();
    super::super::super::push_id(&mut payload, &key.plan_id);
    payload.extend_from_slice(key.binding_digest.as_array());
    payload.extend_from_slice(Digest32::of_bytes(&changed).as_array());
    signed.payload_digest = Digest32::of_bytes(&payload);
    *bytes = execution_codec::encode_envelope(&signed, &changed).expect("same declared signer without its signature");
    assert!(matches!(test.original.readback(), Err(Error::Evaluation(ProductEvaluationError::Signed(_)))));
    assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 1));
}

#[test]
fn paired_mode_cannot_decode_or_reuse_a_shared_behavior_execution() {
    let mut shared = Harness::new();
    let original = shared.run().expect("original legacy execution");
    let encoded = execution_codec::encode_execution(&original).expect("original legacy body");
    assert_eq!(&encoded[..8], b"HPEXR001");
    assert_eq!(shared.frozen.comparison_mode(), &ProductComparisonModeV1::SharedBehavior);
    assert!(super::super::super::product_plan_commitment_bytes(&shared.frozen)
        .expect("original shared plan").starts_with(b"hepta.intelligence-eval.product-frozen-plan.v1"));
    assert_eq!(
        super::super::super::plan_estimand_commitment_bytes(&shared.frozen).expect("shared wrapper"),
        super::super::super::product_estimand_commitment_bytes(
            shared.frozen.base_estimand_digest,
            shared.frozen.candidate_temporal_plan_digest,
            shared.frozen.baseline_temporal_plan_digest,
            &shared.frozen.metric_sources,
        ).expect("unaltered original estimand"),
    );
    let mut wrong = original.clone();
    wrong.paired_input_digest = Some(digest("not-a-paired-execution"));
    assert!(wrong.validate_integrity().is_err());
    let mut paired = PairedHarness::new(2, false, false);
    assert!(execution_codec::decode_execution(&encoded, &paired.original.frozen, &original.holdout).is_err());
    let paired_receipt = paired.run().expect("independent paired owner");
    let paired_bytes = execution_codec::encode_execution(&paired_receipt).expect("paired bytes");
    assert!(execution_codec::decode_execution(&paired_bytes, &shared.frozen, &original.holdout).is_err());
    shared.frozen = paired.original.frozen.clone();
    let before = shared.runner.holdout_anchor();
    assert!(shared.run().is_err());
    assert_eq!(shared.runner.holdout_anchor(), before);
    assert_eq!((shared.fixture.provider.release_count, shared.attestor.calls), (1, 1));
}

#[test]
fn paired_best_case_at_the_producer_pair_upper_bound_keeps_current_metrics_ineligible() {
    // Thirty-one is the optimistic upper bound with any nonempty history in
    // the actual producer's existing 64-episode cap. This pure-domain fixture
    // deliberately grants every pair a distinct cluster and extreme outcomes;
    // it is not an execution of that producer or permission to enlarge its cap.
    for source in [
        ProductMetricSourceV1::Ips,
        ProductMetricSourceV1::Snips,
        ProductMetricSourceV1::DoublyRobust,
    ] {
        let mut test = PairedHarness::new(31, false, false);
        test.original.fixture.sources[0].source = source;
        test.original.frozen = freeze_paired_on_policy_product_evaluation_plan_v1(
            test.original.fixture.cross_fold.clone(),
            test.original.fixture.roles.clone(),
            test.original.fixture.sources.clone(),
            &test.original.fixture.candidate_plan,
            &test.original.fixture.baseline_plan,
            test.pairing.clone(),
        ).expect("same numeric parameters frozen before release");
        let executed = test.run().expect("optimistic original estimator evidence");
        assert_eq!(executed.candidate.estimate.point.ips, FixedQ32::ONE);
        assert_eq!(executed.baseline.estimate.point.ips, FixedQ32::ZERO);
        assert_eq!(executed.candidate.estimate.cluster_count, 31);
        assert!(executed.metrics[0].candidate.lower <= executed.metrics[0].baseline.upper);
        assert_eq!(
            test.qualify(&executed).decision.decision.disposition,
            IndependentEvaluationDispositionV1::Ineligible,
        );
        assert_eq!((test.provider.releases, test.original.attestor.calls), (1, 1));
    }
}
