//! External non-cfg(test) Agentd API contract. No issuer/Control/Effect
//! authority is constructed, and no model or signed nonce can be invoked.
//! This checks that future independently provisioned callers can actually
//! name the exact signed NDU read, frontier and non-authorizing verifier.

use codex_hepta_agentd::AgentdNeuronOwner;
use codex_hepta_agentd::NduReadFrontierPortV1;
use codex_hepta_agentd::NduReadVerificationErrorV1;
use codex_hepta_agentd::NduReadVerifierV1;
use codex_hepta_agentd::SignedNduSnapshotReadV1;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::WitnessStoreError;

struct ExternalWitness;

impl AnchorWitnessStore for ExternalWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Err(WitnessStoreError::Unavailable)
    }
}

struct ExternalNeverExecute;

impl NeuronInferenceControlPort for ExternalNeverExecute {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn external_signed_neuron_contract_is_typeable_without_granting_effects() {
    type Owner = AgentdNeuronOwner<ExternalWitness, ExternalNeverExecute>;
    let method: fn(
        &mut Owner,
        NeuronTickInputV1,
        &SignedNduSnapshotReadV1,
        &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> = Owner::tick_bound;
    let _ = method;
    let name = std::any::type_name::<NduReadVerifierV1>();
    assert!(name.contains("NduReadVerifierV1"));
    assert!(
        std::any::type_name::<NduReadVerificationErrorV1>().contains("NduReadVerificationErrorV1")
    );
    assert!(std::any::type_name::<dyn NduReadFrontierPortV1>().contains("NduReadFrontierPortV1"));
    // No original Control signer or model effect is constructed in this test.
}

#[cfg(unix)]
#[test]
fn external_non_test_agentd_neuron_denies_before_journal_or_model_effect() {
    use codex_hepta_contracts::FinalUseBinding;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_neuron::NeuronCalibrationProfileV1;
    use codex_hepta_neuron::NeuronResourceEnvelopeV1;
    use codex_hepta_neuron::NeuronRuntime;
    use codex_hepta_neuron::NeuronRuntimeConfigV1;
    use codex_hepta_neuron::SparseConfig;
    use codex_hepta_neuron::JournalScope;
    use codex_hepta_neuron::canonical_feature_vector_digest_v1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::NduSnapshotRefV1;
    use codex_hepta_types::StableId;
    use std::fs;
    use std::fs::OpenOptions;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    const Q24: i64 = 1 << 24;
    fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
        match value {
            Ok(value) => value,
            Err(error) => panic!("required original journal test fixture: {error:?}"),
        }
    }

    #[derive(Clone)]
    struct CountingPort(Arc<AtomicUsize>);
    impl NeuronInferenceControlPort for CountingPort {
        fn execute_feature(
            &mut self,
            _request: &NeuronFeatureRequestV1,
        ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(NeuronModelError::Indeterminate)
        }
    }

    // An attacker-supplied healthy Metrics trait object is not original
    // Evidence custody. An unauthorized non-test Tick cannot emit even an
    // admission or failure observation into such a writer.
    #[derive(Debug)]
    struct UntrustedTelemetry {
        records: Arc<AtomicUsize>,
        flushes: Arc<AtomicUsize>,
    }
    impl codex_hepta_types::PhaseMetricSinkV1 for UntrustedTelemetry {
        fn record(
            &self,
            _sample: codex_hepta_types::PhaseMetricEventV1,
        ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
            self.records.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        fn healthy(&self) -> bool {
            true
        }

        fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
            self.flushes.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    let directory = checked(tempfile::tempdir());
    checked(fs::set_permissions(
        directory.path(),
        fs::Permissions::from_mode(0o700),
    ));
    let file_path = directory.path().join("actual-neuron-journal");
    let journal = checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&file_path),
    );
    let generation = checked(Generation::new(1));
    let model_digest = Digest32::of_bytes(b"owner-test-model");
    let normalization_digest = Digest32::of_bytes(b"owner-test-normalization");
    let native = SparseConfig {
        model_digest,
        normalization_digest,
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: Q24,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q24 / 8,
        threshold_rate_q24: Q24 / 8,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("agentd.external.fixture")),
        generation,
        model_id: checked(StableId::new("model.untrusted")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 8 * Q24,
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
    let subject = checked(StableId::new("scope.agentd.external"));
    let subject_bytes = subject.as_str().as_bytes();
    let mut scoped = b"hepta.neuron.subject-scope.v1".to_vec();
    scoped.extend_from_slice(&(subject_bytes.len() as u32).to_be_bytes());
    scoped.extend_from_slice(subject_bytes);
    let objective = Digest32::of_bytes(b"objective");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(&scoped),
        objective_digest: objective,
    };
    let runtime = checked(NeuronRuntime::bootstrap(
        journal,
        native,
        scope,
        16,
        config,
        ExternalWitness,
    ));
    let original_journal = checked(fs::read(&file_path));
    let calls = Arc::new(AtomicUsize::new(0));
    let records = Arc::new(AtomicUsize::new(0));
    let flushes = Arc::new(AtomicUsize::new(0));
    let sink = Arc::new(UntrustedTelemetry {
        records: Arc::clone(&records),
        flushes: Arc::clone(&flushes),
    });
    let mut owner = AgentdNeuronOwner::new(runtime, CountingPort(Arc::clone(&calls)))
        .with_metric_sink(sink);
    let features = vec![Q24 / 4, Q24 / 8, -Q24 / 8];
    let ndu_digest = Digest32::of_bytes(b"ndu");
    let input = NeuronTickInputV1 {
        tick_id: checked(StableId::new("tick.untrusted")),
        subject_id: subject.clone(),
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: objective,
        ndu_snapshot_digest: ndu_digest,
        body_generation: Some(1),
        modulator_digest: None,
    };
    let signed_read = SignedNduSnapshotReadV1 {
        snapshot: NduSnapshotRefV1 {
            scope_id: subject.clone(),
            owner_id: checked(StableId::new("ndu.owner.fixture")),
            generation,
            route_fence: 1,
            revocation_epoch: 7,
            policy_digest: Digest32::of_bytes(b"policy"),
            snapshot_digest: ndu_digest,
            projection_head_digest: Digest32::of_bytes(b"projection"),
        },
        read_id: checked(StableId::new("read.untrusted")),
        read_receipt_digest: Digest32::of_bytes(b"unauthorized-read"),
        issued_at_unix_ms: 100,
        expires_at_unix_ms: 1000,
        signature: [0; 64],
    };
    let forged = SignedFinalUseGrant {
        grant: FinalUseGrant {
            schema_version: 1,
            signer_id: "untrusted-test".into(),
            authority_epoch: 7,
            grant_id: "untrusted-grant".into(),
            nonce: [5; 32],
            binding: FinalUseBinding {
                subject_id: subject.as_str().to_owned(),
                destination_id: "neuron.model".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: 100,
            expires_at_unix_ms: 1000,
        },
        signature: vec![0; 64],
    };
    assert!(matches!(
        owner.tick_bound(input, &signed_read, &forged),
        Err(NeuronRuntimeError::OriginalEffectOwnerUnverified)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0, "no backend invocation");
    assert_eq!(
        records.load(Ordering::SeqCst),
        0,
        "unauthorized call cannot stage unbound original Evidence"
    );
    assert_eq!(
        flushes.load(Ordering::SeqCst),
        0,
        "unauthorized call cannot flush an unbound telemetry writer"
    );
    assert!(!owner.production_metrics_ready());
    assert_eq!(
        checked(fs::read(&file_path)),
        original_journal,
        "no pre-authority Evidence or Neuron journal write"
    );
    assert!(checked(owner.runtime().current_anchor()).is_none());
    assert!(owner.effect_intent_status().is_none());
}
