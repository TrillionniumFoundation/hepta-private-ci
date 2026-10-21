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
    // The first invalid batch reached the driver, whose failure cannot
    // prove no physical execution occurred. The generation is quarantined:
    // a follow-up request must not re-enter the driver even if its identity
    // would independently have been rejected as ModelMismatch.
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.cpu-head", vec![request, request2]),
        Err(Error::ExecutionIndeterminate)
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
    // DriverFailure is not a safe retry verdict after an attempted run.
    // The Worker must fence the entire generation as indeterminate.
    assert!(matches!(
        worker.run(100, "model.cpu-head", request),
        Err(Error::ExecutionIndeterminate)
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

    // The explicit all-zero 2x2 gate matrix is a *valid dense matrix*.
    // Its digest differs from the compact zero-matrix profile, but arithmetic
    // must be identical. This is also asserted by the Python Q24 reference.
    let mut dense_zero = compact.clone();
    dense_zero.gate_weights_q24 = vec![0; 4];
    assert_ne!(
        dense_zero.digest().expect("dense gate digest"),
        compact.digest().expect("compact gate digest")
    );
    assert_eq!(
        dense_zero
            .infer(&[Q24 / 2, Q24 / 4])
            .expect("dense zero gate"),
        compact.infer(&[Q24 / 2, Q24 / 4]).expect("compact gate")
    );
}

#[test]
fn hard_sigmoid_half_ties_round_to_even_not_towards_zero() {
    // A zero-weight affine output with a unit drive lets us observe the
    // half-sigmoid quantization exactly, including signed odd-Q24 ties.
    let mut candidate = CpuGatedHead {
        input_width: 1,
        output_width: 1,
        drive_weights_q24: vec![0],
        prediction_weights_q24: Vec::new(),
        gate_weights_q24: Vec::new(),
        drive_bias_q24: vec![Q24],
        prediction_bias_q24: vec![0],
        gate_bias_q24: vec![0],
    };
    for (pre, expected) in [
        (-Q24 - 1, 0),
        (-Q24, 0),
        (-3, Q24 / 2 - 2),
        (-1, Q24 / 2),
        (0, Q24 / 2),
        (1, Q24 / 2),
        (3, Q24 / 2 + 2),
        (Q24, Q24),
        (Q24 + 1, Q24),
    ] {
        candidate.gate_bias_q24[0] = pre;
        let (drive, prediction) = candidate.infer(&[0]).expect("bounded Q24 gate");
        assert_eq!(drive, vec![expected], "gate_pre={pre}");
        assert_eq!(prediction, vec![0]);
    }
}

#[test]
fn hard_sigmoid_gate_rounding_propagates_correctly_across_rows() {
    let mut candidate = sample_head(false);
    candidate.gate_weights_q24.clear();
    candidate.gate_bias_q24 = vec![-1, 3];
    let input = [Q24 / 2, Q24 / 4];
    let (drive, prediction) = candidate.infer(&input).expect("gated arithmetic");
    assert_eq!(drive[0], Q24 / 4);
    assert_eq!(drive[1], Q24 / 8); // 0.5 LSB ties to the even Q24 value
    assert_eq!(prediction[0], Q24 / 8);
    assert_eq!(prediction[1], Q24 / 4 + 1);
}

#[test]
fn grouped_cpu_head_kernel_matches_scalar_reference_for_32_lanes() {
    // Real Q24 multiplication over a contiguous buffer with mixed-sign
    // inputs and no use of the per-Cell infer() inside the batched kernel.
    let mut compact = sample_head(false);
    compact.gate_weights_q24.clear();
    compact.prediction_weights_q24.clear();
    compact.gate_bias_q24 = vec![-1, 3];
    for head in [sample_head(false), sample_head(true), compact] {
        let packed = (0..32)
            .flat_map(|n| [(n as i64 - 16) * (Q24 / 64), (n as i64 - 8) * (Q24 / 128)])
            .collect::<Vec<_>>();
        let all = (0..32).collect::<Vec<_>>();
        let batched = head.infer_batch(&packed, &all, 2).expect("Q24 batch");
        assert_eq!(batched.len(), 32);
        for (lane, (drive, prediction)) in batched.into_iter().enumerate() {
            let expected = head
                .infer(&packed[lane * 2..(lane + 1) * 2])
                .expect("single Q24 reference");
            assert_eq!((drive, prediction), expected, "lane {lane}");
        }

        let sparse_lanes = [31, 1, 17, 4, 28];
        let sparse = head
            .infer_batch(&packed, &sparse_lanes, 2)
            .expect("reordered lanes");
        for (&lane, observed) in sparse_lanes.iter().zip(sparse.iter()) {
            assert_eq!(
                observed,
                &head
                    .infer(&packed[lane * 2..(lane + 1) * 2])
                    .expect("single"),
                "reordered lane {lane}"
            );
        }
    }
}

#[test]
fn grouped_cpu_head_kernel_rejects_bad_lanes_and_feature_values() {
    let head = sample_head(false);
    let inputs = [Q24 / 2, Q24 / 4, Q24 / 4, Q24 / 2];
    assert_eq!(
        head.infer_batch(&inputs, &[0, 0], 2),
        Err(Error::FeatureBatchMismatch)
    );
    assert_eq!(
        head.infer_batch(&inputs, &[2], 2),
        Err(Error::FeatureBatchMismatch)
    );
    assert_eq!(
        head.infer_batch(&inputs, &[], 2),
        Err(Error::FeatureBatchMismatch)
    );
    assert_eq!(
        head.infer_batch(&inputs, &[0, 1], 3),
        Err(Error::FeatureBatchMismatch)
    );
    let bad = [Q24 / 2, Q24 / 4, 9 * Q24, Q24 / 2];
    assert_eq!(head.infer_batch(&bad, &[0, 1], 2), Err(Error::FeatureLimit));
    // No silent overflow/clamping of a large Q24 accumulator.
    let mut oversized = sample_head(false);
    oversized.drive_weights_q24 = vec![8 * Q24; 4];
    oversized.drive_bias_q24 = vec![8 * Q24; 2];
    let large_inputs = [8 * Q24, 8 * Q24, 8 * Q24, 8 * Q24];
    assert_eq!(
        oversized.infer_batch(&large_inputs, &[0, 1], 2),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn grouped_multi_head_worker_batch_preserves_receipts_and_single_path() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let mut requests = (0..4)
        .map(|i| cpu_request(i + 1, heads[i % 2].clone(), weights.clone()))
        .collect::<Vec<_>>();
    for (i, request) in requests.iter_mut().enumerate() {
        request.feature_vector_q24 = vec![(i as i64 - 2) * Q24 / 4, (i as i64 + 1) * Q24 / 8];
        let digest = canonical_neuron_feature_payload_digest(request);
        request.authorization.payload_digest = digest.clone();
        request.authorization.lease_payload_digest = digest;
    }
    let separate = requests
        .iter()
        .map(|request| {
            worker
                .run_neuron_features_receipt(100, "model.cpu-head", request.clone())
                .expect("single request")
        })
        .collect::<Vec<_>>();
    let batch = worker
        .run_neuron_features_backend_batch(100, "model.cpu-head", requests)
        .expect("one real grouped CPU batch");
    assert_eq!(worker.driver.backend_batch_invocations, 1);
    assert_eq!(batch.receipts.len(), 4);
    // A multi-lane kernel has one real backend duration; per-member receipt
    // timing must never restart a new timer after the arithmetic is done.
    assert!(
        batch
            .receipts
            .iter()
            .all(|receipt| { receipt.latency_micros == batch.backend_elapsed_micros })
    );
    for (i, (scalar, batched)) in separate.iter().zip(batch.receipts.iter()).enumerate() {
        assert_eq!(scalar.drive_q24, batched.drive_q24, "Cell {i}");
        assert_eq!(scalar.prediction_q24, batched.prediction_q24, "Cell {i}");
        assert_eq!(scalar.request_digest, batched.request_digest, "Cell {i}");
        assert!(!batched.authority.grants_any());
    }
    worker
        .unload_model(100, "model.cpu-head")
        .expect("clean unload");
}

#[test]
fn actual_q24_cpu_head_fails_closed_when_scratch_exceeds_generation_budget() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let resident = worker.driver.tracked_weights_bytes;
    // The fixture shrinks its grant to exercise the exact post-driver limit.
    // This checks resource receipts, not system-level physical RSS.
    worker.grant.maximum_memory_bytes = resident + 31;
    assert_eq!(
        worker.run_neuron_features(
            100,
            "model.cpu-head",
            cpu_request(1, heads[0].clone(), weights),
        ),
        Err(Error::ModelCapacity),
    );
    assert!(worker.requires_external_recovery());
}

#[test]
fn actual_q24_cpu_batch_accounts_for_all_members_output_buffers() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let resident = worker.driver.tracked_weights_bytes;
    // The old path discovered known over-budget scratch only AFTER execution
    // and poisoned the generation. The new preflight must reject it before
    // a single backend call, preserving a clean retry under a larger grant.
    worker.grant.maximum_memory_bytes = resident + 32;
    assert_eq!(
        worker.run_neuron_features_backend_batch(
            100,
            "model.cpu-head",
            vec![
                cpu_request(1, heads[0].clone(), weights.clone()),
                cpu_request(2, heads[1].clone(), weights),
            ],
        ),
        Err(Error::ModelCapacity),
    );
    assert_eq!(worker.driver.backend_batch_invocations, 0);
    assert!(!worker.requires_external_recovery());

    worker.grant.maximum_memory_bytes = 1_000_000;
    let retry_weights = worker.driver.manifest.weights_digest.clone();
    let accepted = worker
        .run_neuron_features_backend_batch(
            100,
            "model.cpu-head",
            vec![
                cpu_request(1, heads[0].clone(), retry_weights.clone()),
                cpu_request(2, heads[1].clone(), retry_weights),
            ],
        )
        .expect("budgeted retry without previous physical dispatch");
    assert_eq!(accepted.receipts.len(), 2);
    assert_eq!(worker.driver.backend_batch_invocations, 1);
    assert!(!worker.requires_external_recovery());
}


#[test]
fn cpu_head_batch_preflight_covers_reported_numeric_peak_for_four_cells() {
    let (mut worker, heads) = local_worker();
    let weights = worker.driver.manifest.weights_digest.clone();
    let mut requests = Vec::new();
    for index in 0..4 {
        requests.push(cpu_request(
            index + 1,
            heads[index % 2].clone(),
            weights.clone(),
        ));
    }
    let planned = worker
        .driver
        .preflight_neuron_backend_batch_bytes(
            &worker.models.get("model.cpu-head").expect("loaded").handle,
            &requests,
        )
        .expect("checked numeric memory plan");
    let received = worker
        .run_neuron_features_backend_batch(100, "model.cpu-head", requests)
        .expect("one grouped CPU Head call");
    assert!(received.observed_peak_memory_bytes <= planned);
    assert_eq!(received.receipts.len(), 4);
    assert!(!received.receipts.iter().any(|r| r.authority.grants_any()));
}
