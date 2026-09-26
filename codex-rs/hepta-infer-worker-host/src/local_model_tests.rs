use super::*;

use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

#[derive(Debug)]
struct FixedClock(u64);

impl TrustedClock for FixedClock {
    fn now_ms(&self) -> Result<u64, LocalModelError> {
        Ok(self.0)
    }
}

#[derive(Debug)]
struct FakeDriver {
    resident_bytes: Arc<AtomicU64>,
    run_calls: AtomicUsize,
    inspect_calls: AtomicUsize,
    unload_fails: AtomicBool,
    missing_usage: AtomicBool,
    fail_run_after_effect_once: AtomicBool,
    terminal: Mutex<BTreeMap<String, DriverExecutionObservation>>,
}

impl FakeDriver {
    fn new(resident_bytes: Arc<AtomicU64>) -> Self {
        Self {
            resident_bytes,
            run_calls: AtomicUsize::new(0),
            inspect_calls: AtomicUsize::new(0),
            unload_fails: AtomicBool::new(false),
            missing_usage: AtomicBool::new(false),
            fail_run_after_effect_once: AtomicBool::new(false),
            terminal: Mutex::new(BTreeMap::new()),
        }
    }

    fn observation(
        &self,
        operation_id: &str,
        handle: &AttestedModelHandle,
        input: &VerifiedInput,
        cancellation: &CancellationToken,
    ) -> DriverExecutionObservation {
        let cancelled = cancellation.is_cancelled();
        DriverExecutionObservation {
            operation_id: operation_id.to_string(),
            handle_id: handle.handle_id().to_string(),
            model_digest: handle.manifest().manifest().model_digest.clone(),
            input_digest: input.digest().to_string(),
            terminal_observed: true,
            terminal_status: Some(if cancelled {
                DriverTerminalStatus::Cancelled
            } else {
                DriverTerminalStatus::Succeeded
            }),
            output_digest: if cancelled { None } else { Some("c".repeat(64)) },
            consumed_tokens: Some(if cancelled { 0 } else { 4 }),
            usage_units: if self.missing_usage.load(Ordering::SeqCst) {
                None
            } else {
                Some(if cancelled { 0 } else { 7 })
            },
            observed_transient_bytes: 128,
        }
    }
}

impl LocalModelDriver for FakeDriver {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        _grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadedModel> {
        self.resident_bytes.store(1_024, Ordering::SeqCst);
        let result = DriverLoadedModel {
            handle_id: "handle.1".to_string(),
            model_digest: manifest.manifest().model_digest.clone(),
            device_id: manifest.manifest().device_id.clone(),
            device_lease_id: manifest.manifest().device_lease_id.clone(),
            observed_loaded_bytes: 1_024,
        };
        Box::pin(async move { Ok(result) })
    }

    fn run<'a>(
        &'a self,
        operation_id: &'a str,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        _maximum_tokens: u32,
        cancellation: &'a CancellationToken,
        _deadline: Instant,
    ) -> DriverFuture<'a, DriverExecutionObservation> {
        self.run_calls.fetch_add(1, Ordering::SeqCst);
        let observation = self.observation(operation_id, handle, input, cancellation);
        self.terminal
            .lock()
            .expect("terminal map lock")
            .insert(operation_id.to_string(), observation.clone());
        let fail = self
            .fail_run_after_effect_once
            .swap(false, Ordering::SeqCst);
        Box::pin(async move {
            if fail {
                Err(LocalModelError::Driver(
                    "lost acknowledgement after effect entry".to_string(),
                ))
            } else {
                Ok(observation)
            }
        })
    }

    fn inspect<'a>(
        &'a self,
        operation_id: &'a str,
    ) -> DriverFuture<'a, DriverReconciliation> {
        self.inspect_calls.fetch_add(1, Ordering::SeqCst);
        let result = self
            .terminal
            .lock()
            .expect("terminal map lock")
            .get(operation_id)
            .cloned()
            .map_or(DriverReconciliation::NotFound, DriverReconciliation::Terminal);
        Box::pin(async move { Ok(result) })
    }

    fn unload<'a>(
        &'a self,
        _handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, DriverUnloadObservation> {
        let fails = self.unload_fails.load(Ordering::SeqCst);
        if !fails {
            self.resident_bytes.store(0, Ordering::SeqCst);
        }
        Box::pin(async move {
            if fails {
                Err(LocalModelError::Driver("unload failed".to_string()))
            } else {
                Ok(DriverUnloadObservation {
                    terminal_observed: true,
                    released: true,
                })
            }
        })
    }
}

#[derive(Debug)]
struct FakeObserver {
    resident_bytes: Arc<AtomicU64>,
    fenced: AtomicBool,
}

impl FakeObserver {
    fn new(resident_bytes: Arc<AtomicU64>) -> Self {
        Self {
            resident_bytes,
            fenced: AtomicBool::new(false),
        }
    }

    fn observation(&self, handle_id: &str, generation: u64) -> TrustedResourceObservation {
        TrustedResourceObservation {
            handle_id: handle_id.to_string(),
            worker_generation: generation,
            device_id: "gpu.0".to_string(),
            device_lease_id: "device-lease.1".to_string(),
            resident_bytes: self.resident_bytes.load(Ordering::SeqCst),
            generation_fenced: self.fenced.load(Ordering::SeqCst),
            evidence_digest: "d".repeat(64),
        }
    }
}

impl TrustedResourceObserver for FakeObserver {
    fn attest_loaded(
        &self,
        _manifest: &VerifiedModelManifest,
        loaded: &DriverLoadedModel,
        worker_generation: u64,
    ) -> Result<TrustedResourceObservation, LocalModelError> {
        Ok(self.observation(&loaded.handle_id, worker_generation))
    }

    fn observe_handle(
        &self,
        handle: &AttestedModelHandle,
    ) -> Result<TrustedResourceObservation, LocalModelError> {
        Ok(self.observation(handle.handle_id(), handle.worker_generation()))
    }
}

fn signed_grant(
    maximum_aggregate_memory_bytes: u64,
) -> (ResourceGrantVerifier, VerifiedResourceGrant) {
    let signer = SigningKey::from_bytes(&[7; 32]);
    let verifier = ResourceGrantVerifier::new(
        "issuer.1".to_string(),
        signer.verifying_key().to_bytes(),
        9,
        1,
        "e".repeat(64),
        BTreeSet::new(),
    )
    .expect("verifier");
    let claims = ResourceGrantClaimsV1 {
        issuer_id: "issuer.1".to_string(),
        grant_id: "grant.1".to_string(),
        nonce: "nonce.1".to_string(),
        authority_epoch: 9,
        revocation_revision: 1,
        revocation_head_digest: "e".repeat(64),
        issued_at_ms: 900,
        not_before_ms: 900,
        expires_at_ms: 10_000,
        worker_id: "worker.1".to_string(),
        worker_generation: 3,
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "gpu.0".to_string(),
        device_lease_id: "device-lease.1".to_string(),
        maximum_aggregate_memory_bytes,
        maximum_transient_memory_bytes: maximum_aggregate_memory_bytes.min(1_024),
        maximum_concurrent_requests: 2,
        maximum_tokens_per_request: 128,
        maximum_usage_units: 1_000,
        semantic_digest: String::new(),
    }
    .with_computed_semantic_digest();
    let signed = SignedResourceGrantV1 {
        signature: signer.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
    let verified = verifier
        .verify(1_000, "worker.1", 3, &signed)
        .expect("verified grant");
    (verifier, verified)
}

fn manifest() -> ModelManifestV1 {
    ModelManifestV1 {
        model_id: "model.1".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "gpu.0".to_string(),
        device_lease_id: "device-lease.1".to_string(),
        declared_weight_bytes: 1_024,
        maximum_tokens: 128,
        semantic_digest: String::new(),
    }
    .with_computed_semantic_digest()
}

fn verified_input() -> VerifiedInput {
    let bytes = b"verified local input".to_vec();
    let expected = digest(&bytes);
    VerifiedInput::verify(bytes, &expected, 4_096).expect("verified input")
}

fn request(id: &str, input: &VerifiedInput) -> LocalRunRequest {
    LocalRunRequest {
        request_id: id.to_string(),
        input_digest: input.digest().to_string(),
        maximum_tokens: 64,
        maximum_usage_units: 100,
        maximum_transient_memory_bytes: 256,
        deadline_ms: 9_000,
    }
}

fn worker(
    path: &Path,
    grant: VerifiedResourceGrant,
    driver: Arc<FakeDriver>,
    observer: Arc<FakeObserver>,
) -> LocalModelWorker {
    LocalModelWorker::new(
        "worker.1".to_string(),
        3,
        grant,
        driver,
        observer,
        Arc::new(FixedClock(1_000)),
        DurableInferenceControl::open(path, 64).expect("control journal"),
    )
    .expect("local worker")
}

#[test]
fn forged_signature_and_later_revocation_fail_closed() {
    let signer = SigningKey::from_bytes(&[8; 32]);
    let verifier = ResourceGrantVerifier::new(
        "issuer.2".to_string(),
        signer.verifying_key().to_bytes(),
        4,
        1,
        "a".repeat(64),
        BTreeSet::new(),
    )
    .expect("verifier");
    let mut claims = ResourceGrantClaimsV1 {
        issuer_id: "issuer.2".to_string(),
        grant_id: "grant.2".to_string(),
        nonce: "nonce.2".to_string(),
        authority_epoch: 4,
        revocation_revision: 1,
        revocation_head_digest: "a".repeat(64),
        issued_at_ms: 1,
        not_before_ms: 1,
        expires_at_ms: 10_000,
        worker_id: "worker.2".to_string(),
        worker_generation: 2,
        model_id: "model.2".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "gpu.2".to_string(),
        device_lease_id: "device-lease.2".to_string(),
        maximum_aggregate_memory_bytes: 2_048,
        maximum_transient_memory_bytes: 512,
        maximum_concurrent_requests: 1,
        maximum_tokens_per_request: 64,
        maximum_usage_units: 100,
        semantic_digest: String::new(),
    }
    .with_computed_semantic_digest();
    let signature = signer.sign(&claims.signing_bytes()).to_bytes();
    let verified = verifier
        .verify(
            100,
            "worker.2",
            2,
            &SignedResourceGrantV1 {
                claims: claims.clone(),
                signature,
            },
        )
        .expect("valid signed grant");
    let mut forged = signature;
    forged[0] ^= 1;
    assert!(matches!(
        verifier.verify(
            100,
            "worker.2",
            2,
            &SignedResourceGrantV1 {
                claims: claims.clone(),
                signature: forged,
            }
        ),
        Err(LocalModelError::InvalidSignature)
    ));
    verifier
        .update_revocations(
            4,
            2,
            "b".repeat(64),
            BTreeSet::from([claims.grant_id.clone()]),
        )
        .expect("advance revocations");
    assert_eq!(
        verified.validate_current(101),
        Err(LocalModelError::GrantRevoked)
    );
    claims.revocation_revision = 0;
    assert!(matches!(
        verifier.verify(
            100,
            "worker.2",
            2,
            &SignedResourceGrantV1 { claims, signature }
        ),
        Err(LocalModelError::RevocationRollback)
    ));
}

#[test]
fn aggregate_load_reservation_is_atomic_and_bounded() {
    let (_verifier, grant) = signed_grant(100);
    let resources = ResourceManager::new(&grant);
    let first = resources.reserve_load("model.a", 60).expect("first reservation");
    assert!(matches!(
        resources.reserve_load("model.b", 50),
        Err(LocalModelError::ResourceCapacity)
    ));
    drop(first);
    assert_eq!(resources.snapshot().expect("snapshot").reserved_load_bytes, 0);
}

#[tokio::test]
async fn exact_duplicate_returns_durable_receipt_without_second_run() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("local.journal");
    let (_verifier, grant) = signed_grant(8_192);
    let resident = Arc::new(AtomicU64::new(0));
    let driver = Arc::new(FakeDriver::new(Arc::clone(&resident)));
    let observer = Arc::new(FakeObserver::new(resident));
    let worker = worker(&path, grant, Arc::clone(&driver), observer);
    worker.load_model(manifest()).await.expect("load");
    let input = verified_input();
    let run_request = request("request.duplicate", &input);
    let first = worker
        .run(
            "model.1",
            run_request.clone(),
            input.clone(),
            &CancellationToken::new(),
        )
        .await
        .expect("first run");
    assert_eq!(first.state, LocalExecutionState::Completed);
    let duplicate = worker
        .run(
            "model.1",
            run_request,
            input,
            &CancellationToken::new(),
        )
        .await
        .expect("duplicate");
    assert_eq!(duplicate.state, LocalExecutionState::Completed);
    assert!(duplicate.replayed_from_journal);
    assert_eq!(driver.run_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn missing_usage_stays_pending_and_is_never_inferred_as_zero() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("usage.journal");
    let (_verifier, grant) = signed_grant(8_192);
    let resident = Arc::new(AtomicU64::new(0));
    let driver = Arc::new(FakeDriver::new(Arc::clone(&resident)));
    driver.missing_usage.store(true, Ordering::SeqCst);
    let observer = Arc::new(FakeObserver::new(resident));
    let worker = worker(&path, grant, Arc::clone(&driver), observer);
    worker.load_model(manifest()).await.expect("load");
    let input = verified_input();
    let run_request = request("request.usage", &input);
    let first = worker
        .run(
            "model.1",
            run_request.clone(),
            input.clone(),
            &CancellationToken::new(),
        )
        .await
        .expect("first run");
    assert_eq!(first.state, LocalExecutionState::UsagePending);
    assert_eq!(first.usage_units, None);
    let second = worker
        .run(
            "model.1",
            run_request,
            input,
            &CancellationToken::new(),
        )
        .await
        .expect("reconcile");
    assert_eq!(second.state, LocalExecutionState::UsagePending);
    assert_eq!(second.usage_units, None);
    assert_eq!(driver.run_calls.load(Ordering::SeqCst), 1);
    assert_eq!(driver.inspect_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn lost_ack_reopens_through_inspect_without_driver_replay() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("reopen.journal");
    let (_verifier, grant) = signed_grant(8_192);
    let resident = Arc::new(AtomicU64::new(0));
    let driver = Arc::new(FakeDriver::new(Arc::clone(&resident)));
    driver
        .fail_run_after_effect_once
        .store(true, Ordering::SeqCst);
    let observer = Arc::new(FakeObserver::new(Arc::clone(&resident)));
    let input = verified_input();
    let run_request = request("request.reopen", &input);
    {
        let first_worker = worker(
            &path,
            grant.clone(),
            Arc::clone(&driver),
            Arc::clone(&observer),
        );
        first_worker.load_model(manifest()).await.expect("load");
        let unknown = first_worker
            .run(
                "model.1",
                run_request.clone(),
                input.clone(),
                &CancellationToken::new(),
            )
            .await
            .expect("unknown result");
        assert_eq!(unknown.state, LocalExecutionState::Quarantined);
    }
    let reopened = worker(&path, grant, Arc::clone(&driver), observer);
    reopened.load_model(manifest()).await.expect("reload");
    let settled = reopened
        .run(
            "model.1",
            run_request,
            input,
            &CancellationToken::new(),
        )
        .await
        .expect("inspect and settle");
    assert_eq!(settled.state, LocalExecutionState::Completed);
    assert!(settled.replayed_from_journal);
    assert_eq!(driver.run_calls.load(Ordering::SeqCst), 1);
    assert_eq!(driver.inspect_calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn unload_failure_retains_handle_as_zombie() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("unload.journal");
    let (_verifier, grant) = signed_grant(8_192);
    let resident = Arc::new(AtomicU64::new(0));
    let driver = Arc::new(FakeDriver::new(Arc::clone(&resident)));
    driver.unload_fails.store(true, Ordering::SeqCst);
    let observer = Arc::new(FakeObserver::new(resident));
    let worker = worker(&path, grant, driver, observer);
    worker.load_model(manifest()).await.expect("load");
    assert!(worker.unload_model("model.1").await.is_err());
    let snapshot = worker.resources().snapshot().expect("snapshot");
    assert_eq!(
        snapshot.models.get("model.1"),
        Some(&ModelResourceState::Zombie)
    );
    assert_eq!(snapshot.loaded_bytes, 1_024);
}
