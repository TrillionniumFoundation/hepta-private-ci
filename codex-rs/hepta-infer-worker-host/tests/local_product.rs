#![cfg(unix)]

use std::collections::BTreeSet;
use std::fs;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_worker_host::AuthorityLease;
use codex_hepta_infer_worker_host::InferenceRequest;
use codex_hepta_infer_worker_host::Reservation;
use codex_hepta_infer_worker_host::local_process::LocalModelArtifacts;
use codex_hepta_infer_worker_host::local_product::LocalExecutionEnvelopeV1;
use codex_hepta_infer_worker_host::local_product::LocalProductConfig;
use codex_hepta_infer_worker_host::local_product::LocalProductStatus;
use codex_hepta_infer_worker_host::local_product::execute_local_product;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::resource_grant_binding;
use codex_hepta_infer_worker_host::model_worker::sha256_hex;
use codex_hepta_infer_worker_host::request_digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

const PROTOCOL: &str = "hepta.local-model-runtime.v1";

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

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap()
}

fn fixture() -> Fixture {
    let root = std::env::temp_dir().join(format!(
        "hepta-local-product-{}-{}",
        std::process::id(),
        now_ms()
    ));
    fs::create_dir_all(&root).unwrap();
    let write = |name: &str, bytes: &[u8]| {
        let path = root.join(name);
        fs::write(&path, bytes).unwrap();
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

#[test]
fn signed_product_envelope_reaches_exact_local_runtime_once() {
    let fixture = fixture();
    let listener = UnixListener::bind(&fixture.socket).unwrap();
    fs::set_permissions(&fixture.socket, fs::Permissions::from_mode(0o600)).unwrap();
    let manifest_for_server = fixture.manifest.clone();
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
                "load" => json!({
                    "protocol": PROTOCOL,
                    "ok": true,
                    "error": null,
                    "handle_id": "handle.product",
                    "observed_memory_bytes": 2048,
                    "model_digest": manifest_for_server.model_digest.clone(),
                    "weights_digest": manifest_for_server.weights_digest.clone(),
                    "tokenizer_digest": manifest_for_server.tokenizer_digest.clone(),
                    "preprocessor_digest": manifest_for_server.preprocessor_digest.clone(),
                    "quantization_digest": manifest_for_server.quantization_digest.clone(),
                    "runtime_digest": manifest_for_server.runtime_digest.clone(),
                    "device_digest": manifest_for_server.device_digest.clone(),
                    "isolation_digest": manifest_for_server.isolation_digest.clone()
                }),
                "infer" => {
                    assert_eq!(request["request"]["request_id"], "request.1");
                    assert_eq!(request["request"]["prompt"], "product input");
                    json!({
                        "protocol": PROTOCOL,
                        "ok": true,
                        "error": null,
                        "terminal_observed": true,
                        "succeeded": true,
                        "output": "product output",
                        "consumed_tokens": 9,
                        "observed_memory_bytes": 2048
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

    let now = now_ms();
    let request = InferenceRequest {
        request_id: StableId::new("request.1").unwrap(),
        reservation_id: StableId::new("reservation.1").unwrap(),
        model_digest: fixture.manifest.model_digest.parse::<Digest32>().unwrap(),
        prompt_digest: Digest32::of_bytes(b"product input"),
        maximum_tokens: 64,
        deadline_ms: now + 60_000,
    };
    let canonical_request_digest = request_digest(&request);
    let lease = AuthorityLease {
        lease_id: StableId::new("lease.1").unwrap(),
        request_id: request.request_id.clone(),
        model_digest: request.model_digest,
        payload_digest: canonical_request_digest,
        expires_at_ms: now + 60_000,
        revoked: false,
    };
    let reservation = Reservation {
        reservation_id: request.reservation_id.clone(),
        request_id: request.request_id.clone(),
        model_digest: request.model_digest,
        maximum_tokens: 64,
        valid_until_ms: now + 60_000,
        cancelled: false,
    };
    let envelope = LocalExecutionEnvelopeV1 {
        schema_version: 1,
        request_id: request.request_id.to_string(),
        reservation_id: request.reservation_id.to_string(),
        model_digest: request.model_digest.to_string(),
        prompt_digest: request.prompt_digest.to_string(),
        prompt: "product input".to_string(),
        maximum_tokens: request.maximum_tokens,
        deadline_ms: request.deadline_ms,
        lease_id: lease.lease_id.to_string(),
        lease_request_id: lease.request_id.to_string(),
        lease_model_digest: lease.model_digest.to_string(),
        lease_payload_digest: lease.payload_digest.to_string(),
        lease_expires_at_ms: lease.expires_at_ms,
        lease_revoked: lease.revoked,
        reservation_request_id: reservation.request_id.to_string(),
        reservation_model_digest: reservation.model_digest.to_string(),
        reservation_maximum_tokens: reservation.maximum_tokens,
        reservation_valid_until_ms: reservation.valid_until_ms,
        reservation_cancelled: reservation.cancelled,
    };

    let resource_grant = ResourceGrant {
        grant_id: "resource.1".to_string(),
        authority_epoch: 1,
        generation: 3,
        expires_at_ms: now + 60_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 4096,
        semantic_digest: "2".repeat(64),
    };
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let final_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "signer.1".to_string(),
        authority_epoch: 1,
        grant_id: "resource.1".to_string(),
        nonce: [9_u8; 32],
        binding: resource_grant_binding("worker.1", &resource_grant).unwrap(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing_key
        .sign(&final_grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let signed_resource_grant = SignedFinalUseGrant {
        grant: final_grant,
        signature,
    };
    let authority_dir = fixture.root.join("authority");
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "signer.1".to_string(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();

    let output = execute_local_product(
        now,
        LocalProductConfig {
            worker_id: "worker.1".to_string(),
            generation: 3,
            runtime_socket: fixture.socket.clone(),
            artifacts: fixture.artifacts.clone(),
            timeout: Duration::from_secs(2),
        },
        &authority,
        &signed_resource_grant,
        resource_grant,
        fixture.manifest.clone(),
        envelope,
    )
    .unwrap();
    assert_eq!(output.status, LocalProductStatus::Succeeded);
    assert_eq!(output.consumed_tokens, 9);
    assert_eq!(output.output_digest, Some(sha256_hex(b"product output")));
    assert!(output.terminal_observed);

    server.join().unwrap();
    drop(authority);
}
