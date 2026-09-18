#![cfg(unix)]

use super::*;
use crate::model_worker::ExecutionStatus;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::VerifiedResourceGrant;
use crate::model_worker::WorkerRequest;
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct Fixture {
    root: PathBuf,
    runtime: PathBuf,
    artifacts: LocalModelArtifacts,
    manifest: ModelManifest,
}

impl Fixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-local-runtime-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();

        let runtime = root.join("runtime.py");
        fs::write(
            &runtime,
            r#"#!/usr/bin/env python3
import json
import sys

PROTOCOL = "hepta.local-model-driver.v1"
handle = "local.handle.1"

for line in sys.stdin:
    request = json.loads(line)
    op = request.get("op")
    if op == "load":
        model = request["model"]
        grant = request["grant"]
        response = {
            "protocol": PROTOCOL,
            "op": "loaded",
            "model_id": model["model_id"],
            "model_digest": model["model_digest"],
            "runtime_digest": model["runtime_digest"],
            "device_digest": model["device_digest"],
            "handle_id": handle,
            "reserved_memory_bytes": min(2048, grant["maximum_memory_bytes"]),
            "observed_memory_bytes": 1024,
        }
        print(json.dumps(response), flush=True)
    elif op == "run":
        response = {
            "protocol": PROTOCOL,
            "op": "run_result",
            "handle_id": handle,
            "request_id": request["request_id"],
            "terminal_observed": True,
            "succeeded": True,
            "output": "local:" + request["input"],
            "consumed_tokens": 3,
            "observed_memory_bytes": 1280,
        }
        print(json.dumps(response), flush=True)
    elif op == "unload":
        response = {
            "protocol": PROTOCOL,
            "op": "unloaded",
            "handle_id": handle,
        }
        print(json.dumps(response), flush=True)
        sys.exit(0)
    else:
        sys.exit(64)
"#,
        )
        .unwrap();
        let mut permissions = fs::metadata(&runtime).unwrap().permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(&runtime, permissions).unwrap();

        let weights_path = root.join("weights.bin");
        let tokenizer_path = root.join("tokenizer.json");
        let preprocessor_path = root.join("preprocessor.json");
        let quantization_path = root.join("quantization.json");
        let device_descriptor_path = root.join("device.json");
        fs::write(&weights_path, b"real-test-weights").unwrap();
        fs::write(&tokenizer_path, br#"{"tokenizer":"fixture"}"#).unwrap();
        fs::write(&preprocessor_path, br#"{"preprocessor":"fixture"}"#).unwrap();
        fs::write(&quantization_path, br#"{"quantization":"fixture"}"#).unwrap();
        fs::write(
            &device_descriptor_path,
            br#"{"device":"cpu","isolation":"test-only"}"#,
        )
        .unwrap();

        let artifacts = LocalModelArtifacts {
            weights_path: weights_path.clone(),
            tokenizer_path: tokenizer_path.clone(),
            preprocessor_path: preprocessor_path.clone(),
            quantization_path: quantization_path.clone(),
            device_descriptor_path: device_descriptor_path.clone(),
        };
        let manifest = ModelManifest {
            model_id: "model.local.1".to_string(),
            model_digest: "1".repeat(64),
            weights_digest: sha256_file(&weights_path).unwrap(),
            tokenizer_digest: sha256_file(&tokenizer_path).unwrap(),
            preprocessor_digest: sha256_file(&preprocessor_path).unwrap(),
            quantization_digest: sha256_file(&quantization_path).unwrap(),
            runtime_digest: sha256_file(&runtime).unwrap(),
            device_digest: sha256_file(&device_descriptor_path).unwrap(),
            maximum_tokens: 128,
        };
        Self {
            root,
            runtime,
            artifacts,
            manifest,
        }
    }

    fn driver(&self) -> LocalProcessDriver {
        let mut models = BTreeMap::new();
        models.insert(self.manifest.model_id.clone(), self.artifacts.clone());
        LocalProcessDriver::new(LocalProcessDriverConfig::new(
            self.runtime.clone(),
            models,
        ))
        .unwrap()
    }

    fn grant(&self) -> ResourceGrant {
        ResourceGrant {
            grant_id: "grant.local.1".to_string(),
            authority_epoch: 7,
            generation: 9,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 2,
            maximum_memory_bytes: 4096,
            semantic_digest: "a".repeat(64),
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn real_local_process_driver_loads_runs_and_unloads_digest_pinned_runtime() {
    let fixture = Fixture::new();
    let grant = fixture.grant();
    let verified = VerifiedResourceGrant::trusted_in_process(100, grant).unwrap();
    let mut worker = InferenceWorker::new(
        100,
        "worker.local.1".to_string(),
        9,
        verified,
        fixture.driver(),
    )
    .unwrap();

    let loaded = worker.load_model(100, fixture.manifest.clone()).unwrap();
    assert_eq!(loaded.observed_memory_bytes, 1024);

    let input = "hello".to_string();
    let payload_digest = sha256(input.as_bytes());
    let observed = worker
        .run(
            100,
            &fixture.manifest.model_id,
            WorkerRequest {
                request_id: "request.local.1".to_string(),
                reservation_id: "reservation.local.1".to_string(),
                model_digest: fixture.manifest.model_digest.clone(),
                input,
                payload_digest: payload_digest.clone(),
                maximum_tokens: 16,
                deadline_ms: 9000,
                lease_payload_digest: payload_digest,
                reservation_model_digest: fixture.manifest.model_digest.clone(),
                reservation_maximum_tokens: 16,
                cancelled: false,
            },
        )
        .unwrap();
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert_eq!(observed.consumed_tokens, Some(3));
    assert_eq!(observed.observed_memory_bytes, 1280);
    assert_eq!(observed.output_digest, Some(sha256(b"local:hello")));

    assert!(
        worker
            .unload_model(100, &fixture.manifest.model_id)
            .unwrap()
            .terminal_observed
    );
}

#[test]
fn local_process_driver_rejects_artifact_mutation_before_spawn() {
    let fixture = Fixture::new();
    fs::write(&fixture.artifacts.weights_path, b"mutated-after-selection").unwrap();
    let grant = fixture.grant();
    let verified = VerifiedResourceGrant::trusted_in_process(100, grant).unwrap();
    let mut worker = InferenceWorker::new(
        100,
        "worker.local.1".to_string(),
        9,
        verified,
        fixture.driver(),
    )
    .unwrap();
    assert!(matches!(
        worker.load_model(100, fixture.manifest.clone()),
        Err(Error::DriverFailure(message)) if message.contains("weights digest mismatch")
    ));
}
