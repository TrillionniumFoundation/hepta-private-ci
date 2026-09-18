use super::*;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::thread;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde_json::Value;
use serde_json::json;

struct Fixture {
    root: PathBuf,
    socket: PathBuf,
    artifacts: LocalModelArtifacts,
    manifest: ModelManifest,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.socket);
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn fixture(label: &str) -> Fixture {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::temp_dir().join(format!("hepta-local-driver-{label}-{nonce}"));
    fs::create_dir_all(&root).unwrap();
    let write = |name: &str, content: &[u8]| {
        let path = root.join(name);
        fs::write(&path, content).unwrap();
        path
    };
    let weights_path = write("weights.bin", b"weights-v1");
    let tokenizer_path = write("tokenizer.json", b"tokenizer-v1");
    let preprocessor_path = write("preprocessor.json", b"preprocessor-v1");
    let quantization_path = write("quantization.json", b"quantization-v1");
    let runtime_path = write("runtime.bin", b"runtime-v1");
    let device_descriptor_path = write("device.json", b"device-v1");
    let isolation_receipt_path = write("isolation.json", b"isolation-v1");
    let manifest = ModelManifest {
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: sha256_hex(b"weights-v1"),
        tokenizer_digest: sha256_hex(b"tokenizer-v1"),
        preprocessor_digest: sha256_hex(b"preprocessor-v1"),
        quantization_digest: sha256_hex(b"quantization-v1"),
        runtime_digest: sha256_hex(b"runtime-v1"),
        device_digest: sha256_hex(b"device-v1"),
        isolation_digest: sha256_hex(b"isolation-v1"),
        maximum_tokens: 128,
    };
    Fixture {
        socket: root.join("runtime.sock"),
        artifacts: LocalModelArtifacts {
            weights_path,
            tokenizer_path,
            preprocessor_path,
            quantization_path,
            runtime_path,
            device_descriptor_path,
            isolation_receipt_path,
        },
        root,
        manifest,
    }
}

fn grant() -> ResourceGrant {
    ResourceGrant {
        grant_id: "grant.1".to_string(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: u64::MAX,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 4096,
        semantic_digest: "2".repeat(64),
    }
}

fn request(manifest: &ModelManifest) -> WorkerRequest {
    let prompt = "real local input".to_string();
    let payload_digest = sha256_hex(prompt.as_bytes());
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: manifest.model_digest.clone(),
        payload_digest: payload_digest.clone(),
        prompt,
        maximum_tokens: 32,
        deadline_ms: u64::MAX,
        lease_payload_digest: payload_digest,
        reservation_model_digest: manifest.model_digest.clone(),
        reservation_maximum_tokens: 32,
        cancelled: false,
    }
}

#[test]
fn verifies_artifacts_and_round_trips_load_infer_unload() {
    let fixture = fixture("roundtrip");
    let listener = UnixListener::bind(&fixture.socket).unwrap();
    fs::set_permissions(&fixture.socket, fs::Permissions::from_mode(0o600)).unwrap();
    let manifest = fixture.manifest.clone();
    let server_manifest = manifest.clone();
    let server = thread::spawn(move || {
        for expected_op in ["load", "infer", "unload"] {
            let (stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream);
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            assert_eq!(request["protocol"], PROTOCOL);
            assert_eq!(request["op"], expected_op);
            let response = match expected_op {
                "load" => {
                    assert_eq!(request["grant"]["maximum_memory_bytes"], 4096);
                    json!({
                        "protocol": PROTOCOL,
                        "ok": true,
                        "error": null,
                        "handle_id": "loaded.model.1",
                        "observed_memory_bytes": 1024,
                        "model_digest": server_manifest.model_digest.clone(),
                        "weights_digest": server_manifest.weights_digest.clone(),
                        "tokenizer_digest": server_manifest.tokenizer_digest.clone(),
                        "preprocessor_digest": server_manifest.preprocessor_digest.clone(),
                        "quantization_digest": server_manifest.quantization_digest.clone(),
                        "runtime_digest": server_manifest.runtime_digest.clone(),
                        "device_digest": server_manifest.device_digest.clone(),
                        "isolation_digest": server_manifest.isolation_digest.clone()
                    })
                }
                "infer" => {
                    assert_eq!(request["request"]["prompt"], "real local input");
                    json!({
                        "protocol": PROTOCOL,
                        "ok": true,
                        "error": null,
                        "terminal_observed": true,
                        "succeeded": true,
                        "output": "local answer",
                        "consumed_tokens": 7,
                        "observed_memory_bytes": 1024
                    })
                }
                "unload" => json!({
                    "protocol": PROTOCOL,
                    "ok": true,
                    "error": null
                }),
                _ => unreachable!(),
            };
            let mut stream = reader.into_inner();
            writeln!(stream, "{}", serde_json::to_string(&response).unwrap()).unwrap();
        }
    });

    let mut driver = LocalProcessDriver::single_model(
        fixture.socket.clone(),
        manifest.model_id.clone(),
        fixture.artifacts.clone(),
        Duration::from_secs(2),
    )
    .unwrap();
    let resource_grant = grant();
    let handle = driver.load(&manifest, &resource_grant).unwrap();
    assert_eq!(handle.opaque_id, "loaded.model.1");
    let observation = driver
        .run(&handle, &request(&manifest), &resource_grant)
        .unwrap();
    assert!(observation.terminal_observed);
    assert!(observation.succeeded);
    assert_eq!(observation.consumed_tokens, 7);
    assert_eq!(observation.output_digest, Some(sha256_hex(b"local answer")));
    driver.unload(handle).unwrap();
    server.join().unwrap();
}

#[test]
fn artifact_drift_fails_before_runtime_connection() {
    let fixture = fixture("drift");
    fs::write(&fixture.artifacts.weights_path, b"changed weights").unwrap();
    let mut driver = LocalProcessDriver::single_model(
        fixture.socket.clone(),
        fixture.manifest.model_id.clone(),
        fixture.artifacts.clone(),
        Duration::from_secs(1),
    )
    .unwrap();
    assert!(matches!(
        driver.load(&fixture.manifest, &grant()),
        Err(Error::DriverFailure(message)) if message.contains("weights digest mismatch")
    ));
}

#[test]
fn group_or_world_accessible_runtime_socket_is_rejected() {
    let fixture = fixture("socket-mode");
    let _listener = UnixListener::bind(&fixture.socket).unwrap();
    fs::set_permissions(&fixture.socket, fs::Permissions::from_mode(0o666)).unwrap();
    let mut driver = LocalProcessDriver::single_model(
        fixture.socket.clone(),
        fixture.manifest.model_id.clone(),
        fixture.artifacts.clone(),
        Duration::from_secs(1),
    )
    .unwrap();
    assert!(matches!(
        driver.load(&fixture.manifest, &grant()),
        Err(Error::DriverFailure(message)) if message.contains("accessible by group or world")
    ));
}
