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
