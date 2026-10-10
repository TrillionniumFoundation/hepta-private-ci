use super::*;
use crate::model_worker::canonical_neuron_feature_payload_digest;

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn fixture() -> (CpuNeuronFeatureDriverV1, ModelManifest) {
    let q = 1_i64 << 24;
    let bundle = CpuNeuronWeightBundleV1::new(
        2,
        2,
        vec![q, 0, 0, q],
        vec![0, q, q, 0],
        digest(b"approved.encoder"),
        digest(b"approved.head"),
    )
    .unwrap();
    let manifest = ModelManifest {
        model_id: "approved-model".into(),
        model_digest: digest(b"approved.model").to_string(),
        weights_digest: bundle.weight_digest().to_string(),
        tokenizer_digest: digest(b"tokenizer").to_string(),
        preprocessor_digest: digest(b"preprocessor").to_string(),
        quantization_digest: digest(b"quant.q24").to_string(),
        runtime_digest: digest(b"runtime.cpu.native").to_string(),
        device_digest: digest(b"device.cpu").to_string(),
        maximum_tokens: 128,
    };
    let backend = CpuNeuronFeatureDriverV1::new(
        bundle,
        digest(b"approved.model"),
        digest(b"runtime.cpu.native"),
        digest(b"quant.q24"),
        digest(b"device.cpu"),
    )
    .unwrap();
    (backend, manifest)
}

fn request(manifest: &ModelManifest, id: &str, values: [i64; 2]) -> NeuronFeatureRequest {
    let mut feature = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: id.into(),
            reservation_id: format!("reservation-{id}"),
            model_digest: manifest.model_digest.clone(),
            payload_digest: String::new(),
            maximum_tokens: 2,
            deadline_ms: 9000,
            lease_payload_digest: String::new(),
            reservation_model_digest: manifest.model_digest.clone(),
            reservation_maximum_tokens: 2,
            cancelled: false,
        },
        encoder_digest: digest(b"approved.encoder").to_string(),
        head_digest: digest(b"approved.head").to_string(),
        weights_digest: manifest.weights_digest.clone(),
        input_digest: digest(id.as_bytes()).to_string(),
        feature_vector_q24: values.to_vec(),
        expected_output_width: 2,
    };
    let canonical = canonical_neuron_feature_payload_digest(&feature);
    feature.authorization.payload_digest = canonical.clone();
    feature.authorization.lease_payload_digest = canonical;
    feature
}

#[test]
fn native_cpu_batch_uses_one_matrix_pass_and_preserves_request_order() {
    let (mut driver, manifest) = fixture();
    let handle = driver.load(&manifest).unwrap();
    let q = 1_i64 << 24;
    let requests = [
        request(&manifest, "first", [q, q / 2]),
        request(&manifest, "second", [-q / 2, q]),
    ];
    let observed = driver
        .run_neuron_features_batch(&handle, &requests)
        .unwrap();
    assert_eq!(observed.len(), 2);
    assert_eq!(observed[0].request_id, "first");
    assert_eq!(observed[1].request_id, "second");
    assert_eq!(observed[0].observation.drive_q24, vec![q, q / 2]);
    assert_eq!(observed[1].observation.drive_q24, vec![-q / 2, q]);
    assert_eq!(observed[0].observation.prediction_q24, vec![q / 2, q]);
    assert_eq!(observed[1].observation.prediction_q24, vec![q, -q / 2]);
    assert_eq!(driver.native_batch_counters(), (1, 2));
    let single = driver.run_neuron_features(&handle, &requests[0]).unwrap();
    assert_eq!(single.drive_q24, observed[0].observation.drive_q24);
    assert_eq!(driver.native_batch_counters(), (1, 2));
}

#[test]
fn contiguous_native_batch_matches_single_results_for_odd_and_large_cohorts() {
    let (mut driver, manifest) = fixture();
    let handle = driver.load(&manifest).expect("load pinned model");
    let q = 1_i64 << 24;
    for cohort in [3_usize, 127, 256] {
        let requests = (0..cohort)
            .map(|i| {
                let i = i as i64;
                request(
                    &manifest,
                    &format!("cohort-{cohort}-{i}"),
                    [((i % 17) - 8) * (q / 8), ((i % 11) - 5) * (q / 8)],
                )
            })
            .collect::<Vec<_>>();
        let batched = driver
            .run_neuron_features_batch(&handle, &requests)
            .expect("single physical native batch");
        assert_eq!(batched.len(), cohort);
        for (request, observed) in requests.iter().zip(&batched) {
            assert_eq!(observed.request_id, request.authorization.request_id);
            assert_eq!(observed.input_digest, request.input_digest);
            let single = driver
                .run_neuron_features(&handle, request)
                .expect("same pinned backend for scalar oracle");
            assert_eq!(observed.observation.drive_q24, single.drive_q24);
            assert_eq!(observed.observation.prediction_q24, single.prediction_q24);
            assert_eq!(
                observed.observation.transient_allocation_bytes,
                (cohort * 2 * 2 * std::mem::size_of::<i128>()) as u64
            );
        }
    }
    assert_eq!(driver.native_batch_counters(), (3, 3 + 127 + 256));
}

#[test]
fn backend_rejects_unpinned_model_and_incompatible_batch_before_any_call() {
    let (mut driver, mut manifest) = fixture();
    let correct = manifest.clone();
    manifest.weights_digest = digest(b"untrusted.weights").to_string();
    assert!(matches!(driver.load(&manifest), Err(Error::ModelMismatch)));
    let handle = driver.load(&correct).unwrap();
    let q = 1_i64 << 24;
    let valid = request(&correct, "first", [q, 0]);
    let mut wrong = request(&correct, "second", [0, q]);
    wrong.head_digest = digest(b"unknown.head").to_string();
    assert!(matches!(
        driver.run_neuron_features_batch(&handle, &[valid.clone(), wrong]),
        Err(Error::FeatureContract)
    ));
    assert_eq!(driver.native_batch_counters(), (0, 0));
    assert!(matches!(
        driver.run_neuron_features(
            &DriverModelHandle {
                opaque_id: "other".into(),
                observed_memory_bytes: 0,
            },
            &valid
        ),
        Err(Error::ModelNotLoaded)
    ));
    driver.unload(handle).unwrap();
}

#[test]
fn q24_ties_to_even_and_output_bounds_are_explicit() {
    let half = 1_i128 << 23;
    let full = 1_i128 << 24;
    assert_eq!(round_q48_to_q24(half).unwrap(), 0);
    assert_eq!(round_q48_to_q24(full + half).unwrap(), 2);
    assert_eq!(round_q48_to_q24(-half).unwrap(), 0);
    assert_eq!(round_q48_to_q24(-full - half).unwrap(), -2);
    assert!(matches!(
        round_q48_to_q24((i128::from(MAX_Q24) + 1) * Q24),
        Err(Error::FeatureOutputMismatch)
    ));
}

#[test]
fn no_synthetic_or_generic_turn_execution_is_exposed() {
    let (mut driver, manifest) = fixture();
    let handle = driver.load(&manifest).unwrap();
    let request = WorkerRequest {
        request_id: "generic".into(),
        reservation_id: "r".into(),
        model_digest: manifest.model_digest.clone(),
        payload_digest: digest(b"payload").to_string(),
        maximum_tokens: 1,
        deadline_ms: 9000,
        lease_payload_digest: digest(b"payload").to_string(),
        reservation_model_digest: manifest.model_digest.clone(),
        reservation_maximum_tokens: 1,
        cancelled: false,
    };
    assert!(matches!(
        driver.run(&handle, &request),
        Err(Error::DriverFailure(_))
    ));
}
