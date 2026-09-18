use super::*;

use codex_hepta_neuron::CalibratedSignalV1;
use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronResourceReceiptV1;
use codex_hepta_neuron::NeuronSignalReceiptV1;
use codex_hepta_neuron::NeuronTickReceiptV1;
use codex_hepta_neuron::SparseSignalReceipt;
use codex_hepta_types::AuthorityPosture;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn result(abstain: bool) -> RuntimeTickResultV1 {
    let tick_id = id("tick.1");
    let checkpoint = digest("checkpoint");
    RuntimeTickResultV1 {
        tick_receipt: NeuronTickReceiptV1 {
            tick_id: tick_id.clone(),
            checkpoint_before: Digest32::ZERO,
            checkpoint_after: checkpoint,
            activation_digest: digest("activation"),
            active_indices: vec![0],
            sparsity_ppm: 200_000,
            threshold_digest: digest("threshold"),
            eligibility_digest: digest("eligibility"),
            prediction_error_q24: 1,
            confidence_ppm: if abstain { 0 } else { 900_000 },
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
            resource_receipt: NeuronResourceReceiptV1 {
                execution_micros: 10,
                transient_allocation_bytes: 128,
                checkpoint_bytes: 512,
                saturation_count: 0,
                queue_age_micros: 0,
            },
        },
        signal_receipt: NeuronSignalReceiptV1 {
            signal_set_id: tick_id,
            model_runtime_digest: digest("model-runtime"),
            temporal_state_digest: checkpoint,
            signals_q24: vec![1],
            activation_sparsity_ppm: 200_000,
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
        },
        sparse_receipt: SparseSignalReceipt {
            config_digest: digest("config"),
            input_digest: digest("input"),
            checkpoint_before: Digest32::ZERO,
            checkpoint_after: checkpoint,
            activation_q24: vec![1],
            active_fraction_ppm: 200_000,
            prediction_error_q24: 1,
            projection_count: 0,
            requires_calibration: false,
            authority: AuthorityPosture::DENY_ALL,
        },
        model_runtime_receipt: LocalModelRuntimeReceiptV1 {
            model_id: id("model.1"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q4"),
            backend_id: id("backend.1"),
            device_identity_digest: digest("device"),
            latency_micros: 10,
            resident_bytes: 1024,
        },
        calibration: CalibratedSignalV1 {
            confidence_ppm: if abstain { 0 } else { 900_000 },
            ood_ppm: if abstain { 1_000_000 } else { 10_000 },
            abstain,
            calibration_artifact_digest: Some(digest("calibration")),
            fallback_reason: None,
        },
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[test]
fn calibrated_neuron_signal_remains_advisory_and_authority_free() {
    let receipt = convert_runtime_result(id("tick.1"), result(false)).expect("consumer receipt");
    assert_eq!(
        receipt.disposition,
        NeuronConsumerDispositionV1::AdvisorySignal
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.receipt_digest.is_zero());
}

#[test]
fn neuron_abstention_forces_intelligence_slow_path() {
    let receipt = convert_runtime_result(id("tick.1"), result(true)).expect("consumer receipt");
    assert_eq!(receipt.disposition, NeuronConsumerDispositionV1::SlowPath);
}

#[test]
fn mismatched_tick_or_authority_is_never_normalized_into_success() {
    assert_eq!(
        convert_runtime_result(id("different"), result(false)),
        Err(NeuronConsumerErrorV1::ReceiptMismatch)
    );

    let mut value = result(false);
    value.authority = AuthorityPosture {
        runtime: true,
        ..AuthorityPosture::DENY_ALL
    };
    assert_eq!(
        convert_runtime_result(id("tick.1"), value),
        Err(NeuronConsumerErrorV1::AuthorityViolation)
    );
}
