use super::*;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ResourceGrant;
use crate::model_worker::canonical_neuron_feature_payload_digest;
use tempfile::TempDir;

fn manifest() -> ModelManifest {
    ModelManifest {
        model_id: "laya.retrieval-continuation-v1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_digest: "7".repeat(64),
        maximum_tokens: 512,
    }
}
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}
fn fixture(mode: &str) -> (TempDir, LayaCellDriver) {
    let root = tempfile::tempdir().unwrap();
    let ready = serde_json::json!({"manifest": manifest(),
        "encoder_digest": "8".repeat(64), "head_digest": "9".repeat(64), "memory_bytes": 1024});
    let script = format!(
        "import json,sys,time\nmode={mode:?}\nready={:?}\nprint(ready,flush=True)\nfor line in sys.stdin:\n r=json.loads(line)\n if mode=='slow': time.sleep(5)\n if mode=='oversize': print('x'*17000,flush=True);continue\n rid='wrong' if mode=='wrong' else r['request_id']\n print(json.dumps(dict(request_id=rid,prediction_q24=[8388608,8388608],memory_bytes=2048,latency_micros=10)),flush=True)\n",
        ready.to_string()
    );
    let backend = root.path().join("backend.py");
    std::fs::write(&backend, &script).unwrap();
    let driver = LayaCellDriver::new(LayaCellConfig {
        python: PathBuf::from("/usr/bin/python3"),
        backend,
        model: root.path().to_path_buf(),
        candidate: None,
        base_sha256: "a".repeat(64),
        backend_sha256: format!("{:x}", Sha256::digest(script.as_bytes())),
        load_timeout: Duration::from_secs(5),
        stop_timeout: Duration::from_secs(2),
        cancel: Arc::new(AtomicBool::new(false)),
    })
    .unwrap();
    (root, driver)
}
fn request(deadline_ms: u64) -> NeuronFeatureRequest {
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "cell-request".to_string(),
            reservation_id: "reservation".to_string(),
            model_digest: "1".repeat(64),
            payload_digest: "a".repeat(64),
            maximum_tokens: 512,
            deadline_ms,
            lease_payload_digest: "a".repeat(64),
            reservation_model_digest: "1".repeat(64),
            reservation_maximum_tokens: 512,
            cancelled: false,
        },
        encoder_digest: "8".repeat(64),
        head_digest: "9".repeat(64),
        weights_digest: "2".repeat(64),
        input_digest: "b".repeat(64),
        feature_vector_q24: vec![Q24 / 2; 4],
        expected_output_width: 2,
    };
    let payload = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;
    request
}
#[test]
fn local_backend_prediction_is_request_bound_and_non_authorizing() {
    let (_root, mut driver) = fixture("valid");
    let handle = driver.load(&manifest()).unwrap();
    let output = driver
        .run_neuron_features(&handle, &request(now_ms() + 5000))
        .unwrap();
    assert_eq!(output.prediction_q24, vec![Q24 / 2, Q24 / 2]);
    assert!(output.terminal_observed && output.succeeded);
    assert!(output.latency_micros > 0);
    driver.unload(handle).unwrap();
    assert!(driver.process.is_none());
}
#[test]
fn bad_response_or_oversized_frame_stops_the_model_without_success() {
    for mode in ["wrong", "oversize"] {
        let (_root, mut driver) = fixture(mode);
        let handle = driver.load(&manifest()).unwrap();
        assert!(
            driver
                .run_neuron_features(&handle, &request(now_ms() + 5000))
                .is_err()
        );
        assert!(driver.process.is_none());
    }
}
#[test]
fn deadline_and_live_cancellation_stop_the_child() {
    for cancelled in [false, true] {
        let (_root, mut driver) = fixture("slow");
        let handle = driver.load(&manifest()).unwrap();
        let token = Arc::clone(&driver.config.cancel);
        let thread = std::thread::spawn(move || {
            if cancelled {
                std::thread::sleep(Duration::from_millis(50));
                token.store(true, Ordering::Release);
            }
        });
        let started = Instant::now();
        assert!(
            driver
                .run_neuron_features(&handle, &request(now_ms() + 150))
                .is_err()
        );
        assert!(started.elapsed() < Duration::from_secs(3));
        assert!(driver.process.is_none());
        thread.join().unwrap();
    }
}
#[test]
fn unpinned_backend_or_changed_manifest_rejects_loading() {
    let (_root, mut driver) = fixture("valid");
    driver.config.backend_sha256 = "f".repeat(64);
    assert!(matches!(
        driver.load(&manifest()),
        Err(Error::InvalidManifest)
    ));
    assert!(driver.process.is_none());
    let (_root, mut driver) = fixture("valid");
    let mut changed = manifest();
    changed.weights_digest = "e".repeat(64);
    assert!(matches!(driver.load(&changed), Err(Error::ModelMismatch)));
    assert!(driver.process.is_none());
}
fn worker(driver: LayaCellDriver) -> InferenceWorker<LayaCellDriver> {
    let now = now_ms();
    InferenceWorker::new(
        now,
        "local-cell-worker".to_string(),
        1,
        ResourceGrant {
            grant_id: "local-test-grant".to_string(),
            authority_epoch: 1,
            generation: 1,
            expires_at_ms: now + 300_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
            semantic_digest: "a".repeat(64),
        },
        driver,
    )
    .unwrap()
}
#[test]
fn existing_worker_checks_payload_and_builds_authority_free_receipt() {
    let (_root, driver) = fixture("valid");
    let mut worker = worker(driver);
    worker.load_model(now_ms(), manifest()).unwrap();
    let mut changed = request(now_ms() + 5000);
    changed.feature_vector_q24[0] += 1;
    assert!(matches!(
        worker.run_neuron_features_receipt(now_ms(), &manifest().model_id, changed),
        Err(Error::PayloadMismatch)
    ));
    let receipt = worker
        .run_neuron_features_receipt(now_ms(), &manifest().model_id, request(now_ms() + 5000))
        .unwrap();
    assert!(!receipt.authority.grants_any());
    assert_eq!(receipt.prediction_q24, vec![Q24 / 2, Q24 / 2]);
    worker.unload_model(now_ms(), &manifest().model_id).unwrap();
}
#[test]
#[ignore = "requires an explicitly pinned local Laya model and Python runtime"]
fn actual_pinned_laya_runs_through_existing_worker() {
    let path = |key: &str| PathBuf::from(std::env::var_os(key).expect(key));
    let backend = path("HEPTA_LAYA_BACKEND");
    let ready: Ready =
        serde_json::from_slice(&std::fs::read(path("HEPTA_LAYA_MANIFEST")).unwrap()).unwrap();
    let driver = LayaCellDriver::new(LayaCellConfig {
        python: path("HEPTA_LAYA_PYTHON"),
        backend: backend.clone(),
        model: path("HEPTA_LAYA_MODEL"),
        candidate: std::env::var_os("HEPTA_LAYA_CANDIDATE").map(PathBuf::from),
        base_sha256: "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204".to_string(),
        backend_sha256: format!("{:x}", Sha256::digest(std::fs::read(backend).unwrap())),
        load_timeout: Duration::from_secs(180),
        stop_timeout: Duration::from_secs(3),
        cancel: Arc::new(AtomicBool::new(false)),
    })
    .unwrap();
    let mut worker = worker(driver);
    worker.load_model(now_ms(), ready.manifest.clone()).unwrap();
    let mut reports = Vec::new();
    for (index, features) in [vec![0, Q24, Q24, Q24], vec![Q24, 0, 0, Q24]]
        .into_iter()
        .enumerate()
    {
        let mut input = request(now_ms() + 120_000);
        input.authorization.request_id = format!("real-laya-{index}");
        input.authorization.model_digest = ready.manifest.model_digest.clone();
        input.authorization.reservation_model_digest = ready.manifest.model_digest.clone();
        input.encoder_digest = ready.encoder_digest.clone();
        input.head_digest = ready.head_digest.clone();
        input.weights_digest = ready.manifest.weights_digest.clone();
        input.feature_vector_q24 = features;
        input.input_digest = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&input.feature_vector_q24).unwrap())
        );
        let payload = canonical_neuron_feature_payload_digest(&input);
        input.authorization.payload_digest = payload.clone();
        input.authorization.lease_payload_digest = payload;
        let receipt = worker
            .run_neuron_features_receipt(now_ms(), &ready.manifest.model_id, input)
            .unwrap();
        assert!(!receipt.authority.grants_any());
        assert_eq!(receipt.prediction_q24.iter().sum::<i64>(), Q24);
        reports.push(serde_json::json!({
            "request_digest": receipt.request_digest.to_string(),
            "receipt_digest": receipt.receipt_digest.to_string(),
            "prediction_q24": receipt.prediction_q24,
            "memory_bytes": receipt.observed_memory_bytes,
            "latency_micros": receipt.latency_micros,
            "weights_digest": receipt.runtime_tuple.weights_digest.to_string(),
            "authority_granted": false,
        }));
    }
    assert_ne!(reports[0]["request_digest"], reports[1]["request_digest"]);
    assert_ne!(reports[0]["prediction_q24"], reports[1]["prediction_q24"]);
    worker
        .unload_model(now_ms(), &ready.manifest.model_id)
        .unwrap();
    let report = serde_json::json!({"qualification_only": true, "rows": reports});
    if let Some(path) = std::env::var_os("HEPTA_LAYA_REPORT") {
        std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    }
    println!("{report}");
}
