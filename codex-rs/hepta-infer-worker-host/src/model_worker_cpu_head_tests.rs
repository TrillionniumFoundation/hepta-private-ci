use super::*;

const Q24: i64 = 1_i64 << 24;

fn sample_head(reversed: bool) -> CpuGatedHead {
    CpuGatedHead {
        input_width: 2,
        output_width: 2,
        drive_weights_q24: if reversed {
            vec![-Q24, 0, 0, -Q24]
        } else {
            vec![Q24, 0, 0, Q24]
        },
        prediction_weights_q24: vec![0, Q24, Q24, 0],
        gate_weights_q24: vec![0; 4],
        drive_bias_q24: vec![0; 2],
        prediction_bias_q24: vec![0; 2],
        gate_bias_q24: if reversed { vec![0; 2] } else { vec![Q24; 2] },
    }
}

fn model_manifest(weights_digest: String) -> ModelManifest {
    ModelManifest {
        model_id: "model.cpu-head".to_string(),
        model_digest: "2".repeat(64),
        weights_digest,
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    }
}

fn local_worker() -> (InferenceWorker<CpuGatedHeadDriver>, Vec<String>) {
    let encoder = "a".repeat(64);
    let specs = vec![sample_head(false), sample_head(true)];
    let head_digests = specs
        .iter()
        .map(|head| head.digest().expect("digest"))
        .collect::<Vec<_>>();
    let weights = cpu_gated_bundle_weights_digest(&encoder, &specs).expect("weights");
    let manifest = model_manifest(weights);
    let driver =
        CpuGatedHeadDriver::new(manifest.clone(), encoder, specs).expect("pinned local tensors");
    let grant = ResourceGrant {
        grant_id: "grant.cpu".to_string(),
        authority_epoch: 4,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 4,
        maximum_memory_bytes: 1_000_000,
        semantic_digest: "1".repeat(64),
    };
    let mut worker =
        InferenceWorker::new(100, "worker.cpu".to_string(), 3, grant, driver).expect("worker");
    worker.load_model(100, manifest).expect("load");
    (worker, head_digests)
}

fn cpu_request(number: usize, head_digest: String, weights_digest: String) -> NeuronFeatureRequest {
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: format!("request.cpu.{number}"),
            reservation_id: format!("reservation.cpu.{number}"),
            model_digest: "2".repeat(64),
            payload_digest: "0".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: "0".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: "a".repeat(64),
        head_digest,
        weights_digest,
        input_digest: format!("{number:064x}"),
        feature_vector_q24: vec![Q24 / 2, Q24 / 4],
        expected_output_width: 2,
    };
    let digest = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = digest.clone();
    request.authorization.lease_payload_digest = digest;
    request
}

#[test]
fn native_cpu_batch_computes_two_distinct_cell_heads() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let requests = vec![
        cpu_request(1, heads[0].clone(), weights.clone()),
        cpu_request(2, heads[1].clone(), weights),
    ];
    let batch = worker
        .run_neuron_features_backend_batch(100, "model.cpu-head", requests)
        .expect("real CPU batch");
    assert_eq!(batch.receipts.len(), 2);
    assert_eq!(batch.receipts[0].drive_q24, vec![Q24 / 2, Q24 / 4]);
    assert_eq!(batch.receipts[0].prediction_q24, vec![Q24 / 4, Q24 / 2]);
    assert_eq!(batch.receipts[1].drive_q24, vec![-Q24 / 4, -Q24 / 8]);
    assert_eq!(batch.receipts[1].prediction_q24, vec![Q24 / 8, Q24 / 4]);
    assert_ne!(
        batch.receipts[0].receipt_digest,
        batch.receipts[1].receipt_digest
    );
    assert!(batch.receipts.iter().all(|r| !r.authority.grants_any()));
    assert!(batch.observed_peak_memory_bytes >= worker.driver.tracked_weights_bytes);
    worker.unload_model(100, "model.cpu-head").expect("unload");
}

#[test]
fn native_cpu_single_and_batch_have_same_numeric_outputs() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let first = cpu_request(1, heads[0].clone(), weights.clone());
    let single = worker
        .run_neuron_features_receipt(100, "model.cpu-head", first.clone())
        .expect("single");
    let batch = worker
        .run_neuron_features_backend_batch(
            100,
            "model.cpu-head",
            vec![first, cpu_request(2, heads[1].clone(), weights)],
        )
        .expect("batch");
    assert_eq!(single.drive_q24, batch.receipts[0].drive_q24);
    assert_eq!(single.prediction_q24, batch.receipts[0].prediction_q24);
    assert_eq!(single.request_digest, batch.receipts[0].request_digest);
}

#[test]
fn native_cpu_rejects_tampered_tensors_and_head_identity() {
    let encoder = "a".repeat(64);
    let specs = vec![sample_head(false), sample_head(true)];
    let weights = cpu_gated_bundle_weights_digest(&encoder, &specs).expect("weights");
    let mut changed = specs.clone();
    changed[0].drive_weights_q24[0] += 1;
    assert!(matches!(
        CpuGatedHeadDriver::new(model_manifest(weights.clone()), encoder, changed),
        Err(Error::ModelMismatch)
    ));
    let (mut worker, heads) = local_worker();
    let mut request = cpu_request(1, "f".repeat(64), weights.clone());
    let mut request2 = cpu_request(2, heads[1].clone(), weights);
    assert!(
        worker
            .run_neuron_features_backend_batch(
                100,
                "model.cpu-head",
                vec![request.clone(), request2.clone()]
            )
            .is_err()
    );
    request.encoder_digest = "f".repeat(64);
    request.head_digest = heads[0].clone();
    let payload = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;
    request2.encoder_digest = request.encoder_digest.clone();
    let payload = canonical_neuron_feature_payload_digest(&request2);
    request2.authorization.payload_digest = payload.clone();
    request2.authorization.lease_payload_digest = payload;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.cpu-head", vec![request, request2]),
        Err(Error::ModelMismatch)
    );
}

#[test]
fn q24_bankers_rounding_and_saturation_reject_are_deterministic() {
    assert_eq!(round_q48_to_q24(Q / 2), Ok(0));
    assert_eq!(round_q48_to_q24(3 * Q / 2), Ok(2));
    assert_eq!(round_q48_to_q24(-Q / 2), Ok(0));
    assert_eq!(round_q48_to_q24(-3 * Q / 2), Ok(-2));
    assert_eq!(
        round_q48_to_q24(9 * Q * Q),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn gated_head_driver_refuses_generic_text_model_execution() {
    let (mut worker, _) = local_worker();
    let request = WorkerRequest {
        request_id: "request.cpu.generic".to_string(),
        reservation_id: "reservation.cpu.generic".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: "3".repeat(64),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: "3".repeat(64),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    };
    assert!(matches!(
        worker.run(100, "model.cpu-head", request),
        Err(Error::DriverFailure(_))
    ));
}

#[test]
fn compact_constant_gate_and_zero_prediction_do_not_triple_head_storage() {
    let mut compact = sample_head(false);
    compact.prediction_weights_q24.clear();
    compact.gate_weights_q24.clear();
    let full = sample_head(false);
    assert_eq!(
        compact.digest().expect("canonical Q24 head digest"),
        "3b7962a1f859f4e3a2594c37a3d3b99e6c6c6813102947f9ab3e68aa0cb22e82"
    );
    assert_eq!(
        cpu_gated_bundle_weights_digest(&"a".repeat(64), &[compact.clone()])
            .expect("cross-language bundle digest"),
        "277d9ebc5a6066bcf29e846081cd771578b05e570fd3dbad8785cc3ce05162df"
    );
    assert_ne!(
        compact.digest().expect("digest"),
        full.digest().expect("digest")
    );
    assert!(
        compact.tracked_parameter_bytes().expect("bytes")
            < full.tracked_parameter_bytes().expect("bytes")
    );
    let (drive, prediction) = compact
        .infer(&[Q24 / 2, Q24 / 4])
        .expect("compact inference");
    assert_eq!(drive, vec![Q24 / 2, Q24 / 4]);
    assert_eq!(prediction, vec![0, 0]);
}
