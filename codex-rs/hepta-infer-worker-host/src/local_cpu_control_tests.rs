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
