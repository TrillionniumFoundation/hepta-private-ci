//! Synthetic native boundary tests; no installed role or scientific evidence.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use pretty_assertions::assert_eq;

fn source(count: usize) -> PairedReviewSourcePlanV1 {
    let inputs = inputs(count);
    PairedReviewSourcePlanV1 {
        base_plan: inputs.base_plan,
        source_scope: TaskSourceScopeV1 {
            objective_digest: digest("paired-objective"),
            task_definition_digest: digest("paired-task-contract"),
            source_archive_digest: digest("synthetic-source-archive"),
        },
        source_records: (0..count + 2)
            .map(|index| TaskSourceRecordV1 {
                source_file_digest: digest("synthetic-source-file"),
                source_row_index: index as u64 + 1,
                source_record_digest: digest(&format!("row-{index}")),
                task_id: id(&format!("task-{index}")),
                dependency_ids: vec![id(&format!("doc-{index}"))],
            })
            .collect(),
        folds: inputs.folds,
        unscored_source_records: inputs.unscored_source_records,
        tasks: inputs.tasks,
        runtime: inputs.runtime,
        policy: inputs.policy,
        metrics: inputs.metrics,
    }
}
// This test exercises signed native recomputation, not the normal E policy
// loader. Its actual activated fixture trust is supplied to recompute directly.
fn unused_wire_trust() -> ReviewTrustWireV1 {
    serde_json::from_value(serde_json::json!({
        "root_id":"fixture-root","root_verifying_key_hex":"00".repeat(32),
        "root_valid_from":1,"root_expires_at":1000,"distribution_id":"fixture-distribution",
        "generation":1,"effective_at":1,"issued_at":1,"expires_at":800,
        "scope_digest":digest("paired-objective-scope").to_string(),
        "objective_digest":digest("paired-objective").to_string(),"authority_epoch":1,
        "signers":[],"signature_hex":"00".repeat(64),
    }))
    .unwrap()
}
fn fixture() -> (
    PairedReviewSourcePlanV1,
    SigningFixture,
    ProductPairedEvaluationReceiptV1,
    Vec<u8>,
) {
    let source = source(6);
    let plan = source.freeze().unwrap();
    assert_eq!(plan, freeze_paired_supervised_plan_v1(inputs(6)).unwrap());
    let signing = SigningFixture::new(false);
    let registered = signing.register(&plan);
    let execution = runner()
        .evaluate_paired_with_clock(
            &registered,
            &mut signing.provider(&plan),
            &signing.trust,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let bytes =
        encode_paired_review_publication_v1(&source, &execution, &unused_wire_trust()).unwrap();
    (source, signing, execution, bytes)
}

#[test]
fn independent_recomputation_preserves_original_plan_execution_and_review_preimage() {
    let (source, signing, original, bytes) = fixture();
    assert_eq!(
        PairedReviewSourcePlanV1::decode(&source.encode().unwrap()).unwrap(),
        source
    );
    let recomputed = Publication::read(&bytes)
        .unwrap()
        .recompute(&signing.trust, 30)
        .unwrap();
    assert_eq!(recomputed, original);
    assert_eq!(
        paired_evaluation_signing_payload_v1(&recomputed, &signing.context()).unwrap(),
        paired_evaluation_signing_payload_v1(&original, &signing.context()).unwrap()
    );
    // The original custody owner accepts the independently signed recomputation
    // only for this exact original execution and the original sink.
    let evidence = signing.evaluation(&recomputed, &signing.context());
    let mut sink = crate::paired_supervised_test_support::Sink::default();
    let qualified = runner()
        .qualify_paired_with_clock(
            &original,
            &signing.context(),
            &evidence,
            &signing.trust,
            &mut sink,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    assert_eq!(sink.calls, 1);
    assert!(!qualified.authority.grants_any());
}

#[test]
fn source_graph_and_frozen_gates_cannot_be_replaced_under_original_signatures() {
    let (source, signing, original, bytes) = fixture();
    let mut graph = source.clone();
    graph.source_records[2]
        .dependency_ids
        .push(id("new-shared-document"));
    assert!(encode_paired_review_publication_v1(&graph, &original, &unused_wire_trust()).is_err());
    let mut wire: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    wire["plan_inputs_hex"] = hex(&graph.encode().unwrap()).into();
    assert!(
        Publication::read(&serde_json::to_vec(&wire).unwrap())
            .unwrap()
            .recompute(&signing.trust, 30)
            .is_err()
    );
    let mut gates = source;
    gates.policy.maximum_abstain_ppm = 1_000_000;
    wire["plan_inputs_hex"] = hex(&gates.encode().unwrap()).into();
    assert!(
        Publication::read(&serde_json::to_vec(&wire).unwrap())
            .unwrap()
            .recompute(&signing.trust, 30)
            .is_err()
    );
}

#[test]
fn original_observer_measurements_and_consumption_receipt_are_not_caller_metrics() {
    let (_, signing, original, bytes) = fixture();
    let mut cut = original.observations.clone();
    cut.cut.rows[0].candidate.original_elapsed_micros = Some(0);
    // Even updating the claimed payload digest cannot replace the O signature.
    cut.observer_evidence.payload_digest =
        Digest32::of_bytes(&paired_observation_cut_signing_payload_v1(&cut.cut).unwrap());
    let mut wire: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    wire["observations_hex"] =
        hex(&encode_signed_paired_observation_transport_v1(&cut).unwrap()).into();
    assert!(
        Publication::read(&serde_json::to_vec(&wire).unwrap())
            .unwrap()
            .recompute(&signing.trust, 30)
            .is_err()
    );
    let mut wire: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    let mut receipt = original.holdout;
    receipt.record_digest = digest("different-original-CAS-record");
    receipt.head_digest = receipt.record_digest;
    wire["holdout_receipt_hex"] = hex(&encode(&receipt).unwrap()).into();
    assert!(
        Publication::read(&serde_json::to_vec(&wire).unwrap())
            .unwrap()
            .recompute(&signing.trust, 30)
            .is_err()
    );
}

#[test]
fn malformed_input_transport_and_expired_original_roles_are_rejected() {
    let (source, signing, _, bytes) = fixture();
    let encoded = source.encode().unwrap();
    for length in 0..encoded.len() {
        assert!(PairedReviewSourcePlanV1::decode(&encoded[..length]).is_err());
    }
    let mut trailing = encoded;
    trailing.push(0);
    assert!(PairedReviewSourcePlanV1::decode(&trailing).is_err());
    let mut unknown: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    unknown["caller_qualified"] = true.into();
    assert!(Publication::read(&serde_json::to_vec(&unknown).unwrap()).is_err());
    let text = std::str::from_utf8(&bytes)
        .unwrap()
        .replacen("{", "{\"schema\":\"duplicate\",", 1);
    assert!(Publication::read(text.as_bytes()).is_err());
    assert!(
        Publication::read(&bytes)
            .unwrap()
            .recompute(&signing.trust, 900)
            .is_err()
    );
}

#[test]
fn root_material_encoder_matches_original_native_plan_without_inventing_a_receipt() {
    use crate::paired_supervised_test_support::digest as fixture_digest;
    use crate::paired_supervised_test_support::id as fixture_id;
    use crate::paired_supervised_test_support::inputs;
    use crate::*;
    use std::path::Path;
    let input = inputs(6);
    let records: Vec<_> = (0..8)
        .map(|index| TaskSourceRecordV1 {
            source_file_digest: fixture_digest("synthetic-source-file"),
            source_row_index: index + 1,
            source_record_digest: fixture_digest(&format!("row-{index}")),
            task_id: fixture_id(&format!("task-{index}")),
            dependency_ids: vec![fixture_id(&format!("doc-{index}"))],
        })
        .collect();
    let source = PairedReviewSourcePlanV1 {
        base_plan: input.base_plan,
        source_scope: TaskSourceScopeV1 {
            objective_digest: fixture_digest("paired-objective"),
            task_definition_digest: fixture_digest("paired-task-contract"),
            source_archive_digest: fixture_digest("synthetic-source-archive"),
        },
        source_records: records,
        folds: input.folds,
        unscored_source_records: input.unscored_source_records,
        tasks: input.tasks,
        runtime: input.runtime,
        policy: input.policy,
        metrics: input.metrics,
    };
    let contract = |c: &MetricContractV1| {
        serde_json::json!({"metric_id":c.metric_id.to_string(),
        "direction":match c.direction {EvaluationDirectionV1::Maximize=>"Maximize",EvaluationDirectionV1::Minimize=>"Minimize"},
        "safety_floor":c.safety_floor.map(codex_hepta_types::FixedQ32::raw)})
    };
    let ids =
        |v: &[codex_hepta_types::StableId]| v.iter().map(ToString::to_string).collect::<Vec<_>>();
    let digests = |v: &[Digest32]| v.iter().map(ToString::to_string).collect::<Vec<_>>();
    let base = &source.base_plan;
    let scope = &source.source_scope;
    let runtime = &source.runtime;
    let policy = &source.policy;
    let value = serde_json::json!({"schema":"hepta.eval.paired-supervised.declarative-inputs.v1","inputs":{
        "base_plan":{"plan_id":base.plan_id.to_string(),"claim_scope":"Qualification","candidate_id":base.candidate_id.to_string(),
            "baseline_id":base.baseline_id.to_string(),"objective_digest":base.objective_digest.to_string(),"dataset_digest":base.dataset_digest.to_string(),
            "estimand_digest":base.estimand_digest.to_string(),"metric_contracts":base.metric_contracts.iter().map(contract).collect::<Vec<_>>(),
            "family_alpha_ppm":base.family_alpha_ppm,"simultaneous_comparisons":base.simultaneous_comparisons,"folds":[],
            "final_holdout_window_id":base.final_holdout_window_id.to_string(),"final_holdout_digest":base.final_holdout_digest.to_string()},
        "source_scope":{"objective_digest":scope.objective_digest.to_string(),"task_definition_digest":scope.task_definition_digest.to_string(),"source_archive_digest":scope.source_archive_digest.to_string()},
        "source_records":source.source_records.iter().map(|r|serde_json::json!({"source_file_digest":r.source_file_digest.to_string(),"source_row_index":r.source_row_index,
            "source_record_digest":r.source_record_digest.to_string(),"task_id":r.task_id.to_string(),"dependency_ids":ids(&r.dependency_ids)})).collect::<Vec<_>>(),
        "folds":source.folds.iter().map(|f|serde_json::json!({"fold_id":f.fold_id.to_string(),"training_records":digests(&f.training_records),"holdout_records":digests(&f.holdout_records),
            "training_windows":ids(&f.training_windows),"holdout_windows":ids(&f.holdout_windows),"model_digest":f.model_digest.to_string(),"predictions_digest":f.predictions_digest.to_string()})).collect::<Vec<_>>(),
        "unscored_source_records":digests(&source.unscored_source_records),
        "tasks":source.tasks.iter().map(|t|serde_json::json!({"source_record_digest":t.source_record_digest.to_string(),"candidate_request_id":t.candidate_request_id.to_string(),
            "baseline_request_id":t.baseline_request_id.to_string(),"candidate_input_digest":t.candidate_input_digest.to_string(),"baseline_input_digest":t.baseline_input_digest.to_string()})).collect::<Vec<_>>(),
        "runtime":{"candidate_artifact_digest":runtime.candidate_artifact_digest.to_string(),"deployed_baseline_digest":runtime.deployed_baseline_digest.to_string(),
            "candidate_runtime_digest":runtime.candidate_runtime_digest.to_string(),"baseline_runtime_digest":runtime.baseline_runtime_digest.to_string(),"task_input_contract_digest":runtime.task_input_contract_digest.to_string()},
        "policy":{"required_evidence_metrics":{"execution_cost":policy.required_evidence_metrics.execution_cost.to_string(),"retention":policy.required_evidence_metrics.retention.to_string(),"unlearning":policy.required_evidence_metrics.unlearning.to_string()},
            "output_alphabet":ids(&policy.output_alphabet),"assumptions_digest":policy.assumptions_digest.to_string(),"minimum_independent_clusters":policy.minimum_independent_clusters,
            "maximum_abstain_ppm":policy.maximum_abstain_ppm,"maximum_execution_window_micros":policy.maximum_execution_window_micros},
        "metrics":source.metrics.iter().map(|m|serde_json::json!({"contract":contract(&m.contract),"role":match m.role {
            MetricRoleV2::PrimarySuperiority{minimum_improvement}=>serde_json::json!({"PrimarySuperiority":{"minimum_improvement":minimum_improvement.raw()}}),
            MetricRoleV2::NonInferiority{maximum_regression}=>serde_json::json!({"NonInferiority":{"maximum_regression":maximum_regression.raw()}}),
            MetricRoleV2::AbsoluteConstraint=>serde_json::json!({"AbsoluteConstraint":{}})},"kind":match m.kind {
                PairedMetricKindV1::ClassificationAccuracy=>serde_json::json!({"ClassificationAccuracy":{}}),
                PairedMetricKindV1::ExecutionLatencyMillis{maximum}=>serde_json::json!({"ExecutionLatencyMillis":{"maximum":maximum.raw()}}),
                PairedMetricKindV1::ObservedBounded{minimum,maximum}=>serde_json::json!({"ObservedBounded":{"minimum":minimum.raw(),"maximum":maximum.raw()}})}})).collect::<Vec<_>>()
    }});
    let file = crate::NamedTempFile::new().unwrap();
    std::fs::write(file.path(), serde_json::to_vec(&value).unwrap()).unwrap();
    let helper = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tools/hepta_encode_paired_plan_inputs.py");
    let run = || {
        std::process::Command::new("python3")
            .args(["-I", "-B", "-S"])
            .arg(&helper)
            .arg(file.path())
            .output()
            .unwrap()
    };
    let out = run();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let bytes = codex_hepta_learning_ledger::decode_review_payload_hex(
        std::str::from_utf8(&out.stdout).unwrap().trim(),
    )
    .unwrap();
    let decoded = PairedReviewSourcePlanV1::decode(&bytes).unwrap();
    assert_eq!(decoded, source);
    assert_eq!(decoded.freeze().unwrap(), source.freeze().unwrap());
    let mut unknown = value;
    unknown["inputs"]["policy"]["unregistered_gate"] = serde_json::json!(0);
    std::fs::write(file.path(), serde_json::to_vec(&unknown).unwrap()).unwrap();
    assert!(!run().status.success());
}
