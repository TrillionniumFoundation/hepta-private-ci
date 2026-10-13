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

/// Production acceptance requires distinct telemetry observations for signed
/// NDU reads, Final-use and WAL, without deriving any serving authority.
#[derive(Debug, Default)]
struct RecordedNeuronPhases(std::sync::Mutex<Vec<codex_hepta_types::PhaseMetricEventV1>>);

impl codex_hepta_types::PhaseMetricSinkV1 for RecordedNeuronPhases {
    fn record(
        &self,
        sample: codex_hepta_types::PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        self.0
            .lock()
            .map_err(|_| codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)?
            .push(sample);
        Ok(())
    }

    fn healthy(&self) -> bool {
        self.0.lock().is_ok()
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[derive(Debug)]
struct RejectNeuronMetrics;

impl codex_hepta_types::PhaseMetricSinkV1 for RejectNeuronMetrics {
    fn record(
        &self,
        _sample: codex_hepta_types::PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }

    fn healthy(&self) -> bool {
        false
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }
}

#[test]
fn signed_neuron_phase_telemetry_latches_failure_without_minting_authority() {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::PhaseMetricKindV1;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::time::Duration;

    let scope = Digest32::of_bytes(b"scope");
    let operation = Digest32::of_bytes(b"tick");
    let failed = AtomicU64::new(0);
    let captured = RecordedNeuronPhases::default();
    super::observe_phase_v1(
        Some(&captured),
        &failed,
        scope,
        operation,
        PhaseMetricKindV1::NduRead,
        Duration::from_micros(2),
        false,
    );
    super::observe_phase_v1(
        Some(&captured),
        &failed,
        scope,
        operation,
        PhaseMetricKindV1::FinalUse,
        Duration::from_micros(3),
        true,
    );
    assert_eq!(failed.load(Ordering::Acquire), 0);
    let observed = captured.0.lock().expect("observation");
    assert_eq!(observed.len(), 2);
    assert_eq!(observed[0].phase, PhaseMetricKindV1::NduRead);
    assert!(!observed[0].succeeded);
    assert_eq!(observed[1].phase, PhaseMetricKindV1::FinalUse);
    drop(observed);
    super::observe_phase_v1(
        Some(&RejectNeuronMetrics),
        &failed,
        scope,
        operation,
        PhaseMetricKindV1::Wal,
        Duration::from_micros(4),
        false,
    );
    assert_eq!(failed.load(Ordering::Acquire), 1);
}
