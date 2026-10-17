use std::fmt::Debug;
use std::sync::Arc;

use super::*;
use codex_hepta_types::AuthorityPosture;

use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;
use crate::canonical_cell_head_digest_v1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(raw: &str) -> StableId {
    match StableId::new(raw) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture id: {error:?}"),
    }
}

fn digest(raw: &str) -> Digest32 {
    Digest32::of_bytes(raw.as_bytes())
}

fn head() -> CellHeadV1 {
    let cell_id = id("cell:evidence");
    let weights = vec![0; 3 * 2];
    let bias = vec![0; 3];
    let head_digest = canonical_cell_head_digest_v1(
        &cell_id,
        Generation::new(3).unwrap_or_else(|error| panic!("{error:?}")),
        digest("encoder"),
        2,
        1,
        &weights,
        &bias,
        1,
    );
    must(CellHeadV1::new(
        cell_id,
        Generation::new(3).unwrap_or_else(|error| panic!("{error:?}")),
        digest("encoder"),
        head_digest,
        2,
        1,
        weights,
        bias,
        1,
    ))
}

fn output(head: &CellHeadV1) -> CellHeadOutputV1 {
    CellHeadOutputV1 {
        cell_id: head.cell_id().clone(),
        head_digest: head.head_digest(),
        action_digest: digest("action"),
        action_logits_q24: Arc::from(vec![1].into_boxed_slice()),
        value_q24: 2,
        uncertainty_q24: 3,
        abstain: false,
    }
}

fn runtime_output() -> NeuronRuntimeOutputV1 {
    let resource_receipt = NeuronResourceReceiptV1 {
        execution_micros: 10,
        transient_allocation_bytes: 20,
        checkpoint_bytes: 30,
        journal_bytes_written: 40,
        write_amplification_ppm: 1_000_000,
        saturation_count: 1,
        queue_age_micros: 2,
    };
    NeuronRuntimeOutputV1 {
        tick: NeuronTickReceiptV1 {
            tick_id: id("tick:evidence"),
            checkpoint_before: digest("before"),
            checkpoint_after: digest("after"),
            activation_digest: digest("activation"),
            active_indices: vec![0],
            sparsity_ppm: 500_000,
            threshold_digest: digest("threshold"),
            eligibility_digest: digest("eligibility"),
            prediction_error_q24: 2,
            confidence_ppm: 900_000,
            ood_ppm: 100_000,
            abstain: true,
            resource_receipt,
        },
        signal: NeuronSignalReceiptV1 {
            signal_set_id: id("signal:evidence"),
            model_runtime_digest: digest("model-binding"),
            temporal_state_digest: digest("temporal"),
            signals_q24: vec![1, 2],
            activation_sparsity_ppm: 500_000,
            ood_ppm: 100_000,
            abstain: false,
            authority: AuthorityPosture::DENY_ALL,
        },
        model_runtime: LocalModelRuntimeReceiptV1 {
            model_id: id("model:evidence"),
            model_manifest_digest: digest("manifest"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("quant:q24"),
            quantization_digest: digest("quantization"),
            backend_id: id("backend:test"),
            runtime_digest: digest("runtime"),
            device_identity_digest: digest("device"),
            latency_micros: 10,
            resident_bytes: 20,
        },
    }
}

#[test]
fn binds_head_and_runtime_receipts_into_replayable_evidence() {
    let head = head();
    let runtime = runtime_output();
    let evidence = must(bind_cell_evidence_v1(&head, &output(&head), &runtime));

    assert_eq!(evidence.cell_id, id("cell:evidence"));
    assert_eq!(evidence.encoder_digest, digest("encoder"));
    assert_eq!(evidence.confidence_ppm, 900_000);
    assert_eq!(evidence.ood_ppm, 100_000);
    assert!(evidence.abstain);
    assert_eq!(
        evidence.evidence_digest,
        canonical_cell_evidence_digest_v1(&evidence, &runtime)
    );
    assert_ne!(evidence.runtime_receipt_digest, Digest32::ZERO);
}

#[test]
fn evidence_fences_authority_calibration_and_receipt_integrity() {
    let head = head();
    let mut runtime = runtime_output();
    runtime.signal.model_runtime_digest = Digest32::ZERO;
    assert_eq!(
        bind_cell_evidence_v1(&head, &output(&head), &runtime),
        Err(CellEvidenceError::EmptyDigest("model runtime binding"))
    );

    let mut runtime = runtime_output();
    runtime.tick.ood_ppm = 1_000_001;
    assert_eq!(
        bind_cell_evidence_v1(&head, &output(&head), &runtime),
        Err(CellEvidenceError::InvalidPpm)
    );

    let mut runtime = runtime_output();
    runtime.model_runtime.model_manifest_digest = Digest32::ZERO;
    assert_eq!(
        bind_cell_evidence_v1(&head, &output(&head), &runtime),
        Err(CellEvidenceError::RuntimeReceiptInvalid)
    );
}

#[test]
fn evidence_fences_cell_and_head_binding() {
    let head = head();
    let runtime = runtime_output();
    let mut wrong_cell_output = output(&head);
    wrong_cell_output.cell_id = id("cell:other");
    assert_eq!(
        bind_cell_evidence_v1(&head, &wrong_cell_output, &runtime),
        Err(CellEvidenceError::CellBindingMismatch)
    );

    let mut wrong_head_output = output(&head);
    wrong_head_output.head_digest = digest("other-head");
    assert_eq!(
        bind_cell_evidence_v1(&head, &wrong_head_output, &runtime),
        Err(CellEvidenceError::HeadBindingMismatch)
    );
}
