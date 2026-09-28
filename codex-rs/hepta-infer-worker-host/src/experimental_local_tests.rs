use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::tempdir;
use tokio_util::sync::CancellationToken;

use super::*;

#[derive(Clone, Copy)]
struct FixedClock(u64);

impl TrustedClock for FixedClock {
    fn now_ms(&self) -> Result<u64, LocalWorkerError> {
        Ok(self.0)
    }
}

#[derive(Clone)]
struct FakeDriver {
    state: Arc<FakeDriverState>,
}

struct FakeDriverState {
    loads: AtomicUsize,
    runs: AtomicUsize,
    inspections: AtomicUsize,
    failed_load_cleanups: AtomicUsize,
    fail_unload: AtomicBool,
    corrupt_load_identity: AtomicBool,
    run_observation: Mutex<DriverRunObservation>,
    reconciliation: Mutex<DriverReconciliation>,
}

impl FakeDriver {
    fn new() -> Self {
        Self {
            state: Arc::new(FakeDriverState {
                loads: AtomicUsize::new(0),
                runs: AtomicUsize::new(0),
                inspections: AtomicUsize::new(0),
                failed_load_cleanups: AtomicUsize::new(0),
                fail_unload: AtomicBool::new(false),
                corrupt_load_identity: AtomicBool::new(false),
                run_observation: Mutex::new(success_observation()),
                reconciliation: Mutex::new(DriverReconciliation::MissingHistory),
            }),
        }
    }
}

impl LocalModelDriver for FakeDriver {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        _grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, DriverLoadObservation> {
        let sequence = self.state.loads.fetch_add(1, Ordering::SeqCst) + 1;
        let corrupt = self.state.corrupt_load_identity.load(Ordering::SeqCst);
        let raw = manifest.as_manifest().clone();
        Box::pin(async move {
            Ok(DriverLoadObservation {
                handle_id: format!("local.handle.{sequence}"),
                model_digest: if corrupt {
                    digest(b"wrong-model")
                } else {
                    raw.model_digest
                },
                weights_digest: raw.weights_digest,
                runtime_digest: raw.runtime_digest,
                device_uuid: raw.device_uuid,
                driver_reported_memory_bytes: 1,
            })
        })
    }

    fn cleanup_failed_load<'a>(
        &'a self,
        _load: &'a DriverLoadObservation,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
        self.state
            .failed_load_cleanups
            .fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            Ok(DriverUnloadObservation {
                terminal_observed: true,
                released_memory_bytes: Some(100),
            })
        })
    }

    fn run<'a>(
        &'a self,
        _handle: &'a AttestedModelHandle,
        _input: &'a VerifiedInput,
        _cancellation: &'a CancellationToken,
        _deadline: TrustedDeadline,
    ) -> LocalFuture<'a, DriverRunObservation> {
        self.state.runs.fetch_add(1, Ordering::SeqCst);
        let observed = self
            .state
            .run_observation
            .lock()
            .expect("run observation lock")
            .clone();
        Box::pin(async move { Ok(observed) })
    }

    fn inspect<'a>(
        &'a self,
        _operation_id: &'a str,
        _handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation> {
        self.state.inspections.fetch_add(1, Ordering::SeqCst);
        let observed = self
            .state
            .reconciliation
            .lock()
            .expect("reconciliation lock")
            .clone();
        Box::pin(async move { Ok(observed) })
    }

    fn unload<'a>(
        &'a self,
        _handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
        let fail = self.state.fail_unload.load(Ordering::SeqCst);
        Box::pin(async move {
            if fail {
                Err(LocalWorkerError::Driver(
                    "injected unload failure".to_string(),
                ))
            } else {
                Ok(DriverUnloadObservation {
                    terminal_observed: true,
                    released_memory_bytes: Some(100),
                })
            }
        })
    }
}

#[derive(Clone, Copy)]
struct FakeObserver;

impl TrustedResourceObserver for FakeObserver {
    fn observe_model<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedResourceObservation> {
        let handle_id = handle_id.to_string();
        let device_uuid = device_uuid.to_string();
        Box::pin(async move {
            Ok(TrustedResourceObservation {
                observer_id: "trusted.os.observer".to_string(),
                handle_id,
                worker_generation,
                device_uuid,
                device_epoch: 3,
                resident_memory_bytes: 100,
                transient_memory_bytes: 0,
                attestation_digest: digest(b"resident-attestation"),
            })
        })
    }

    fn observe_unattested_release<'a>(
        &'a self,
        handle_id: &'a str,
        device_uuid: &'a str,
        worker_generation: u64,
    ) -> LocalFuture<'a, TrustedReleaseObservation> {
        let handle_id = handle_id.to_string();
        let device_uuid = device_uuid.to_string();
        Box::pin(async move {
            Ok(TrustedReleaseObservation {
                observer_id: "trusted.os.observer".to_string(),
                handle_id,
                worker_generation,
                device_uuid,
                device_epoch: 3,
                resident_memory_bytes: 0,
                attestation_digest: digest(b"failed-load-release-attestation"),
            })
        })
    }

    fn observe_release<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, TrustedReleaseObservation> {
        let handle_id = handle.handle_id().to_string();
        let device_uuid = handle.device_uuid().to_string();
        let generation = handle.worker_generation();
        let device_epoch = handle.device_epoch();
        Box::pin(async move {
            Ok(TrustedReleaseObservation {
                observer_id: "trusted.os.observer".to_string(),
                handle_id,
                worker_generation: generation,
                device_uuid,
                device_epoch,
                resident_memory_bytes: 0,
                attestation_digest: digest(b"release-attestation"),
            })
        })
    }
}

fn success_observation() -> DriverRunObservation {
    DriverRunObservation {
        terminal_observed: true,
        status: DriverTerminalStatus::Succeeded,
        output: b"answer".to_vec(),
        observed_tokens: Some(7),
        usage_units: Some(11),
        stop_reason: None,
    }
}

fn signed_grant(maximum_memory: u64) -> (VerifiedResourceGrant, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[9_u8; 32]);
    let revoked = BTreeSet::new();
    let frontier_digest = digest(
        &serde_json::to_vec(&(
            "hepta.local-resource-revocations.v1",
            5_u64,
            8_u64,
            &revoked,
        ))
        .expect("frontier encoding"),
    );
    let frontier = TrustedRevocationFrontier {
        authority_epoch: 5,
        revision: 8,
        head_digest: frontier_digest.clone(),
        revoked_grant_ids: revoked,
    };
    let verifier = ResourceGrantVerifier::from_trusted_parts(
        "trusted.local.issuer".to_string(),
        signing_key.verifying_key().to_bytes(),
        frontier,
    )
    .expect("verifier");
    let mut claims = ResourceGrantClaims {
        schema_version: 1,
        issuer: "trusted.local.issuer".to_string(),
        authority_epoch: 5,
        grant_id: "grant.local.1".to_string(),
        nonce: "nonce.local.1".to_string(),
        worker_subject: "worker.local.1".to_string(),
        worker_generation: 2,
        model_id: "model.local.1".to_string(),
        model_digest: digest(b"model"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_digest: digest(b"quantization"),
        runtime_digest: digest(b"runtime"),
        device_uuid: "device.local.1".to_string(),
        device_lease_digest: digest(b"device-lease"),
        device_epoch: 3,
        maximum_aggregate_memory_bytes: maximum_memory,
        maximum_concurrency: 2,
        maximum_tokens: 128,
        maximum_usage_units: 1_000,
        issued_at_ms: 500,
        expires_at_ms: 10_000,
        revocation_revision: 8,
        revocation_head_digest: frontier_digest,
        semantic_digest: String::new(),
    };
    let mut semantic = claims.clone();
    semantic.semantic_digest.clear();
    claims.semantic_digest = digest(&serde_json::to_vec(&semantic).expect("semantic grant"));
    let signature = signing_key
        .sign(&claims.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let verified = verifier
        .verify(
            SignedResourceGrant { claims, signature },
            &FixedClock(1_000),
        )
        .expect("verified grant");
    (verified, signing_key)
}

fn manifest(grant: &VerifiedResourceGrant) -> VerifiedModelManifest {
    let claims = grant.claims();
    let mut value = LocalModelManifest {
        model_id: claims.model_id.clone(),
        model_digest: claims.model_digest.clone(),
        weights_digest: claims.weights_digest.clone(),
        tokenizer_digest: claims.tokenizer_digest.clone(),
        preprocessor_digest: claims.preprocessor_digest.clone(),
        quantization_digest: claims.quantization_digest.clone(),
        runtime_digest: claims.runtime_digest.clone(),
        device_uuid: claims.device_uuid.clone(),
        device_lease_digest: claims.device_lease_digest.clone(),
        expected_resident_memory_bytes: 100,
        semantic_digest: String::new(),
    };
    let mut semantic = value.clone();
    semantic.semantic_digest.clear();
    value.semantic_digest = digest(&serde_json::to_vec(&semantic).expect("manifest semantic"));
    VerifiedModelManifest::verify(grant, value).expect("verified manifest")
}

fn admission(request_id: &str) -> LocalRunAdmission {
    LocalRunAdmission {
        request_id: request_id.to_string(),
        maximum_in_flight: 2,
        maximum_tokens: 64,
        maximum_usage_units: 100,
        expected_transient_memory_bytes: 20,
        requested_deadline_ms: 5_000,
    }
}

fn input() -> VerifiedInput {
    let bytes = b"prompt".to_vec();
    let expected = digest(&bytes);
    VerifiedInput::verify(bytes, &expected, 1024).expect("verified input")
}

#[test]
fn signed_grant_rejects_post_signature_semantic_drift() {
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let revoked = BTreeSet::new();
    let head = digest(
        &serde_json::to_vec(&(
            "hepta.local-resource-revocations.v1",
            1_u64,
            1_u64,
            &revoked,
        ))
        .expect("frontier"),
    );
    let verifier = ResourceGrantVerifier::from_trusted_parts(
        "issuer.local".to_string(),
        signing_key.verifying_key().to_bytes(),
        TrustedRevocationFrontier {
            authority_epoch: 1,
            revision: 1,
            head_digest: head.clone(),
            revoked_grant_ids: revoked,
        },
    )
    .expect("verifier");
    let (verified, _) = signed_grant(256);
    let mut claims = verified.claims().clone();
    claims.issuer = "issuer.local".to_string();
    claims.authority_epoch = 1;
    claims.revocation_revision = 1;
    claims.revocation_head_digest = head;
    claims.maximum_aggregate_memory_bytes = 256;
    let mut semantic = claims.clone();
    semantic.semantic_digest.clear();
    claims.semantic_digest = digest(&serde_json::to_vec(&semantic).expect("semantic"));
    let signature = signing_key
        .sign(&claims.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    claims.maximum_aggregate_memory_bytes = 257;
    let error = verifier
        .verify(
            SignedResourceGrant { claims, signature },
            &FixedClock(1_000),
        )
        .expect_err("post-signature drift must fail");
    assert!(matches!(
        error,
        LocalWorkerError::InvalidGrant(_) | LocalWorkerError::InvalidSignature
    ));
}

#[tokio::test]
async fn failed_attestation_is_cleaned_and_does_not_leak_pending_capacity() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    driver
        .state
        .corrupt_load_identity
        .store(true, Ordering::SeqCst);
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");

    assert!(matches!(
        worker.load_model(&grant, &manifest).await,
        Err(LocalWorkerError::InvalidObservation(_))
    ));
    assert_eq!(
        driver
            .state
            .failed_load_cleanups
            .load(Ordering::SeqCst),
        1
    );
    let snapshot = worker.resources().snapshot().expect("snapshot");
    assert_eq!(snapshot.pending_model_bytes, 0);
    assert_eq!(snapshot.committed_model_bytes, 0);
    assert_eq!(snapshot.loaded_models, 0);
    assert_eq!(snapshot.fenced_reason, None);
}

#[tokio::test]
async fn aggregate_memory_and_failed_unload_preserve_resource_truth() {
    let (grant, _) = signed_grant(150);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("first model");
    assert_eq!(
        worker.load_model(&grant, &manifest).await,
        Err(LocalWorkerError::CapacityExceeded)
    );
    driver.state.fail_unload.store(true, Ordering::SeqCst);
    assert!(
        worker
            .unload_model(&grant, &manifest, &handle)
            .await
            .is_err()
    );
    assert_eq!(
        worker
            .resources()
            .model_lifecycle(handle.handle_id())
            .expect("lifecycle"),
        Some(ModelLifecycle::Zombie)
    );
    assert_eq!(
        worker
            .resources()
            .snapshot()
            .expect("snapshot")
            .committed_model_bytes,
        100
    );
}

#[tokio::test]
async fn same_process_terminal_reconciliation_releases_quarantined_resources() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let journal = directory.path().join("local-same-process.journal");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("control");

    *driver
        .state
        .run_observation
        .lock()
        .expect("run observation") = DriverRunObservation {
        terminal_observed: false,
        status: DriverTerminalStatus::Indeterminate,
        output: Vec::new(),
        observed_tokens: None,
        usage_units: None,
        stop_reason: Some("lost driver channel".to_string()),
    };
    let unknown = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.same-process"),
            &input(),
            &CancellationToken::new(),
        )
        .await
        .expect("unknown run");
    assert_eq!(unknown.status, LocalRunStatus::Indeterminate);
    let held = worker.resources().snapshot().expect("held snapshot");
    assert_eq!(held.active_or_quarantined_requests, 1);
    assert_eq!(held.request_bytes, 20);

    *driver
        .state
        .reconciliation
        .lock()
        .expect("reconciliation") = DriverReconciliation::Terminal(success_observation());
    let terminal = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.same-process"),
            &input(),
            &CancellationToken::new(),
        )
        .await
        .expect("terminal reconciliation");
    assert_eq!(terminal.status, LocalRunStatus::Succeeded);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.inspections.load(Ordering::SeqCst), 1);
    let released = worker.resources().snapshot().expect("released snapshot");
    assert_eq!(released.active_or_quarantined_requests, 0);
    assert_eq!(released.request_bytes, 0);
}

#[tokio::test]
async fn reconciliation_is_checked_against_original_request_bounds() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let journal = directory.path().join("local-original-bounds.journal");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("control");

    *driver
        .state
        .run_observation
        .lock()
        .expect("run observation") = DriverRunObservation {
        terminal_observed: false,
        status: DriverTerminalStatus::Indeterminate,
        output: Vec::new(),
        observed_tokens: None,
        usage_units: None,
        stop_reason: Some("lost driver channel".to_string()),
    };
    worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.bounds"),
            &input(),
            &CancellationToken::new(),
        )
        .await
        .expect("unknown run");
    let mut over_limit = success_observation();
    over_limit.observed_tokens = Some(65);
    *driver
        .state
        .reconciliation
        .lock()
        .expect("reconciliation") = DriverReconciliation::Terminal(over_limit);

    assert!(matches!(
        worker
            .run(
                &mut control,
                &grant,
                &manifest,
                &handle,
                admission("request.local.bounds"),
                &input(),
                &CancellationToken::new(),
            )
            .await,
        Err(LocalWorkerError::InvalidObservation(_))
    ));
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.inspections.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn exact_duplicate_and_restart_reconciliation_never_replay_run() {
    let (grant, _) = signed_grant(512);
    let manifest = manifest(&grant);
    let driver = FakeDriver::new();
    let worker = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("worker");
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let journal = directory.path().join("local-control.journal");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("control");
    let cancellation = CancellationToken::new();

    let first = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.1"),
            &input(),
            &cancellation,
        )
        .await
        .expect("first run");
    assert_eq!(first.status, LocalRunStatus::Succeeded);
    assert_eq!(first.observed_tokens, Some(7));
    let duplicate = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.1"),
            &input(),
            &cancellation,
        )
        .await
        .expect("duplicate");
    assert_eq!(duplicate, first);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);

    *driver
        .state
        .run_observation
        .lock()
        .expect("run observation") = DriverRunObservation {
        terminal_observed: false,
        status: DriverTerminalStatus::Indeterminate,
        output: Vec::new(),
        observed_tokens: None,
        usage_units: None,
        stop_reason: Some("lost driver channel".to_string()),
    };
    let unknown = worker
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.2"),
            &input(),
            &cancellation,
        )
        .await
        .expect("unknown run");
    assert_eq!(unknown.status, LocalRunStatus::Indeterminate);
    assert_eq!(unknown.observed_tokens, None);
    drop(control);

    *driver
        .state
        .reconciliation
        .lock()
        .expect("reconciliation") = DriverReconciliation::Terminal(success_observation());
    let restarted = DurableLocalModelWorker::new(
        driver.clone(),
        FakeObserver,
        FixedClock(1_000),
        &grant,
    )
    .expect("restarted worker");
    let mut control = DurableInferenceControl::open(&journal, 64).expect("reopened control");
    let reconciled = restarted
        .run(
            &mut control,
            &grant,
            &manifest,
            &handle,
            admission("request.local.2"),
            &input(),
            &cancellation,
        )
        .await
        .expect("reconciliation");
    assert_eq!(reconciled.status, LocalRunStatus::Succeeded);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 2);
    assert_eq!(driver.state.inspections.load(Ordering::SeqCst), 1);
}
