use super::*;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::durable_control::feature::FeatureOperationStateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[tokio::test]
async fn shared_model_guard_blocks_cpu_without_reservation_and_cancellation_returns_one_writer() {
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("original-inference.control");
    let shared = Arc::new(tokio::sync::Mutex::new(
        DurableInferenceControl::open(&path, /*capacity*/ 8).expect("original writer"),
    ));
    let cpu = CpuControlOwner::Shared(shared.clone());
    let request = NeuronFeatureRequestV1 {
        request_id: StableId::new("shared.original.cpu").expect("request"),
        generation: Generation::new(1).expect("model generation"),
        model_id: StableId::new("physical-model").expect("model"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"head"),
        weights_digest: Digest32::of_bytes(b"weights"),
        input_digest: Digest32::of_bytes(b"real invocation input"),
        feature_vector_q24: vec![2 << 24, 4 << 24],
        expected_output_width: 1,
    };
    let model_guard = shared.clone().lock_owned().await;
    let mut cancelled_model = Box::pin(async move {
        let _guard = model_guard;
        std::future::pending::<()>().await;
    });
    assert!(futures::poll!(cancelled_model.as_mut()).is_pending());
    assert!(matches!(cpu.try_lock(), Err(Error::WriterUnavailable)));
    assert_eq!(
        cpu.busy_error(),
        codex_hepta_neuron::NeuronModelError::Unavailable
    );
    assert!(DurableInferenceControl::open(&path, /*capacity*/ 8).is_err());
    drop(cancelled_model);
    {
        let mut cpu_guard = cpu.try_lock().expect("cancel returned original guard");
        assert_eq!(
            cpu_guard.feature_record(&request).expect("bounded query"),
            None
        );
        let reserved = cpu_guard
            .reserve_feature(request.clone())
            .expect("original reserve");
        assert_eq!(reserved.state, FeatureOperationStateV1::Reserved);
        assert!(shared.try_lock().is_err());
        assert!(DurableInferenceControl::open(&path, /*capacity*/ 8).is_err());
    }
    let model_guard = shared.lock().await;
    assert_eq!(
        model_guard
            .feature_record(&request)
            .expect("same original record")
            .expect("exists")
            .state,
        FeatureOperationStateV1::Reserved
    );
    drop(model_guard);
    drop(cpu);
    drop(shared);
    let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).expect("cold sole writer");
    assert_eq!(
        reopened
            .feature_record(&request)
            .expect("cold record")
            .expect("exists")
            .state,
        FeatureOperationStateV1::Reserved
    );
}
