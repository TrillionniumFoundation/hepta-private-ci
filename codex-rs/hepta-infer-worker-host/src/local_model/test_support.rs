use std::collections::BTreeSet;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use ed25519_dalek::{Signer, SigningKey};
use tempfile::tempdir;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::*;

#[derive(Clone)]
struct FixedClock {
    now_ms: u64,
}

impl TrustedClock for FixedClock {
    fn now_ms(&self) -> Result<u64, Error> {
        Ok(self.now_ms)
    }

    fn instant_for(&self, deadline_ms: u64) -> Result<Instant, Error> {
        let remaining = deadline_ms
            .checked_sub(self.now_ms)
            .ok_or(Error::InvalidDeadline)?;
        Ok(Instant::now() + Duration::from_millis(remaining))
    }
}

struct TestObserver {
    present: Mutex<bool>,
}

impl TrustedResourceObserver for TestObserver {
    fn observe<'a>(
        &'a self,
        handle_id: &'a str,
        operation_id: Option<&'a OperationId>,
    ) -> ObserverFuture<'a> {
        Box::pin(async move {
            let present = *self
                .present
                .lock()
                .map_err(|_| ObserverError::new("poisoned"))?;
            Ok(HostResourceObservation {
                present,
                handle_id: handle_id.to_string(),
                worker_generation: 7,
                device_id: "device.1".to_string(),
                device_digest: "7".repeat(64),
                model_memory_bytes: if present { 1_024 } else { 0 },
                kv_memory_bytes: operation_id.map_or(0, |_| 128),
                transient_memory_bytes: operation_id.map_or(0, |_| 64),
            })
        })
    }
}

struct TestDriver {
    run_calls: AtomicUsize,
    inspect_calls: AtomicUsize,
    observer: Arc<TestObserver>,
    run_result: Mutex<DriverRunEvidence>,
    inspect_result: Mutex<Option<DriverRunEvidence>>,
    unload_terminal: bool,
}

impl TestDriver {
    fn terminal() -> DriverRunEvidence {
        DriverRunEvidence {
            terminal_observed: true,
            status: Some(DriverTerminalStatus::Succeeded),
            output_digest: Some("f".repeat(64)),
            consumed_tokens: Some(0),
            observed_model_bytes: 1_024,
            observed_kv_memory_bytes: 128,
            transient_memory_bytes: 64,
        }
    }
}

impl LocalModelDriver for TestDriver {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        _grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadEvidence> {
        Box::pin(async move {
            Ok(DriverLoadEvidence {
                handle_id: "handle.1".to_string(),
                model_digest: manifest.manifest.model_digest.clone(),
                weights_digest: manifest.manifest.weights_digest.clone(),
                runtime_digest: manifest.manifest.runtime_digest.clone(),
                device_id: manifest.manifest.device_id.clone(),
                device_digest: manifest.manifest.device_digest.clone(),
                observed_weight_bytes: 1_024,
            })
        })
    }

    fn run<'a>(
        &'a self,
        _operation_id: &'a OperationId,
        _handle: &'a AttestedModelHandle,
        _input: &'a VerifiedInput,
        _cancellation: &'a CancellationToken,
        _deadline: &'a TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunEvidence> {
        self.run_calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            self.run_result
                .lock()
                .map_err(|_| DriverError::new("poisoned"))
                .map(|value| value.clone())
        })
    }

    fn inspect<'a>(
        &'a self,
        _operation_id: &'a OperationId,
    ) -> DriverFuture<'a, Option<DriverRunEvidence>> {
        self.inspect_calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            self.inspect_result
                .lock()
                .map_err(|_| DriverError::new("poisoned"))
                .map(|value| value.clone())
        })
    }

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, DriverUnloadEvidence> {
        Box::pin(async move {
            if self.unload_terminal {
                *self
                    .observer
                    .present
                    .lock()
                    .map_err(|_| DriverError::new("poisoned"))? = false;
            }
            Ok(DriverUnloadEvidence {
                terminal_observed: self.unload_terminal,
                released_memory_bytes: handle.observed_weight_bytes,
            })
        })
    }
}

fn claims() -> ResourceGrantClaims {
    let mut claims = ResourceGrantClaims {
        issuer: "issuer.1".to_string(),
        authority_epoch: 3,
        revocation_revision: 4,
        grant_id: "grant.1".to_string(),
        nonce: "nonce.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 7,
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "device.1".to_string(),
        device_digest: "7".repeat(64),
        maximum_model_memory_bytes: 2_048,
        maximum_aggregate_memory_bytes: 8_192,
        maximum_kv_memory_bytes: 1_024,
        maximum_transient_memory_bytes: 512,
        maximum_concurrent_requests: 2,
        maximum_tokens: 128,
        expires_at_ms: 10_000,
        semantic_digest: "8".repeat(64),
    };
    claims.semantic_digest = resource_grant_semantic_digest(&claims).unwrap();
    claims
}

fn signed_grant() -> (ResourceGrantVerifier, SignedResourceGrant) {
    let signing = SigningKey::from_bytes(&[9_u8; 32]);
    let claims = claims();
    let signature = signing
        .sign(&resource_grant_signing_bytes(&claims).unwrap())
        .to_bytes()
        .to_vec();
    (
        ResourceGrantVerifier::new(
            "issuer.1".to_string(),
            signing.verifying_key().to_bytes(),
            3,
            4,
            BTreeSet::new(),
        )
        .unwrap(),
        SignedResourceGrant { claims, signature },
    )
}

fn verified_grant() -> VerifiedResourceGrant {
    let (verifier, signed) = signed_grant();
    verifier.verify(&signed, 100, "worker.1", 7).unwrap()
}

fn manifest() -> ModelManifestEvidence {
    ModelManifestEvidence {
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "device.1".to_string(),
        device_digest: "7".repeat(64),
        declared_weight_bytes: 1_024,
        maximum_kv_memory_bytes: 1_024,
        maximum_transient_memory_bytes: 512,
        maximum_tokens: 128,
    }
}

fn input() -> VerifiedInput {
    let bytes = b"hello local model".to_vec();
    let expected = digest(&bytes);
    VerifiedInput::verify(bytes, &expected).unwrap()
}

fn driver(
    run_result: DriverRunEvidence,
    inspect_result: Option<DriverRunEvidence>,
    unload_terminal: bool,
) -> Arc<TestDriver> {
    Arc::new(TestDriver {
        run_calls: AtomicUsize::new(0),
        inspect_calls: AtomicUsize::new(0),
        observer: Arc::new(TestObserver {
            present: Mutex::new(true),
        }),
        run_result: Mutex::new(run_result),
        inspect_result: Mutex::new(inspect_result),
        unload_terminal,
    })
}

fn worker(
    driver: &Arc<TestDriver>,
    resources: ResourceManager,
) -> DurableLocalWorker<TestDriver, TestObserver, FixedClock> {
    DurableLocalWorker::new(
        "worker.1".to_string(),
        7,
        Arc::clone(driver),
        Arc::clone(&driver.observer),
        FixedClock { now_ms: 100 },
        resources,
    )
    .unwrap()
}
