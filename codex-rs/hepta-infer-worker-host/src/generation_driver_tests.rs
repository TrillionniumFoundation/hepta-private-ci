use super::*;
use codex_hepta_infer_core::GENERATION_SCHEMA;

fn fixture() -> (
    tempfile::TempDir,
    GenerationRegistrationV1,
    GenerationRequestV1,
) {
    let root = tempfile::tempdir().expect("temporary registration");
    let source = root.path().join(SOURCE_DIR);
    std::fs::create_dir_all(&source).expect("source directory");
    for name in SOURCES {
        std::fs::write(source.join(name), name).expect("source fixture");
    }
    let python = root.path().join("registered-python");
    std::fs::write(&python, b"registered runtime fixture; never executed")
        .expect("runtime fixture");
    std::fs::write(
        root.path().join("model.pt"),
        b"registered checkpoint fixture",
    )
    .expect("checkpoint fixture");
    let pins = GenerationModelPinsV1 {
        checkpoint_sha256: Digest32::of_bytes(b"registered checkpoint fixture").to_string(),
        snapshot_sha256: "1".repeat(64),
        parameters_sha256: "1".repeat(64),
        config_sha256: "2".repeat(64),
        source_sha256: generation_source_digest(root.path()).expect("source digest"),
        python_sha256: Digest32::of_bytes(b"registered runtime fixture; never executed")
            .to_string(),
        device_sha256: "8".repeat(64),
        runtime_versions: ["p".into(), "t".into(), "n".into(), "i".into()],
        hidden: 16,
    };
    let request = GenerationRequestV1 {
        schema: GENERATION_SCHEMA.into(),
        request_id: "request.fixture".into(),
        objective_sha256: "3".repeat(64),
        input_source_sha256: "4".repeat(64),
        model: pins.clone(),
        required_modalities: 3,
        pixels_f32: vec![0; 28 * 56],
        mask_f32: vec![0; 28 * 56],
        text_tokens: vec![1; 8],
        noise_seed: 0,
        content_control: true,
        actions: Vec::new(),
    };
    let registration = GenerationRegistrationV1 {
        repository: root.path().to_path_buf(),
        python,
        artifact_root: root.path().to_path_buf(),
        checkpoint_name: "model.pt".into(),
        model_id: "fixture.model".into(),
        pins,
        timeout: Duration::from_secs(1),
    };
    (root, registration, request)
}

#[test]
fn registered_manifest_and_source_substitution_fail_before_execution() {
    let (root, registration, request) = fixture();
    let mut driver = GenerationDriver::new(registration, vec![request]).expect("registration");
    let mut manifest = driver.manifest().expect("manifest");
    manifest.weights_digest = "e".repeat(64);
    assert_eq!(driver.load(&manifest), Err(Error::ModelMismatch));
    manifest = driver.manifest().expect("exact manifest");
    assert!(driver.load(&manifest).is_ok());
    std::fs::write(root.path().join(SOURCE_DIR).join("neural.py"), b"changed")
        .expect("substitution");
    assert!(driver.load(&manifest).is_err());
}

#[test]
fn traversal_and_unregistered_snapshot_pins_reject_before_execution() {
    let (_root, mut registration, request) = fixture();
    registration.checkpoint_name = "../model.pt".into();
    assert!(GenerationDriver::new(registration, vec![request]).is_err());
    let (_root, registration, mut request) = fixture();
    request.model.snapshot_sha256 = "f".repeat(64);
    assert!(GenerationDriver::new(registration, vec![request]).is_err());
}

#[test]
fn insufficient_token_limits_reject_before_starting_a_process() {
    let (_root, registration, request) = fixture();
    let payload = generation_json_digest(&request).expect("payload");
    let request_id = request.request_id.clone();
    let mut driver = GenerationDriver::new(registration, vec![request]).expect("registration");
    let manifest = driver.manifest().expect("manifest");
    let handle = driver.load(&manifest).expect("registration load");
    let evidence = driver.evidence();
    for limit in 1..8 {
        for (maximum_tokens, reservation_maximum_tokens) in [(limit, 8), (8, limit)] {
            let request = WorkerRequest {
                request_id: request_id.clone(),
                reservation_id: "test.reservation".into(),
                model_digest: manifest.model_digest.clone(),
                payload_digest: payload.clone(),
                maximum_tokens,
                deadline_ms: 90_000,
                lease_payload_digest: payload.clone(),
                reservation_model_digest: manifest.model_digest.clone(),
                reservation_maximum_tokens,
                cancelled: false,
            };
            assert_eq!(driver.run(&handle, &request), Err(Error::TokenLimit));
            assert_eq!(evidence.get(&payload), None);
        }
    }
}
