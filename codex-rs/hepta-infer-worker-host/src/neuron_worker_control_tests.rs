use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error as WorkerError;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;

const Q: i64 = 1 << 24;

#[derive(Debug)]
struct FixtureDriver {
    calls: Arc<AtomicUsize>,
    indeterminate: bool,
    bad_head: bool,
    consumed_tokens: u32,
}

impl ModelDriver for FixtureDriver {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, WorkerError> {
        Ok(DriverModelHandle {
            opaque_id: "actual-loaded-fixture-model".to_owned(),
            observed_memory_bytes: 4096,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, WorkerError> {
        Err(WorkerError::DriverFailure(
            "ordinary output disabled".to_owned(),
        ))
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), WorkerError> {
        Ok(())
    }
}

impl NeuronFeatureDriver for FixtureDriver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, WorkerError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let successful = !self.indeterminate;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: successful,
            succeeded: successful,
            consumed_tokens: self.consumed_tokens,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: if self.bad_head {
                "f".repeat(64)
            } else {
                request.head_digest.clone()
            },
            drive_q24: if successful {
                vec![Q; request.expected_output_width]
            } else {
                Vec::new()
            },
            prediction_q24: if successful {
                vec![0; request.expected_output_width]
            } else {
                Vec::new()
            },
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 2048,
            queue_age_micros: 7,
            latency_micros: 20,
        })
    }
}

fn digest(v: &str) -> Digest32 {
    // The single-hex-character fixtures match loaded Worker manifest hashes.
    // Multi-character labels are semantic test data, not repeated hex bytes.
    if v.len() == 1 && v.as_bytes()[0].is_ascii_hexdigit() {
        v.repeat(64).parse().expect("fixed fixture digest")
    } else {
        Digest32::of_bytes(v.as_bytes())
    }
}

fn typed_request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: StableId::new("tick.1").unwrap(),
        generation: Generation::new(3).unwrap(),
        model_id: StableId::new("model.1").unwrap(),
        encoder_digest: digest("a"),
        head_digest: digest("b"),
        weights_digest: digest("3"),
        input_digest: digest("c"),
        feature_vector_q24: vec![Q / 4, -(Q / 8)],
        expected_output_width: 5,
    }
}

fn preadmitted_reservation(request: &NeuronFeatureRequestV1) -> WorkerRequest {
    let mut features = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: request.request_id.to_string(),
            reservation_id: "reservation.1".to_owned(),
            model_digest: "2".repeat(64),
            payload_digest: "e".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: "e".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    };
    let digest = canonical_neuron_feature_payload_digest(&features);
    features.authorization.payload_digest = digest.clone();
    features.authorization.lease_payload_digest = digest;
    features.authorization
}

fn worker(
    calls: Arc<AtomicUsize>,
    indeterminate: bool,
    bad_head: bool,
) -> InferenceWorker<FixtureDriver> {
    worker_with_observed_tokens(calls, indeterminate, bad_head, 4)
}

fn worker_with_observed_tokens(
    calls: Arc<AtomicUsize>,
    indeterminate: bool,
    bad_head: bool,
    consumed_tokens: u32,
) -> InferenceWorker<FixtureDriver> {
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_owned(),
        3,
        ResourceGrant {
            grant_id: "grant.1".to_owned(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 2,
            maximum_active_requests: 4,
            maximum_memory_bytes: 8192,
            semantic_digest: "1".repeat(64),
        },
        FixtureDriver {
            calls,
            indeterminate,
            bad_head,
            consumed_tokens,
        },
    )
    .unwrap();
    worker
        .load_model(
            100,
            ModelManifest {
                model_id: "model.1".to_owned(),
                model_digest: "2".repeat(64),
                weights_digest: "3".repeat(64),
                tokenizer_digest: "4".repeat(64),
                preprocessor_digest: "5".repeat(64),
                quantization_digest: "6".repeat(64),
                runtime_digest: "7".repeat(64),
                device_digest: "8".repeat(64),
                maximum_tokens: 128,
            },
        )
        .unwrap();
    worker
}

fn model_request(request: &NeuronFeatureRequestV1) -> NeuronModelRequestV1 {
    NeuronModelRequestV1 {
        request_id: request.request_id.clone(),
        config_id: StableId::new("neuron.config.1").unwrap(),
        generation: request.generation,
        model_id: request.model_id.clone(),
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        weights_digest: request.weights_digest,
        input_digest: request.input_digest,
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    }
}

#[test]
fn native_worker_single_use_port_executes_exact_neuron_model_port() {
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), false, false);
    let typed = typed_request();
    let reservation = preadmitted_reservation(&typed);
    let mut control = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        reservation,
        typed.generation,
        100,
    );
    assert!(control.reservation_unconsumed());
    let mut model = InferenceControlModelPort::new(&mut control);
    let actual = model.execute(&model_request(&typed)).unwrap();
    assert_eq!(actual.drive_q24, vec![Q; 5]);
    assert_eq!(actual.prediction_q24, vec![0; 5]);
    assert_eq!(actual.runtime_receipt.weights_digest, typed.weights_digest);
    assert_eq!(actual.runtime_receipt.tokenizer_digest, digest("4"));
    assert_eq!(actual.runtime_receipt.runtime_digest, digest("7"));
    assert!(!actual.output_digest.is_zero());
    assert_eq!(actual.runtime_receipt.resident_bytes, 4096);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(!control.reservation_unconsumed());
    assert_eq!(
        control.execute_feature(&typed),
        Err(NeuronModelError::Rejected),
        "a successful reservation cannot be reused"
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn native_worker_port_rejects_wrong_model_generation_and_payload_before_driver() {
    let typed = typed_request();
    for mode in 0..5 {
        let calls = Arc::new(AtomicUsize::new(0));
        let mut worker = worker(Arc::clone(&calls), false, false);
        let mut request = typed.clone();
        let mut reservation = preadmitted_reservation(&typed);
        let mut model_id = "model.1".to_owned();
        match mode {
            0 => model_id = "other-model".to_owned(),
            1 => request.generation = Generation::new(4).unwrap(),
            2 => request.feature_vector_q24[0] += 1,
            3 => reservation.reservation_model_digest = "f".repeat(64),
            _ => reservation.lease_payload_digest = "f".repeat(64),
        }
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            model_id,
            reservation,
            typed.generation,
            100,
        );
        assert_eq!(
            port.execute_feature(&request),
            Err(NeuronModelError::Rejected),
            "rejection mode {mode}"
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected),
            "a rejected reservation must never be reused"
        );
        assert!(!port.reservation_unconsumed());
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn native_worker_port_maps_unobserved_terminal_and_driver_drift() {
    let typed = typed_request();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), true, false);
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        preadmitted_reservation(&typed),
        typed.generation,
        100,
    );
    let receipt = port.execute_feature(&typed).unwrap();
    assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Indeterminate);
    assert!(receipt.drive_q24.is_empty());
    assert!(receipt.prediction_q24.is_empty());
    assert!(!port.reservation_unconsumed());

    let mut worker = self::worker(Arc::clone(&calls), false, true);
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        preadmitted_reservation(&typed),
        typed.generation,
        100,
    );
    assert_eq!(
        port.execute_feature(&typed),
        Err(NeuronModelError::Indeterminate),
        "driver identity drift after invocation has an unknown effect outcome"
    );
    assert_eq!(
        port.execute_feature(&typed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn post_driver_token_overrun_is_indeterminate_and_unrepeatable_across_ports() {
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_observed_tokens(Arc::clone(&calls), false, false, 65);
    let typed = typed_request();
    let reservation = preadmitted_reservation(&typed);
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            reservation.clone(),
            typed.generation,
            100,
        );
        // The request is authorized for 64 tokens but the backend observed
        // consuming 65. The effect may already have happened, so rejection
        // as "safe to retry" is incorrect.
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Indeterminate)
        );
        assert!(!port.reservation_unconsumed());
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let mut recreated = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        reservation,
        typed.generation,
        100,
    );
    assert_eq!(
        recreated.execute_feature(&typed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn native_worker_port_rejects_cancelled_or_expired_worker_reservation() {
    let typed = typed_request();
    for mode in 0..2 {
        let calls = Arc::new(AtomicUsize::new(0));
        let mut worker = worker(Arc::clone(&calls), false, false);
        let mut reservation = preadmitted_reservation(&typed);
        let now_ms = if mode == 0 {
            reservation.cancelled = true;
            100
        } else {
            10_000
        };
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            reservation,
            typed.generation,
            now_ms,
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected)
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn native_worker_to_agentd_tick_commits_and_recovers_independent_durable_journal_and_witness() {
    use std::fs::OpenOptions;

    use codex_hepta_agentd::AgentdNeuronOwner;
    use codex_hepta_neuron::AnchorWitnessStore;
    use codex_hepta_neuron::FileAnchorWitnessStore;
    use codex_hepta_neuron::JournalScope;
    use codex_hepta_neuron::NeuronCalibrationProfileV1;
    use codex_hepta_neuron::NeuronResourceEnvelopeV1;
    use codex_hepta_neuron::NeuronRuntime;
    use codex_hepta_neuron::NeuronRuntimeConfigV1;
    use codex_hepta_neuron::NeuronRuntimeError;
    use codex_hepta_neuron::NeuronTickInputV1;
    use codex_hepta_neuron::SparseConfig;
    use codex_hepta_neuron::canonical_feature_vector_digest_v1;

    // Simulate an independently durable Witness that refuses precisely the
    // first post-Journal CAS. The same tick may only reconcile that CAS; the
    // already-spent Worker reservation must never run its ModelDriver twice.
    struct RejectOneWitness {
        inner: FileAnchorWitnessStore,
        fail_once: bool,
    }

    impl AnchorWitnessStore for RejectOneWitness {
        fn current(
            &self,
        ) -> Result<Option<codex_hepta_neuron::JournalAnchor>, codex_hepta_neuron::WitnessStoreError>
        {
            self.inner.current()
        }

        fn compare_and_swap(
            &mut self,
            expected: Option<codex_hepta_neuron::JournalAnchor>,
            next: codex_hepta_neuron::JournalAnchor,
        ) -> Result<(), codex_hepta_neuron::WitnessStoreError> {
            if self.fail_once {
                self.fail_once = false;
                return Err(codex_hepta_neuron::WitnessStoreError::Unavailable);
            }
            self.inner.compare_and_swap(expected, next)
        }
    }

    let generation = Generation::new(3).unwrap();
    let q24 = Q;
    let native = SparseConfig {
        model_digest: digest("b"),
        normalization_digest: Digest32::of_bytes(b"frozen-normalization"),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: q24 / 2,
        inhibition_gain_q24: q24,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: q24 / 8,
        threshold_rate_q24: q24 / 8,
        threshold_min_q24: -q24,
        threshold_max_q24: q24,
        eligibility_decay_q24: q24 / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("neuron.config.1").unwrap(),
        generation,
        model_id: StableId::new("model.1").unwrap(),
        model_manifest_digest: digest("2"),
        encoder_digest: digest("a"),
        head_digest: native.model_digest,
        weights_digest: digest("3"),
        tokenizer_digest: digest("4"),
        preprocessor_digest: digest("5"),
        quantization_digest: digest("6"),
        runtime_digest: digest("7"),
        device_digest: digest("8"),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest().unwrap(),
        input_feature_dimension: 2,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration-artifact"),
            ood_artifact_digest: Digest32::of_bytes(b"ood-artifact"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * q24,
            maximum_in_domain_error_q24: 8 * q24,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    let subject = StableId::new("subject.1").unwrap();
    let objective = Digest32::of_bytes(b"objective");
    // Match the canonical Neuron subject-scope framing exactly: the owner
    // does not take a caller-provided scope checksum as evidence.
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    let raw_subject = subject.as_str().as_bytes();
    scope_bytes.extend_from_slice(&(raw_subject.len() as u32).to_be_bytes());
    scope_bytes.extend_from_slice(raw_subject);
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scope_bytes),
        objective_digest: objective,
    };
    let features = vec![q24 / 4, -(q24 / 8)];
    let input = NeuronTickInputV1 {
        tick_id: StableId::new("tick.1").unwrap(),
        subject_id: subject,
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features.clone(),
        objective_digest: objective,
        ndu_snapshot_digest: Digest32::of_bytes(b"frozen-ndu"),
        body_generation: Some(3),
        modulator_digest: None,
    };
    let temp = tempfile::tempdir().unwrap();
    let journal_path = temp.path().join("neuron.journal");
    let witness_path = temp.path().join("neuron.witness");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&journal_path)
        .unwrap();
    let witness_file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&witness_path)
        .unwrap();
    let witness = RejectOneWitness {
        inner: FileAnchorWitnessStore::open(witness_file, scope, generation, 16).unwrap(),
        fail_once: true,
    };
    let runtime =
        NeuronRuntime::bootstrap(file, native.clone(), scope, 16, config.clone(), witness).unwrap();
    let actual_request = runtime.model_request(&input).unwrap();
    let control_request = NeuronFeatureRequestV1 {
        request_id: actual_request.request_id,
        generation: actual_request.generation,
        model_id: actual_request.model_id,
        encoder_digest: actual_request.encoder_digest,
        head_digest: actual_request.head_digest,
        weights_digest: actual_request.weights_digest,
        input_digest: actual_request.input_digest,
        feature_vector_q24: actual_request.feature_vector_q24,
        expected_output_width: actual_request.expected_output_width,
    };
    use codex_hepta_infer_core::durable_control::Assignment;
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_infer_core::durable_control::InferenceRequest;
    use codex_hepta_infer_core::durable_control::RequestState;
    use codex_hepta_infer_core::durable_control::Reservation;
    use codex_hepta_infer_core::neuron_feature_request_digest_v1;
    use crate::neuron_durable_assignment::NeuronDurableAssignmentErrorV1;
    use crate::neuron_durable_assignment::claim_neuron_durable_dispatch_v1;
    
    // Bind the existing native Worker ModelPort to the ACTUAL fsynced
    // inference.control assignment. A directly manufactured WorkerPort would
    // not exercise the product's pre-execution single-use journal barrier.
    let mut feature = NeuronFeatureRequest {
        authorization: preadmitted_reservation(&control_request),
        encoder_digest: control_request.encoder_digest.to_string(),
        head_digest: control_request.head_digest.to_string(),
        weights_digest: control_request.weights_digest.to_string(),
        input_digest: control_request.input_digest.to_string(),
        feature_vector_q24: control_request.feature_vector_q24.clone(),
        expected_output_width: control_request.expected_output_width,
    };
    let payload_digest = canonical_neuron_feature_payload_digest(&feature);
    feature.authorization.payload_digest = payload_digest.clone();
    feature.authorization.lease_payload_digest = payload_digest.clone();
    let inference_journal_path = temp.path().join("inference.control");
    let mut control = DurableInferenceControl::open(&inference_journal_path, 32).unwrap();
    control
        .submit(
            100,
            InferenceRequest {
                request_id: control_request.request_id.to_string(),
                principal_id: "preapproved-agent".to_owned(),
                model_digest: feature.authorization.model_digest.clone(),
                payload_digest,
                maximum_tokens: 64,
                deadline_ms: 9_000,
                semantic_digest: neuron_feature_request_digest_v1(&control_request)
                    .unwrap()
                    .to_string(),
            },
        )
        .unwrap();
    control
        .reserve(
            100,
            control_request.request_id.as_str(),
            1,
            Reservation {
                reservation_id: "reservation.1".to_owned(),
                quota_units: 100,
                maximum_tokens: 64,
                authority_epoch: 4,
                valid_until_ms: 8_000,
            },
        )
        .unwrap();
    control
        .assign(
            control_request.request_id.as_str(),
            2,
            Assignment {
                worker_id: "worker.1".to_owned(),
                worker_generation: 3,
                assignment_digest: "f".repeat(64),
            },
        )
        .unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), false, false);
    let (claim, worker_port) =
        claim_neuron_durable_dispatch_v1(&mut control, &mut worker, &control_request, 100)
            .unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    assert_eq!(claim.revision, 4);
    assert!(!claim.idempotent);
    let mut agentd = AgentdNeuronOwner::new(runtime, worker_port);
    assert!(agentd.read_local_checkpoint_binding_v1().is_err());
    assert!(matches!(
        agentd.tick_with_observation_v1(input.clone()),
        Err(NeuronRuntimeError::WitnessAfterCommit { .. })
    ));
    // Journal was mutated, but no observation may be emitted before the
    // independent acknowledgement. Reuse the same input to reconcile only
    // the pending Witness CAS, not the already consumed Worker request.
    assert!(agentd.read_local_checkpoint_binding_v1().is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let (first, observation) = agentd.tick_with_observation_v1(input.clone()).unwrap();
    assert!(observation.validate_integrity());
    assert_eq!(observation.tick_id, input.tick_id);
    assert_eq!(observation.input_digest, input.semantic_digest().unwrap());
    assert_eq!(observation.checkpoint_before, Digest32::ZERO);
    assert_eq!(observation.checkpoint_after, first.tick.checkpoint_after);
    assert_eq!(observation.logical_sequence, 1);
    assert_eq!(
        observation.model_runtime_digest,
        first.model_runtime.semantic_digest().unwrap()
    );
    assert_eq!(
        observation.observed_memory_bytes,
        first.model_runtime.resident_bytes
    );
    assert_eq!(observation.abstain, first.tick.abstain);
    agentd
        .revalidate_current_tick_observation_v1(&observation)
        .unwrap();
    let mut tampered = observation.clone();
    tampered.observed_output_digest = digest("forged-output");
    assert!(!tampered.validate_integrity());
    assert!(
        agentd
            .revalidate_current_tick_observation_v1(&tampered)
            .is_err()
    );
    let mut tampered = observation.clone();
    tampered.checkpoint_before = digest("different-predecessor");
    assert!(!tampered.validate_integrity());

    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(first.model_runtime.weights_digest, digest("3"));
    assert_eq!(first.model_runtime.tokenizer_digest, digest("4"));
    assert_eq!(first.model_runtime.runtime_digest, digest("7"));
    let pinned = agentd.read_local_checkpoint_binding_v1().unwrap();
    assert_eq!(
        observation.local_checkpoint_binding_digest,
        pinned.binding_digest
    );
    assert!(pinned.validate_integrity());
    assert_eq!(pinned.anchor.checkpoint_digest, first.tick.checkpoint_after);
    // The committed anchor is stored in a separate fsynced file, not derived
    // from the mutable Journal that the model updated.

    // A second tick cannot fabricate a new reservation. The state owner must
    // not commit a successor checkpoint after the Worker refused reuse.
    let mut second = input;
    second.tick_id = StableId::new("tick.2").unwrap();
    second.logical_sequence = 2;
    second.monotonic_time_micros = 2000;
    second.checkpoint_digest = first.tick.checkpoint_after;
    assert!(matches!(
        agentd.tick_with_observation_v1(second),
        Err(NeuronRuntimeError::Model(NeuronModelError::Rejected))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        agentd.read_local_checkpoint_binding_v1().unwrap().anchor,
        pinned.anchor
    );

    // Simulate process-object death. Reopen BOTH the pre-Worker dispatch WAL
    // and the Neuron Journal/Witness. A replaced Worker has no in-memory
    // tombstones, yet the fsynced Dispatching claim cannot be replayed.
    drop(agentd);
    drop(control);
    let mut reopened_control = DurableInferenceControl::open(&inference_journal_path, 32).unwrap();
    assert_eq!(
        reopened_control.get(control_request.request_id.as_str()).unwrap().state,
        RequestState::Dispatching
    );
    let mut new_worker = worker_with_observed_tokens(Arc::clone(&calls), false, false, 4);
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(
            &mut reopened_control,
            &mut new_worker,
            &control_request,
            100,
        ),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let recovered_witness = FileAnchorWitnessStore::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&witness_path)
            .unwrap(),
        scope,
        generation,
        16,
    )
    .unwrap();
    assert_eq!(recovered_witness.current().unwrap(), Some(pinned.anchor));
    let recovered = NeuronRuntime::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&journal_path)
            .unwrap(),
        native,
        scope,
        16,
        config,
        pinned.anchor,
        recovered_witness,
    )
    .unwrap();
    assert_eq!(
        recovered.read_local_checkpoint_binding_v1().unwrap().anchor,
        pinned.anchor
    );
}

#[test]
fn reconstructed_worker_ports_cannot_replay_request_or_reservation_ids() {
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), false, false);
    let typed = typed_request();
    let original = preadmitted_reservation(&typed);
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            original.clone(),
            typed.generation,
            100,
        );
        assert!(port.execute_feature(&typed).is_ok());
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    // Reopening the port must not reset the Worker-owned tombstones.
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            original,
            typed.generation,
            100,
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected)
        );
    }
    let mut new_reservation = preadmitted_reservation(&typed);
    new_reservation.reservation_id = "reservation.2".to_owned();
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            new_reservation,
            typed.generation,
            100,
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected)
        );
    }
    let mut fresh = typed.clone();
    fresh.request_id = StableId::new("tick.2").unwrap();
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            preadmitted_reservation(&fresh),
            typed.generation,
            100,
        );
        assert_eq!(
            port.execute_feature(&fresh),
            Err(NeuronModelError::Rejected)
        );
    }
    // A genuinely new pair from the external reservation owner remains usable.
    let mut distinct = preadmitted_reservation(&fresh);
    distinct.reservation_id = "reservation.2".to_owned();
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            distinct,
            typed.generation,
            100,
        );
        // This particular pair has a previously denied request ID and so must
        // still fail closed. Use a new request+reservation below instead.
        assert_eq!(
            port.execute_feature(&fresh),
            Err(NeuronModelError::Rejected)
        );
    }
    fresh.request_id = StableId::new("tick.3").unwrap();
    let mut third = preadmitted_reservation(&fresh);
    third.reservation_id = "reservation.3".to_owned();
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        third,
        typed.generation,
        100,
    );
    assert!(port.execute_feature(&fresh).is_ok());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn early_rejection_and_unknown_terminal_consume_across_port_recreation() {
    let typed = typed_request();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), false, false);
    let reservation = preadmitted_reservation(&typed);
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "wrong.model".to_owned(),
            reservation.clone(),
            typed.generation,
            100,
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected)
        );
    }
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        reservation,
        typed.generation,
        100,
    );
    assert_eq!(
        port.execute_feature(&typed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);

    let mut worker = self::worker(Arc::clone(&calls), true, false);
    let reservation = preadmitted_reservation(&typed);
    {
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            reservation.clone(),
            typed.generation,
            100,
        );
        let observed = port.execute_feature(&typed).unwrap();
        assert_eq!(
            observed.status,
            NeuronFeatureTerminalStatusV1::Indeterminate
        );
    }
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        reservation,
        typed.generation,
        100,
    );
    assert_eq!(
        port.execute_feature(&typed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
