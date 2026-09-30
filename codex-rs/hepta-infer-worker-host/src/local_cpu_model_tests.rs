use super::*;

fn installed_model() -> (
    tempfile::TempDir,
    std::path::PathBuf,
    Digest32,
    String,
    String,
) {
    let directory = tempfile::tempdir().expect("test model directory");
    let mut weights = b"HPTNCPU1".to_vec();
    for dimension in [2_u16, 2, 1] {
        weights.extend_from_slice(&dimension.to_be_bytes());
    }
    for value in [
        Q24,
        0,
        0,
        0,
        Q24,
        0,
        Q24 / 2,
        Q24 / 4,
        Q24 / 8,
        -Q24 / 4,
        Q24 / 2,
        -Q24 / 8,
    ] {
        weights.extend_from_slice(&value.to_be_bytes());
    }
    let encoder = Digest32::of_bytes(&weights[14..62]).to_string();
    let head = Digest32::of_bytes(&weights[62..]).to_string();
    let descriptor = CpuNeuronManifestV1 {
        version: 1,
        model_id: "test.learned-cpu-head".into(),
        weights_filename: "weights.bin".into(),
        weights_digest: Digest32::of_bytes(&weights).to_string(),
        encoder_digest: encoder.clone(),
        head_digest: head.clone(),
        tokenizer_digest: Digest32::of_bytes(CPU_NEURON_TOKENIZER_PROFILE_V1).to_string(),
        preprocessor_digest: Digest32::of_bytes(CPU_NEURON_PREPROCESSOR_PROFILE_V1).to_string(),
        quantization_digest: Digest32::of_bytes(CPU_NEURON_QUANTIZATION_PROFILE_V1).to_string(),
        runtime_digest: Digest32::of_bytes(CPU_NEURON_RUNTIME_PROFILE_V1).to_string(),
        device_digest: cpu_neuron_device_digest_v1()
            .expect("actual CPU identity")
            .to_string(),
        maximum_tokens: 32,
    };
    let bytes = serde_json::to_vec(&descriptor).expect("manifest encode");
    let path = directory.path().join("manifest.json");
    std::fs::write(&path, &bytes).expect("manifest write");
    std::fs::write(directory.path().join("weights.bin"), &weights).expect("weights write");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for file in [&path, &directory.path().join("weights.bin")] {
            std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o600))
                .expect("immutable input access");
        }
    }
    (directory, path, Digest32::of_bytes(&bytes), encoder, head)
}

#[test]
fn installed_dense_weights_execute_both_heads_and_unload_releases_the_model() {
    let (_directory, path, pin, encoder, head) = installed_model();
    let mut driver = CpuNeuronModelDriver::open(&path, pin).expect("pinned immutable weights");
    let manifest = driver.manifest().clone();
    let handle = driver.load(&manifest).expect("exact selected manifest");
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "test.request".into(),
            reservation_id: "test.reservation".into(),
            model_digest: manifest.model_digest.clone(),
            payload_digest: pin.to_string(),
            maximum_tokens: 32,
            deadline_ms: 100,
            lease_payload_digest: pin.to_string(),
            reservation_model_digest: manifest.model_digest,
            reservation_maximum_tokens: 32,
            cancelled: false,
        },
        encoder_digest: encoder.clone(),
        head_digest: head.clone(),
        weights_digest: manifest.weights_digest,
        input_digest: pin.to_string(),
        feature_vector_q24: vec![2 * Q24, 4 * Q24],
        expected_output_width: 1,
    };
    let observed = driver
        .run_neuron_features(&handle, &request)
        .expect("physical dense execution");
    assert_eq!(
        (observed.drive_q24, observed.prediction_q24),
        (vec![17 * Q24 / 8], vec![11 * Q24 / 8])
    );
    assert_eq!(
        (observed.encoder_digest, observed.head_digest),
        (encoder, head)
    );
    assert!(observed.terminal_observed && observed.succeeded);
    request.feature_vector_q24 = vec![-Q24, 2 * Q24];
    let observed = driver
        .run_neuron_features(&handle, &request)
        .expect("new feature execution");
    assert_eq!(
        (observed.drive_q24, observed.prediction_q24),
        (vec![5 * Q24 / 8], vec![7 * Q24 / 8])
    );
    driver
        .unload(handle.clone())
        .expect("release actual weights");
    assert!(driver.weights.is_none());
    assert!(matches!(
        driver.run_neuron_features(&handle, &request),
        Err(Error::ModelNotLoaded)
    ));
}

#[test]
fn changed_payload_and_backend_tuple_do_not_load_as_the_installed_model() {
    let (directory, path, pin, _, _) = installed_model();
    let mut payload = std::fs::read(directory.path().join("weights.bin")).expect("payload");
    payload[20] ^= 1;
    std::fs::write(directory.path().join("weights.bin"), payload).expect("changed bytes");
    assert!(matches!(
        CpuNeuronModelDriver::open(&path, pin),
        Err(Error::ModelMismatch)
    ));
    let (_second_directory, path, _, _, _) = installed_model();
    let mut descriptor: CpuNeuronManifestV1 =
        serde_json::from_slice(&std::fs::read(&path).expect("descriptor")).expect("manifest");
    descriptor.runtime_digest = Digest32::of_bytes(b"different runtime").to_string();
    let bytes = serde_json::to_vec(&descriptor).expect("encode changed tuple");
    std::fs::write(&path, &bytes).expect("changed manifest");
    assert!(matches!(
        CpuNeuronModelDriver::open(&path, Digest32::of_bytes(&bytes)),
        Err(Error::InvalidManifest)
    ));
}

#[test]
fn signed_q24_rounding_uses_nearest_even_in_both_directions_and_saturates() {
    assert_eq!(
        dense(&[1, 0], &[Q24 / 2], /*width*/ 1).expect("even zero"),
        vec![0]
    );
    assert_eq!(
        dense(&[3, 0], &[Q24 / 2], /*width*/ 1).expect("odd upward"),
        vec![2]
    );
    assert_eq!(
        dense(&[-3, 0], &[Q24 / 2], /*width*/ 1).expect("odd downward"),
        vec![-2]
    );
    assert_eq!(
        dense(&[LIMIT, LIMIT], &[LIMIT], /*width*/ 1).expect("saturation"),
        vec![LIMIT]
    );
}
