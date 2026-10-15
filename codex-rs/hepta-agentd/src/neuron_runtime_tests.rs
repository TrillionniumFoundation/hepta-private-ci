use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::WitnessStoreError;

use super::AgentdNeuronOwner;

struct StubWitness;

impl AnchorWitnessStore for StubWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Ok(())
    }
}

struct StubInferenceControl;

impl NeuronInferenceControlPort for StubInferenceControl {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn agentd_neuron_owner_is_a_compiled_product_surface() {
    let name = std::any::type_name::<AgentdNeuronOwner<StubWitness, StubInferenceControl>>();
    assert!(name.contains("AgentdNeuronOwner"));
}

#[test]
fn ndu_final_use_binding_fences_snapshot_read_and_owner() {
    use codex_hepta_neuron::NeuronTickInputV1;
    use codex_hepta_neuron::canonical_feature_vector_digest_v1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::NduSnapshotRefV1;
    use codex_hepta_types::StableId;
    let digest = |label: &[u8]| Digest32::of_bytes(label);
    let subject = StableId::new("subject").unwrap();
    let tick = NeuronTickInputV1 {
        tick_id: StableId::new("tick").unwrap(),
        subject_id: subject.clone(),
        logical_sequence: 1,
        monotonic_time_micros: 1,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&[1 << 24]),
        feature_vector_q24: vec![1 << 24],
        objective_digest: digest(b"objective"),
        ndu_snapshot_digest: digest(b"ndu"),
        body_generation: None,
        modulator_digest: None,
    };
    let snapshot = NduSnapshotRefV1 {
        scope_id: subject,
        owner_id: StableId::new("ndu-owner").unwrap(),
        generation: Generation::new(3).unwrap(),
        route_fence: 9,
        revocation_epoch: 7,
        policy_digest: digest(b"policy"),
        snapshot_digest: tick.ndu_snapshot_digest,
        projection_head_digest: digest(b"head"),
    };
    let read_receipt = digest(b"independently-verified-read");
    let owner = StableId::new("neuron-owner").unwrap();
    let baseline =
        super::neuron_ndu_final_use_binding_v1(&owner, &tick, &snapshot, read_receipt).unwrap();
    let different_fence = NduSnapshotRefV1 {
        route_fence: 10,
        ..snapshot.clone()
    };
    assert_ne!(
        baseline,
        super::neuron_ndu_final_use_binding_v1(&owner, &tick, &different_fence, read_receipt)
            .unwrap()
    );
    assert_ne!(
        baseline,
        super::neuron_ndu_final_use_binding_v1(&owner, &tick, &snapshot, digest(b"other-read"))
            .unwrap()
    );
    assert!(
        super::neuron_ndu_final_use_binding_v1(&owner, &tick, &snapshot, Digest32::ZERO).is_err()
    );
    let wrong_scope = NduSnapshotRefV1 {
        scope_id: StableId::new("wrong").unwrap(),
        ..snapshot
    };
    assert!(
        super::neuron_ndu_final_use_binding_v1(&owner, &tick, &wrong_scope, read_receipt).is_err()
    );
}

#[derive(Debug, Default)]
struct RecordingPhaseSink {
    events: std::sync::Mutex<Vec<codex_hepta_types::PhaseMetricEventV1>>,
    fail: std::sync::atomic::AtomicBool,
}

impl codex_hepta_types::PhaseMetricSinkV1 for RecordingPhaseSink {
    fn record(
        &self,
        event: codex_hepta_types::PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        if self.fail.load(std::sync::atomic::Ordering::Acquire) {
            return Err(codex_hepta_types::PhaseMetricSinkErrorV1::Backpressure);
        }
        self.events
            .lock()
            .expect("recording phase sink")
            .push(event);
        Ok(())
    }

    fn healthy(&self) -> bool {
        !self.fail.load(std::sync::atomic::Ordering::Acquire)
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        if self.healthy() {
            Ok(())
        } else {
            Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
        }
    }
}

#[test]
fn observed_neuron_feature_is_real_and_metric_loss_is_sticky() {
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::time::Duration;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::PhaseMetricEventV1;
    use codex_hepta_types::PhaseMetricKindV1;

    let sink = RecordingPhaseSink::default();
    let failure_count = AtomicU64::new(0);
    let scope = Digest32::of_bytes(b"scope");
    let operation = Digest32::of_bytes(b"signed-neuron-tick");
    super::observe_phase_v1(
        Some(&sink),
        &failure_count,
        scope,
        operation,
        PhaseMetricKindV1::NeuronFeature,
        Duration::from_micros(42),
        true,
    );
    assert_eq!(
        sink.events.lock().expect("retained metrics").as_slice(),
        &[PhaseMetricEventV1 {
            scope_digest: scope,
            operation_digest: operation,
            phase: PhaseMetricKindV1::NeuronFeature,
            latency_micros: 42,
            succeeded: true,
        }],
    );
    assert_eq!(failure_count.load(Ordering::Acquire), 0);
    sink.fail.store(true, Ordering::Release);
    super::observe_phase_v1(
        Some(&sink),
        &failure_count,
        scope,
        operation,
        PhaseMetricKindV1::NeuronFeature,
        Duration::from_micros(43),
        false,
    );
    assert_eq!(failure_count.load(Ordering::Acquire), 1);
    sink.fail.store(false, Ordering::Release);
    assert!(codex_hepta_types::PhaseMetricSinkV1::healthy(&sink));
    assert_eq!(
        failure_count.load(Ordering::Acquire),
        1,
        "recovery of telemetry health may not erase an already lost sample"
    );
    super::observe_phase_v1(
        None,
        &failure_count,
        scope,
        operation,
        PhaseMetricKindV1::NeuronFeature,
        Duration::from_micros(10),
        false,
    );
    assert_eq!(failure_count.load(Ordering::Acquire), 1);
}

#[test]
fn agentd_metrics_require_original_provenance_and_actual_flush_ack() {
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::AtomicU64;

    let sink = RecordingPhaseSink::default();
    let failures = AtomicU64::new(0);
    let flushed = AtomicBool::new(false);
    assert!(!super::metrics_ready_v1(
        Some(&sink),
        &failures,
        &flushed,
        false
    ));
    assert!(!super::flush_metrics_v1(
        Some(&sink),
        &failures,
        &flushed,
        false
    ));
    assert!(matches!(
        super::begin_signed_tick_v1(Some(&sink), &failures, &flushed, false),
        Err(codex_hepta_neuron::NeuronRuntimeError::PendingReconciliation)
    ));

    // Boolean below exercises only the private protocol helper: product code
    // cannot synthesize the typed DurablePhaseMetricSinkV1 this way.
    assert!(super::flush_metrics_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
    super::begin_signed_tick_v1(Some(&sink), &failures, &flushed, true).unwrap();
    assert!(!super::metrics_ready_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
    assert!(super::observe_and_commit_neuron_phase_v1(
        Some(&sink),
        &failures,
        &flushed,
        true,
        codex_hepta_types::Digest32::of_bytes(b"scope"),
        codex_hepta_types::Digest32::of_bytes(b"tick"),
        std::time::Duration::from_micros(11),
        true,
    ));
    assert!(super::metrics_ready_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
    assert_eq!(sink.events.lock().expect("sample").len(), 1);
}

#[test]
fn agentd_post_effect_observation_failure_is_sticky_even_after_writer_recovers() {
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    let sink = RecordingPhaseSink::default();
    let failures = AtomicU64::new(0);
    let flushed = AtomicBool::new(false);
    assert!(super::flush_metrics_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
    super::begin_signed_tick_v1(Some(&sink), &failures, &flushed, true).unwrap();
    sink.fail.store(true, Ordering::Release);
    assert!(!super::observe_and_commit_neuron_phase_v1(
        Some(&sink),
        &failures,
        &flushed,
        true,
        codex_hepta_types::Digest32::of_bytes(b"scope"),
        codex_hepta_types::Digest32::of_bytes(b"committed-operation"),
        std::time::Duration::from_micros(20),
        true,
    ));
    assert_eq!(failures.load(Ordering::Acquire), 1);
    sink.fail.store(false, Ordering::Release);
    assert!(!super::flush_metrics_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
    assert!(!super::metrics_ready_v1(
        Some(&sink),
        &failures,
        &flushed,
        true
    ));
}

#[test]
fn agentd_missing_sink_cannot_arm_signed_effect() {
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::AtomicU64;

    let failures = AtomicU64::new(0);
    let flushed = AtomicBool::new(false);
    assert!(!super::flush_metrics_v1(None, &failures, &flushed, true));
    assert!(matches!(
        super::begin_signed_tick_v1(None, &failures, &flushed, true),
        Err(codex_hepta_neuron::NeuronRuntimeError::PendingReconciliation)
    ));
}
