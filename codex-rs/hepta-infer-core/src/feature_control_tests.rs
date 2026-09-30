use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn private_directory() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "hepta-feature-control-{:032x}",
        rand::random::<u128>()
    ));
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(&path).expect("private test directory");
    path
}

fn request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: StableId::new("feature.original").expect("request ID"),
        generation: Generation::new(1).expect("generation"),
        model_id: StableId::new("cpu.actual").expect("model ID"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"heads"),
        weights_digest: Digest32::of_bytes(b"weights"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_vector_q24: vec![1 << 24, -(1 << 23)],
        expected_output_width: 1,
    }
}
fn receipt(request: &NeuronFeatureRequestV1) -> NeuronFeatureReceiptV1 {
    crate::build_neuron_feature_receipt_v1(
        request,
        crate::NeuronModelRuntimeTupleV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: Digest32::of_bytes(b"manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
            quantization_digest: Digest32::of_bytes(b"q24"),
            runtime_digest: Digest32::of_bytes(b"runtime"),
            device_digest: Digest32::of_bytes(b"device"),
        },
        crate::NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24: vec![1 << 23],
            prediction_q24: vec![1 << 22],
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 256,
            queue_age_micros: 0,
            latency_micros: 31,
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        },
    )
    .expect("typed observed receipt")
}

#[test]
fn original_receipt_and_dispatch_fence_survive_owner_reopen() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let request = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).expect("owner");
    assert_eq!(control.feature_record(&request).expect("query"), None);
    let reserved = control.reserve_feature(request.clone()).expect("reserve");
    assert_eq!(reserved.state, FeatureOperationStateV1::Reserved);
    drop(control);
    let mut control =
        DurableInferenceControl::open(&path, /*capacity*/ 8).expect("reopen reservation");
    assert_eq!(
        control.feature_record(&request).expect("query"),
        Some(reserved)
    );
    let permit = control
        .dispatch_feature(&request)
        .expect("one original permit");
    assert_eq!(permit.into_request(), request);
    assert!(matches!(
        control.dispatch_feature(&request),
        Err(Error::InvalidTransition)
    ));
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).expect("reopen fence");
    assert_eq!(
        control
            .feature_record(&request)
            .expect("query")
            .expect("record")
            .state,
        FeatureOperationStateV1::Dispatched
    );
    assert!(matches!(
        control.dispatch_feature(&request),
        Err(Error::InvalidTransition)
    ));
    let receipt = receipt(&request);
    control
        .observe_feature(&request, &receipt)
        .expect("original observation");
    control
        .observe_feature(&request, &receipt)
        .expect("exact retry");
    drop(control);
    let control =
        DurableInferenceControl::open(&path, /*capacity*/ 8).expect("reopen complete receipt");
    assert_eq!(
        control.feature_record(&request).expect("query"),
        Some(FeatureOperationRecordV1 {
            request,
            state: FeatureOperationStateV1::Observed(Box::new(receipt)),
        })
    );
}

#[test]
fn changed_context_and_unverified_observation_cannot_replace_original_truth() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let request = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).expect("owner");
    control.reserve_feature(request.clone()).expect("reserve");
    let mut changed = request.clone();
    changed.feature_vector_q24[0] += 1;
    assert!(matches!(
        control.reserve_feature(changed.clone()),
        Err(Error::Conflict)
    ));
    assert!(matches!(
        control.feature_record(&changed),
        Err(Error::Conflict)
    ));
    let original = receipt(&request);
    assert!(matches!(
        control.observe_feature(&request, &original),
        Err(Error::InvalidTransition)
    ));
    control.dispatch_feature(&request).expect("fence");
    let mut changed = original.clone();
    changed.drive_q24[0] += 1;
    assert!(matches!(
        control.observe_feature(&request, &changed),
        Err(Error::InvalidDigest(_))
    ));
    control
        .observe_feature(&request, &original)
        .expect("original receipt");
    let before = std::fs::read(&path).expect("journal");
    drop(control);
    let text = String::from_utf8(before)
        .expect("UTF8")
        .replace("\"latency_micros\":31", "\"latency_micros\":32");
    std::fs::write(&path, text).expect("tamper measured receipt");
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 8),
        Err(Error::CorruptJournal(_))
    ));
}

#[test]
fn partial_receipt_append_and_competing_owner_remain_fenced() {
    use std::io::Write;
    let directory = private_directory();
    let path = directory.join("control.log");
    let request = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).expect("owner");
    control.reserve_feature(request.clone()).expect("reserve");
    control.dispatch_feature(&request).expect("fence");
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 8),
        Err(Error::WriterUnavailable)
    ));
    drop(control);
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("journal");
    file.write_all(b"feature-v1|{\"event\":\"observe\"")
        .expect("partial crash append");
    file.sync_all().expect("real sync");
    drop(file);
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 8),
        Err(Error::CorruptJournal(_))
    ));
}

#[test]
fn all_operation_kinds_share_one_capacity_and_request_namespace() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let request = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("owner");
    control
        .reserve_feature(request.clone())
        .expect("feature uses existing capacity");
    let mut second = request.clone();
    second.request_id = StableId::new("feature.second").expect("second ID");
    assert!(matches!(
        control.reserve_feature(second),
        Err(Error::CapacityExceeded)
    ));
    let native = super::super::native::NativeRequest {
        request_id: request.request_id.to_string(),
        principal_id: "principal".into(),
        worker_generation: 1,
        model: "model".into(),
        payload_digest: request.input_digest.to_string(),
    };
    assert!(matches!(
        control.reserve_native(native, /*maximum_in_flight*/ 1),
        Err(Error::Conflict)
    ));
}
