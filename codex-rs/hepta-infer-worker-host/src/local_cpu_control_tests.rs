use super::installed_model;
use crate::CpuNeuronControlConfigV1;
use crate::CpuNeuronInferenceControlV1;
use crate::local_cpu_model::CpuNeuronModelDriver;
use crate::model_worker::ResourceGrant;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_neuron::DurableNeuronFeatureResolutionV2;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

struct FixtureClock;
impl AuthorityClock for FixtureClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(1_000)
    }
}
fn config() -> CpuNeuronControlConfigV1 {
    CpuNeuronControlConfigV1 {
        worker_id: "cpu.fixture.worker".into(),
        generation: 1,
        grant: ResourceGrant {
            grant_id: "test.resource.grant".into(),
            authority_epoch: 1,
            generation: 1,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 1 << 20,
            semantic_digest: "1".repeat(64),
        },
        maximum_request_duration: Duration::from_secs(1),
    }
}

#[test]
fn original_physical_cpu_receipt_reopens_without_another_dense_execution() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let manifest = driver.manifest().clone();
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.original").expect("request"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new(manifest.model_id).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: manifest.weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let journal = directory.path().join("physical-control.log");
    let control = DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("control owner");
    let mut port =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("physical CPU port");
    assert_eq!(
        port.reconcile_feature(&request).expect("absent query"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
    let observed = port
        .execute_feature(&request)
        .expect("actual dense execution");
    assert_eq!(
        (observed.drive_q24.clone(), observed.prediction_q24.clone()),
        (vec![17 * (1 << 24) / 8], vec![11 * (1 << 24) / 8])
    );
    drop(port);
    let control =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("reopened original owner");
    let mut port =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("reopened CPU port");
    assert_eq!(
        port.reconcile_feature(&request)
            .expect("original receipt query"),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(observed.clone()))
    );
    assert_eq!(
        port.execute_feature(&request)
            .expect("exact original receipt"),
        observed
    );
    let mut changed = request;
    changed.feature_vector_q24[0] += 1;
    assert!(matches!(
        port.execute_feature(&changed),
        Err(NeuronModelError::Indeterminate)
    ));
}

#[test]
fn committed_dispatch_without_receipt_stays_unknown_after_cpu_owner_restart() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.crash-cut").expect("request"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let journal = directory.path().join("physical-control.log");
    let mut control =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("control owner");
    control
        .reserve_feature(request.clone())
        .expect("durable reservation");
    control
        .dispatch_feature(&request)
        .expect("durable dispatch fence");
    drop(control);
    let control =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("reopened original owner");
    let mut port =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("reopened CPU port");
    assert_eq!(
        port.reconcile_feature(&request).expect("query"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
    assert!(matches!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    ));
    assert_eq!(
        port.reconcile_feature(&request).expect("still unknown"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
}

#[test]
fn two_physical_generations_share_one_exclusive_control_writer_and_original_receipts() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let journal = directory.path().join("shared-control.log");
    let control = Arc::new(Mutex::new(
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("sole writer"),
    ));
    let mut first = CpuNeuronInferenceControlV1::open_shared(
        Arc::clone(&control),
        Arc::new(FixtureClock),
        &path,
        pin,
        config(),
    )
    .expect("first generation");
    let mut successor = config();
    successor.generation = 2;
    successor.grant.generation = 2;
    successor.worker_id = "cpu.fixture.successor".into();
    let mut second = CpuNeuronInferenceControlV1::open_shared(
        Arc::clone(&control),
        Arc::new(FixtureClock),
        &path,
        pin,
        successor,
    )
    .expect("second generation");
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.shared.first").expect("request"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let original = first
        .execute_feature(&request)
        .expect("first physical execution");
    let mut next = request.clone();
    next.request_id = StableId::new("cpu.shared.second").expect("request");
    next.generation = Generation::new(2).expect("generation");
    let next_receipt = second
        .execute_feature(&next)
        .expect("second physical execution");
    drop(first);
    drop(control);
    assert!(DurableInferenceControl::open(&journal, /*capacity*/ 8).is_err());
    assert_eq!(
        second
            .reconcile_feature(&request)
            .expect("original predecessor truth"),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(original.clone()))
    );
    drop(second);
    let recovered =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("reopen sole writer");
    assert_eq!(
        recovered
            .feature_record(&request)
            .expect("original")
            .expect("exists")
            .state,
        codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1::Observed(
            Box::new(original)
        )
    );
    assert_eq!(
        recovered
            .feature_record(&next)
            .expect("successor")
            .expect("exists")
            .state,
        codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1::Observed(
            Box::new(next_receipt)
        )
    );
}

#[test]
fn physical_cpu_traffic_retires_observed_features_and_replays_full_cold_receipts() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let journal = directory.path().join("traffic-control.log");
    let owner = Arc::new(Mutex::new(
        DurableInferenceControl::open(&journal, 2).expect("small hot capacity"),
    ));
    let mut port = CpuNeuronInferenceControlV1::open_shared(
        Arc::clone(&owner),
        Arc::new(FixtureClock),
        &path,
        pin,
        config(),
    )
    .expect("real CPU port");
    let mut originals = Vec::new();
    for ordinal in 0..12 {
        let request = NeuronFeatureRequestV1 {
            request_id: StableId::new(format!("cpu.traffic.{ordinal}")).expect("ID"),
            generation: Generation::new(1).expect("generation"),
            model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
            encoder_digest: encoder.parse().expect("encoder"),
            head_digest: head.parse().expect("head"),
            weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
            input_digest: pin,
            feature_vector_q24: vec![(2 << 24) + ordinal, 4 << 24],
            expected_output_width: 1,
        };
        let receipt = match port.execute_feature(&request) {
            Ok(receipt) => receipt,
            Err(NeuronModelError::Indeterminate) => {
                // A 100ms admission maintenance slice can expire during real
                // fsync. Retry only after this same writer's periodic work;
                // no unknown dispatch or completed receipt is fabricated.
                port.maintain_history(8, codex_hepta_infer_core::durable_control::feature::DEFAULT_FEATURE_COLD_BYTE_LIMIT,
                    Duration::from_secs(180)).expect("periodic physical retirement");
                port.execute_feature(&request)
                    .expect("actual execution after capacity recovery")
            }
            Err(error) => panic!("unexpected physical error: {error:?}"),
        };
        assert!(
            owner
                .lock()
                .expect("sole writer")
                .resident_feature_records()
                <= 2
        );
        originals.push((request, receipt));
    }
    let mut malformed = originals[0].0.clone();
    malformed.request_id = StableId::new("cpu.invalid.width").expect("ID");
    malformed.expected_output_width = 2;
    assert!(matches!(
        port.execute_feature(&malformed),
        Err(NeuronModelError::Rejected)
    ));
    assert_eq!(
        port.reconcile_feature(&malformed)
            .expect("never reserved bad shape"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
    malformed.expected_output_width = 1;
    malformed.feature_vector_q24.pop();
    assert!(matches!(
        port.execute_feature(&malformed),
        Err(NeuronModelError::Rejected)
    ));
    let report = port
        .maintain_history(
            8,
            codex_hepta_infer_core::durable_control::feature::DEFAULT_FEATURE_COLD_BYTE_LIMIT,
            Duration::from_secs(180),
        )
        .expect("final same owner maintenance");
    assert_eq!(report.cold_records, 12);
    assert_eq!(report.resident_feature_records, 0);
    drop(port);
    drop(owner);
    let control = DurableInferenceControl::open(&journal, 2).expect("bounded cold restart");
    let mut port =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("reopened CPU owner");
    for (request, original) in originals {
        assert_eq!(
            port.reconcile_feature(&request)
                .expect("full cold receipt query"),
            DurableNeuronFeatureResolutionV2::Observed(Box::new(original.clone()))
        );
        assert_eq!(
            port.execute_feature(&request)
                .expect("replay with original actual timing"),
            original
        );
    }
}

#[test]
fn physical_cpu_cold_pressure_stops_new_execution_but_returns_original_receipt() {
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let control = DurableInferenceControl::open(directory.path().join("pressure-control.log"), 2)
        .expect("owner");
    let mut port =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("CPU owner");
    port.maintain_history(1, 1, Duration::from_secs(10))
        .expect("pin real small byte limit before work");
    let original = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.pressure.original").expect("ID"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let receipt = port.execute_feature(&original).expect("physical original");
    let mut next = original.clone();
    next.request_id = StableId::new("cpu.pressure.next").expect("next ID");
    assert!(matches!(
        port.execute_feature(&next),
        Err(NeuronModelError::Indeterminate)
    ));
    assert_eq!(
        port.reconcile_feature(&next)
            .expect("never admitted next request"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
    assert_eq!(
        port.execute_feature(&original)
            .expect("original receipt under pressure"),
        receipt
    );
}

#[test]
fn physical_cpu_refreshes_protected_time_after_dispatch_fsync_before_worker_admission() {
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    struct ExpiringClock(AtomicUsize);
    impl AuthorityClock for ExpiringClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(if self.0.fetch_add(1, Ordering::SeqCst) < 2 {
                1_000
            } else {
                20_000
            })
        }
    }
    let (directory, path, pin, encoder, head) = installed_model();
    let driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned model");
    let journal = directory.path().join("expired-control.log");
    let control = DurableInferenceControl::open(&journal, 2).expect("owner");
    let mut port = CpuNeuronInferenceControlV1::open(
        control,
        Arc::new(ExpiringClock(AtomicUsize::new(0))),
        &path,
        pin,
        config(),
    )
    .expect("CPU owner with protected clock");
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("cpu.expired.after-fsync").expect("ID"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new(driver.manifest().model_id.clone()).expect("model"),
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("head"),
        weights_digest: driver.manifest().weights_digest.parse().expect("weights"),
        input_digest: pin,
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    assert!(matches!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    ));
    assert_eq!(
        port.reconcile_feature(&request).expect("fence retained"),
        DurableNeuronFeatureResolutionV2::Unknown
    );
    let report = port
        .maintain_history(
            1,
            codex_hepta_infer_core::durable_control::feature::DEFAULT_FEATURE_COLD_BYTE_LIMIT,
            Duration::from_secs(180),
        )
        .expect("unknown cannot retire");
    assert_eq!(report.archived_records, 0);
    assert_eq!(report.resident_feature_records, 1);
    drop(port);
    let control = DurableInferenceControl::open(&journal, 2).expect("reopen real expired fence");
    assert_eq!(
        control
            .feature_record(&request)
            .expect("original state")
            .expect("record")
            .state,
        codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1::Dispatched
    );
}

#[path = "local_cpu_runtime_binding_tests.rs"]
mod runtime_binding;
