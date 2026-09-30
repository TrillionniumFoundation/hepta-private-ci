use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::tempdir;
use tokio_util::sync::CancellationToken;

use super::*;

#[derive(Clone)]
struct MutableClock(Arc<AtomicU64>);

impl MutableClock {
    fn new(now_ms: u64) -> Self {
        Self(Arc::new(AtomicU64::new(now_ms)))
    }
}

impl TrustedClock for MutableClock {
    fn now_ms(&self) -> Result<u64, LocalWorkerError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

#[derive(Clone)]
struct MutableAuthority {
    snapshot: Arc<Mutex<TrustedAuthoritySnapshot>>,
}

impl MutableAuthority {
    fn new(snapshot: TrustedAuthoritySnapshot) -> Self {
        Self {
            snapshot: Arc::new(Mutex::new(snapshot)),
        }
    }

    fn update(&self, update: impl FnOnce(&mut TrustedAuthoritySnapshot)) {
        let mut snapshot = self.snapshot.lock().expect("authority snapshot");
        update(&mut snapshot);
        snapshot.revocation_head_digest = digest(
            &serde_json::to_vec(&(
                "hepta.local-resource-revocations.v1",
                snapshot.authority_epoch,
                snapshot.revocation_revision,
                &snapshot.revoked_grant_ids,
            ))
            .expect("frontier encoding"),
        );
        snapshot.snapshot_digest = snapshot.expected_snapshot_digest().expect("snapshot digest");
    }
}

impl TrustedAuthorityProvider for MutableAuthority {
    fn observe<'a>(
        &'a self,
        _grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, TrustedAuthoritySnapshot> {
        let snapshot = self.snapshot.lock().expect("authority snapshot").clone();
        Box::pin(async move { Ok(snapshot) })
    }
}

#[derive(Clone)]
struct HardenedDriver {
    state: Arc<HardenedDriverState>,
}

struct HardenedDriverState {
    loads: AtomicUsize,
    runs: AtomicUsize,
    interrupts: AtomicUsize,
    inspections: AtomicUsize,
    hang_run: AtomicBool,
    interrupt_result: Mutex<DriverReconciliation>,
    inspect_result: Mutex<DriverReconciliation>,
}

impl HardenedDriver {
    fn new() -> Self {
        Self {
            state: Arc::new(HardenedDriverState {
                loads: AtomicUsize::new(0),
                runs: AtomicUsize::new(0),
                interrupts: AtomicUsize::new(0),
                inspections: AtomicUsize::new(0),
                hang_run: AtomicBool::new(false),
                interrupt_result: Mutex::new(DriverReconciliation::Pending {
                    observed_tokens: None,
                    usage_units: None,
                }),
                inspect_result: Mutex::new(DriverReconciliation::MissingHistory),
            }),
        }
    }
}

impl LocalModelDriver for HardenedDriver {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        _grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, DriverLoadObservation> {
        let sequence = self.state.loads.fetch_add(1, Ordering::SeqCst) + 1;
        let manifest = manifest.as_manifest().clone();
        Box::pin(async move {
            Ok(DriverLoadObservation {
                handle_id: format!("hardened.handle.{sequence}"),
                model_digest: manifest.model_digest,
                weights_digest: manifest.weights_digest,
                runtime_digest: manifest.runtime_digest,
                device_uuid: manifest.device_uuid,
                driver_reported_memory_bytes: 100,
            })
        })
    }

    fn cleanup_failed_load<'a>(
        &'a self,
        _load: &'a DriverLoadObservation,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
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
        if self.state.hang_run.load(Ordering::SeqCst) {
            Box::pin(std::future::pending())
        } else {
            Box::pin(async move { Ok(success_observation()) })
        }
    }

    fn interrupt<'a>(
        &'a self,
        _operation_id: &'a str,
        _handle: &'a AttestedModelHandle,
        _reason: DriverInterruptReason,
    ) -> LocalFuture<'a, DriverReconciliation> {
        self.state.interrupts.fetch_add(1, Ordering::SeqCst);
        let result = self
            .state
            .interrupt_result
            .lock()
            .expect("interrupt result")
            .clone();
        Box::pin(async move { Ok(result) })
    }

    fn inspect<'a>(
        &'a self,
        _operation_id: &'a str,
        _handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverReconciliation> {
        self.state.inspections.fetch_add(1, Ordering::SeqCst);
        let result = self
            .state
            .inspect_result
            .lock()
            .expect("inspect result")
            .clone();
        Box::pin(async move { Ok(result) })
    }

    fn unload<'a>(
        &'a self,
        _handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, DriverUnloadObservation> {
        Box::pin(async move {
            Ok(DriverUnloadObservation {
                terminal_observed: true,
                released_memory_bytes: Some(100),
            })
        })
    }
}

#[derive(Clone, Copy)]
struct HardenedObserver;

impl TrustedResourceObserver for HardenedObserver {
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
                attestation_digest: digest(b"hardened-resource-attestation"),
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
                attestation_digest: digest(b"hardened-unattested-release"),
            })
        })
    }

    fn observe_release<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> LocalFuture<'a, TrustedReleaseObservation> {
        let handle_id = handle.handle_id().to_string();
        let device_uuid = handle.device_uuid().to_string();
        let worker_generation = handle.worker_generation();
        let device_epoch = handle.device_epoch();
        Box::pin(async move {
            Ok(TrustedReleaseObservation {
                observer_id: "trusted.os.observer".to_string(),
                handle_id,
                worker_generation,
                device_uuid,
                device_epoch,
                resident_memory_bytes: 0,
                attestation_digest: digest(b"hardened-release"),
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

fn grant_and_snapshot(now_ms: u64) -> (VerifiedResourceGrant, TrustedAuthoritySnapshot) {
    let signing_key = SigningKey::from_bytes(&[19_u8; 32]);
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
    let verifier = ResourceGrantVerifier::from_trusted_parts(
        "trusted.local.issuer".to_string(),
        signing_key.verifying_key().to_bytes(),
        TrustedRevocationFrontier {
            authority_epoch: 5,
            revision: 8,
            head_digest: frontier_digest.clone(),
            revoked_grant_ids: revoked,
        },
    )
    .expect("verifier");
    let mut claims = ResourceGrantClaims {
        schema_version: 1,
        issuer: "trusted.local.issuer".to_string(),
        authority_epoch: 5,
        grant_id: "grant.hardened.1".to_string(),
        nonce: "nonce.hardened.1".to_string(),
        worker_subject: "worker.hardened.1".to_string(),
        worker_generation: 2,
        model_id: "model.hardened.1".to_string(),
        model_digest: digest(b"model"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_digest: digest(b"quantization"),
        runtime_digest: digest(b"runtime"),
        device_uuid: "device.hardened.1".to_string(),
        device_lease_digest: digest(b"device-lease"),
        device_epoch: 3,
        maximum_aggregate_memory_bytes: 512,
        maximum_concurrency: 2,
        maximum_tokens: 128,
        maximum_usage_units: 1_000,
        issued_at_ms: 500,
        expires_at_ms: 20_000,
        revocation_revision: 8,
        revocation_head_digest: frontier_digest.clone(),
        semantic_digest: String::new(),
    };
    let mut semantic = claims.clone();
    semantic.semantic_digest.clear();
    claims.semantic_digest = digest(&serde_json::to_vec(&semantic).expect("grant semantic"));
    let signature = signing_key
        .sign(&claims.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let grant = verifier
        .verify(
            SignedResourceGrant { claims, signature },
            &MutableClock::new(now_ms),
        )
        .expect("verified grant");
    let claims = grant.claims();
    let mut snapshot = TrustedAuthoritySnapshot {
        schema_version: AUTHORITY_SNAPSHOT_SCHEMA_VERSION,
        issuer: claims.issuer.clone(),
        grant_id: claims.grant_id.clone(),
        worker_subject: claims.worker_subject.clone(),
        worker_generation: claims.worker_generation,
        authority_epoch: claims.authority_epoch,
        revocation_revision: claims.revocation_revision,
        revocation_head_digest: claims.revocation_head_digest.clone(),
        revoked_grant_ids: BTreeSet::new(),
        grant_witness_digest: grant.witness_digest().to_string(),
        provider_witness_digest: digest(b"live-authority-provider-witness"),
        observed_at_unix_ms: now_ms,
        snapshot_digest: String::new(),
    };
    snapshot.snapshot_digest = snapshot.expected_snapshot_digest().expect("snapshot digest");
    (grant, snapshot)
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

fn input() -> VerifiedInput {
    let bytes = b"prompt".to_vec();
    let expected = digest(&bytes);
    VerifiedInput::verify(bytes, &expected, 1024).expect("verified input")
}

fn admission(id: &str) -> LocalRunAdmission {
    LocalRunAdmission {
        request_id: id.to_string(),
        maximum_in_flight: 1,
        maximum_tokens: 64,
        maximum_usage_units: 100,
        expected_transient_memory_bytes: 20,
        requested_deadline_ms: 15_000,
    }
}

#[tokio::test]
async fn revoked_live_frontier_blocks_new_physical_effect() {
    let clock = MutableClock::new(1_000);
    let (grant, snapshot) = grant_and_snapshot(1_000);
    let authority = MutableAuthority::new(snapshot);
    let driver = HardenedDriver::new();
    let worker = DurableLocalModelWorker::new_with_authority(
        driver.clone(),
        HardenedObserver,
        clock.clone(),
        authority.clone(),
        &grant,
    )
    .expect("worker");
    let manifest = manifest(&grant);
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    authority.update(|snapshot| {
        snapshot.revocation_revision += 1;
        snapshot.revoked_grant_ids.insert(snapshot.grant_id.clone());
    });

    let directory = tempdir().expect("tempdir");
    let mut control = DurableInferenceControl::open(directory.path().join("control"), 16)
        .expect("control");
    assert_eq!(
        worker
            .run(
                &mut control,
                &grant,
                &manifest,
                &handle,
                admission("request.revoked"),
                &input(),
                &CancellationToken::new(),
            )
            .await,
        Err(LocalWorkerError::GrantRevoked)
    );
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 0);
    assert!(control.native_record("request.revoked").is_none());
}

#[tokio::test]
async fn live_revocation_during_hung_run_interrupts_and_holds_capacity() {
    let clock = MutableClock::new(1_000);
    let (grant, snapshot) = grant_and_snapshot(1_000);
    let authority = MutableAuthority::new(snapshot);
    let driver = HardenedDriver::new();
    driver.state.hang_run.store(true, Ordering::SeqCst);
    let worker = DurableLocalModelWorker::new_with_authority(
        driver.clone(),
        HardenedObserver,
        clock.clone(),
        authority.clone(),
        &grant,
    )
    .expect("worker");
    let manifest = manifest(&grant);
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let mut control = DurableInferenceControl::open(directory.path().join("control"), 16)
        .expect("control");
    let cancellation = CancellationToken::new();
    let verified_input = input();

    let run = worker.run(
        &mut control,
        &grant,
        &manifest,
        &handle,
        admission("request.live-revoked"),
        &verified_input,
        &cancellation,
    );
    let revoke = async {
        tokio::time::sleep(std::time::Duration::from_millis(125)).await;
        authority.update(|snapshot| {
            snapshot.revocation_revision += 1;
            snapshot.revoked_grant_ids.insert(snapshot.grant_id.clone());
        });
    };
    let (result, ()) = tokio::join!(run, revoke);
    let result = result.expect("contained result");
    assert!(result.quarantined);
    assert_eq!(driver.state.runs.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.interrupts.load(Ordering::SeqCst), 1);
    let record = control
        .native_record("request.live-revoked")
        .expect("durable record");
    assert_eq!(record.state, NativeReservationState::Indeterminate);
    assert!(record.authority_observation.is_some());
    assert_eq!(
        control.reserve_native(
            codex_hepta_infer_core::durable_control::native::NativeRequest {
                request_id: "request.next".to_string(),
                principal_id: grant.worker_subject().to_string(),
                worker_generation: grant.worker_generation(),
                model: manifest.model_id().to_string(),
                payload_digest: "f".repeat(64),
            },
            1,
        ),
        Err(codex_hepta_infer_core::durable_control::Error::CapacityExceeded)
    );
}

#[tokio::test]
async fn interrupt_terminal_without_independent_inspect_never_releases() {
    let clock = MutableClock::new(1_000);
    let (grant, snapshot) = grant_and_snapshot(1_000);
    let authority = MutableAuthority::new(snapshot);
    let driver = HardenedDriver::new();
    driver.state.hang_run.store(true, Ordering::SeqCst);
    *driver
        .state
        .interrupt_result
        .lock()
        .expect("interrupt result") = DriverReconciliation::Terminal(DriverRunObservation {
        terminal_observed: true,
        status: DriverTerminalStatus::Interrupted,
        output: Vec::new(),
        observed_tokens: Some(2),
        usage_units: Some(3),
        stop_reason: Some("interrupt acknowledged".to_string()),
    });
    *driver.state.inspect_result.lock().expect("inspect result") =
        DriverReconciliation::MissingHistory;
    let worker = DurableLocalModelWorker::new_with_authority(
        driver.clone(),
        HardenedObserver,
        clock,
        authority,
        &grant,
    )
    .expect("worker");
    let manifest = manifest(&grant);
    let handle = worker
        .load_model(&grant, &manifest)
        .await
        .expect("model");
    let directory = tempdir().expect("tempdir");
    let mut control = DurableInferenceControl::open(directory.path().join("control"), 16)
        .expect("control");
    let cancellation = CancellationToken::new();
    let verified_input = input();
    let run = worker.run(
        &mut control,
        &grant,
        &manifest,
        &handle,
        admission("request.interrupt-inspect"),
        &verified_input,
        &cancellation,
    );
    let cancel = async {
        tokio::task::yield_now().await;
        cancellation.cancel();
    };
    let (result, ()) = tokio::join!(run, cancel);
    let result = result.expect("contained result");
    assert!(result.quarantined);
    assert_eq!(driver.state.interrupts.load(Ordering::SeqCst), 1);
    assert_eq!(driver.state.inspections.load(Ordering::SeqCst), 1);
    assert_eq!(
        control
            .native_record("request.interrupt-inspect")
            .expect("record")
            .state,
        NativeReservationState::Indeterminate
    );
}
