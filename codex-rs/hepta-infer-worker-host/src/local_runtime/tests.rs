use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn wall_now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time")
            .as_millis(),
    )
    .expect("time fits")
}

#[derive(Clone)]
struct FixedClock {
    wall_ms: u64,
    monotonic: Instant,
}

impl TrustedClock for FixedClock {
    fn unix_time_ms(&self) -> Result<u64, LocalRuntimeError> {
        Ok(self.wall_ms)
    }

    fn monotonic_now(&self) -> Instant {
        self.monotonic
    }
}

struct TestGrantAuthority;

impl ResourceGrantAuthority for TestGrantAuthority {
    fn claim(
        &self,
        grant: &SignedResourceGrant,
        _canonical_semantic_digest: Digest32,
    ) -> Result<AuthorityVerification, LocalRuntimeError> {
        Ok(AuthorityVerification {
            signer_id: grant.claims.issuer_id.clone(),
            authority_epoch: grant.claims.authority_epoch,
            revocation_revision: grant.claims.revocation_revision,
            witness_digest: digest("grant-witness"),
            replay_protected: true,
        })
    }
}

struct TestArtifactAuthority;

impl ModelArtifactAuthority for TestArtifactAuthority {
    fn attest(
        &self,
        manifest: &ModelManifestClaims,
        _grant: &VerifiedResourceGrant,
        canonical_manifest_digest: Digest32,
    ) -> Result<ArtifactVerification, LocalRuntimeError> {
        Ok(ArtifactVerification {
            witness_digest: digest("artifact-witness"),
            manifest_digest: canonical_manifest_digest,
            device_id: manifest.device_id.clone(),
            runtime_digest: manifest.runtime_digest,
            observed_weight_bytes: manifest.expected_weight_bytes,
            physical_bytes_observed: true,
        })
    }
}

fn verified_tuple(
    maximum_memory_bytes: u64,
) -> (VerifiedResourceGrant, VerifiedModelManifest, u64) {
    let now = wall_now_ms();
    let mut claims = ResourceGrantClaims {
        issuer_id: id("issuer.1"),
        grant_id: id("grant.1"),
        nonce: id("nonce.1"),
        authority_epoch: 4,
        worker_subject: id("worker.subject"),
        worker_generation: generation(7),
        model_digest: digest("model"),
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_id: id("device.1"),
        artifact_descriptor_digest: digest("artifact-descriptor"),
        maximum_aggregate_memory_bytes: maximum_memory_bytes,
        maximum_concurrency: 2,
        maximum_tokens: 256,
        expires_at_ms: now + 60_000,
        revocation_revision: 3,
        revocation_head_digest: digest("revocations"),
        semantic_digest: digest("placeholder"),
        revoked: false,
    };
    claims.semantic_digest = grant_semantic_digest(&claims);
    let grant = GrantVerifier::new(
        TestGrantAuthority,
        FixedClock {
            wall_ms: now,
            monotonic: Instant::now(),
        },
    )
    .verify(SignedResourceGrant {
        claims,
        signature: vec![7; 64],
    })
    .expect("verified grant");
    let manifest = ManifestVerifier::new(TestArtifactAuthority)
        .verify(
            ModelManifestClaims {
                model_id: id("model.1"),
                model_digest: grant.claims().model_digest,
                weights_digest: grant.claims().weights_digest,
                tokenizer_digest: grant.claims().tokenizer_digest,
                preprocessor_digest: grant.claims().preprocessor_digest,
                quantization_digest: grant.claims().quantization_digest,
                runtime_digest: grant.claims().runtime_digest,
                device_id: grant.claims().device_id.clone(),
                artifact_descriptor_digest: grant.claims().artifact_descriptor_digest,
                expected_weight_bytes: 1_024,
                maximum_tokens: 128,
            },
            &grant,
        )
        .expect("verified manifest");
    (grant, manifest, now)
}

fn verified_input(
    grant: &VerifiedResourceGrant,
    manifest: &VerifiedModelManifest,
    now: u64,
    operation: &str,
    request_memory: u64,
) -> VerifiedInput {
    let bytes = b"exact local input".to_vec();
    InputVerifier::new(FixedClock {
        wall_ms: now,
        monotonic: Instant::now(),
    })
    .verify(
        InputEnvelope {
            operation_id: id(operation),
            payload_digest: Digest32::of_bytes(&bytes),
            bytes,
            maximum_tokens: 64,
            deadline_ms: now + 30_000,
            kv_memory_bytes: request_memory,
            transient_memory_bytes: 0,
        },
        grant,
        manifest,
    )
    .expect("verified input")
}

#[derive(Clone, Copy)]
enum DriverMode {
    KnownUsage,
    UnknownUsage,
    UnloadFailure,
}

struct TestDriver {
    mode: DriverMode,
    run_calls: Mutex<u64>,
}

impl TestDriver {
    fn new(mode: DriverMode) -> Self {
        Self {
            mode,
            run_calls: Mutex::new(0),
        }
    }

    fn terminal(&self) -> DriverRunObservation {
        DriverRunObservation {
            terminal_observed: true,
            terminal_status: Some(DriverTerminalStatus::Completed),
            output_digest: Some(digest("output")),
            usage: match self.mode {
                DriverMode::UnknownUsage => TokenUsage::Unknown,
                DriverMode::KnownUsage | DriverMode::UnloadFailure => TokenUsage::Observed {
                    consumed_tokens: 17,
                    usage_units: 17,
                },
            },
            observed_memory_bytes: 1_024,
            observation_digest: digest("terminal-observation"),
        }
    }
}

impl LocalModelDriver for TestDriver {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadedModel> {
        Box::pin(async move {
            Ok(DriverLoadedModel {
                opaque_id: id("handle.1"),
                model_id: manifest.claims().model_id.clone(),
                model_digest: manifest.claims().model_digest,
                device_id: grant.claims().device_id.clone(),
                worker_generation: grant.claims().worker_generation,
                driver_reported_memory_bytes: 1_024,
            })
        })
    }

    fn run<'a>(
        &'a self,
        _handle: &'a AttestedModelHandle,
        _input: &'a VerifiedInput,
        _cancellation: &'a CancellationToken,
        _deadline: &'a TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunObservation> {
        Box::pin(async move {
            let mut calls = self
                .run_calls
                .lock()
                .map_err(|_| LocalRuntimeError::LockPoisoned)?;
            *calls += 1;
            Ok(self.terminal())
        })
    }

    fn inspect<'a>(
        &'a self,
        _operation_id: &'a StableId,
    ) -> DriverFuture<'a, DriverReconciliation> {
        Box::pin(async move { Ok(DriverReconciliation::Terminal(self.terminal())) })
    }

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, UnloadObservation> {
        Box::pin(async move {
            if matches!(self.mode, DriverMode::UnloadFailure) {
                return Err(LocalRuntimeError::Driver(
                    "injected unload failure".to_string(),
                ));
            }
            Ok(UnloadObservation {
                terminal_observed: true,
                released_memory_bytes: handle.observed_memory_bytes(),
                observation_digest: digest("unload"),
            })
        })
    }

    fn discard_unattested<'a>(
        &'a self,
        loaded: DriverLoadedModel,
    ) -> DriverFuture<'a, UnloadObservation> {
        Box::pin(async move {
            Ok(UnloadObservation {
                terminal_observed: true,
                released_memory_bytes: loaded.driver_reported_memory_bytes,
                observation_digest: digest("discard"),
            })
        })
    }
}

struct TestDeviceAuthority;

impl TrustedDeviceAuthority for TestDeviceAuthority {
    fn verify_loaded_model(
        &self,
        loaded: &DriverLoadedModel,
        manifest: &VerifiedModelManifest,
        grant: &VerifiedResourceGrant,
    ) -> Result<DeviceVerification, LocalRuntimeError> {
        Ok(DeviceVerification {
            opaque_id: loaded.opaque_id.clone(),
            model_id: manifest.claims().model_id.clone(),
            model_digest: manifest.claims().model_digest,
            device_id: grant.claims().device_id.clone(),
            worker_generation: grant.claims().worker_generation,
            observed_memory_bytes: 1_024,
            attestation_digest: digest("device-attestation"),
        })
    }

    fn observe_total_memory(
        &self,
        device_id: &StableId,
        worker_generation: Generation,
    ) -> Result<TrustedMemoryObservation, LocalRuntimeError> {
        Ok(TrustedMemoryObservation {
            device_id: device_id.clone(),
            worker_generation,
            observed_total_bytes: 1_024,
            witness_digest: digest("memory-observation"),
        })
    }
}

fn runtime(
    mode: DriverMode,
    grant: &VerifiedResourceGrant,
) -> (
    Arc<TestDriver>,
    LocalInferenceRuntime<TestDriver, TestDeviceAuthority>,
) {
    let driver = Arc::new(TestDriver::new(mode));
    let resources = ResourceManager::new(
        grant.claims().worker_generation,
        grant.claims().device_id.clone(),
        ResourceLimits {
            maximum_models: 2,
            maximum_in_flight: 2,
            maximum_aggregate_memory_bytes: grant.claims().maximum_aggregate_memory_bytes,
        },
    )
    .expect("resources");
    let runtime = LocalInferenceRuntime::new(
        driver.clone(),
        Arc::new(TestDeviceAuthority),
        resources,
        id("worker.1"),
    );
    (driver, runtime)
}

fn journal_path(label: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-local-runtime-{label}-{nonce}.journal"))
}

#[test]
fn forged_semantic_digest_is_rejected() {
    let now = wall_now_ms();
    let mut claims = verified_tuple(4_096).0.claims().clone();
    claims.semantic_digest = digest("forged");
    assert!(matches!(
        GrantVerifier::new(
            TestGrantAuthority,
            FixedClock {
                wall_ms: now,
                monotonic: Instant::now(),
            },
        )
        .verify(SignedResourceGrant {
            claims,
            signature: vec![1; 64],
        }),
        Err(LocalRuntimeError::InvalidGrant("semantic digest"))
    ));
}

#[test]
fn aggregate_memory_is_reserved_before_dispatch() {
    let (grant, manifest, now) = verified_tuple(1_500);
    let resources = ResourceManager::new(
        grant.claims().worker_generation,
        grant.claims().device_id.clone(),
        ResourceLimits {
            maximum_models: 1,
            maximum_in_flight: 1,
            maximum_aggregate_memory_bytes: 1_500,
        },
    )
    .expect("resources");
    let reservation = resources
        .reserve_model(&grant, &manifest)
        .expect("model reserve");
    let handle = AttestedModelHandle::from_verification(
        DeviceVerification {
            opaque_id: id("handle.memory"),
            model_id: manifest.claims().model_id.clone(),
            model_digest: manifest.claims().model_digest,
            device_id: grant.claims().device_id.clone(),
            worker_generation: grant.claims().worker_generation,
            observed_memory_bytes: 1_024,
            attestation_digest: digest("memory-attestation"),
        },
        &manifest,
        &grant,
    )
    .expect("handle");
    reservation.commit(&handle).expect("commit");
    let input = verified_input(&grant, &manifest, now, "operation.memory", 600);
    assert!(matches!(
        resources.reserve_request(&grant, &input, &manifest.claims().model_id),
        Err(LocalRuntimeError::Capacity)
    ));
}

#[tokio::test(flavor = "current_thread")]
async fn duplicate_terminal_request_never_runs_driver_twice() {
    let (grant, manifest, now) = verified_tuple(4_096);
    let input = verified_input(&grant, &manifest, now, "operation.known", 128);
    let (driver, runtime) = runtime(DriverMode::KnownUsage, &grant);
    runtime.load_model(&grant, &manifest).await.expect("load");
    let path = journal_path("known");
    let mut control = DurableInferenceControl::open(&path, 32).expect("control");
    let cancellation = CancellationToken::new();
    let first = runtime
        .run(&mut control, &grant, &manifest, &input, &cancellation)
        .await
        .expect("first run");
    assert!(matches!(
        first,
        LocalRunOutcome::Settled {
            state: RequestState::Completed,
            ..
        }
    ));
    let second = runtime
        .run(&mut control, &grant, &manifest, &input, &cancellation)
        .await
        .expect("duplicate");
    assert!(matches!(
        second,
        LocalRunOutcome::PreviouslySettled {
            state: RequestState::Completed,
            ..
        }
    ));
    assert_eq!(*driver.run_calls.lock().expect("calls"), 1);
    drop(control);
    std::fs::remove_file(path).expect("cleanup");
}

#[tokio::test(flavor = "current_thread")]
async fn missing_usage_is_held_without_replay() {
    let (grant, manifest, now) = verified_tuple(4_096);
    let input = verified_input(&grant, &manifest, now, "operation.unknown", 128);
    let (driver, runtime) = runtime(DriverMode::UnknownUsage, &grant);
    runtime.load_model(&grant, &manifest).await.expect("load");
    let path = journal_path("unknown");
    let mut control = DurableInferenceControl::open(&path, 32).expect("control");
    let cancellation = CancellationToken::new();
    let first = runtime
        .run(&mut control, &grant, &manifest, &input, &cancellation)
        .await
        .expect("first run");
    assert!(matches!(first, LocalRunOutcome::UsagePending { .. }));
    assert_eq!(
        control
            .get(input.operation_id().as_str())
            .expect("record")
            .state,
        RequestState::Assigned
    );
    let second = runtime
        .run(&mut control, &grant, &manifest, &input, &cancellation)
        .await
        .expect("reconcile");
    assert!(matches!(second, LocalRunOutcome::UsagePending { .. }));
    assert_eq!(*driver.run_calls.lock().expect("calls"), 1);
    drop(control);
    std::fs::remove_file(path).expect("cleanup");
}

#[tokio::test(flavor = "current_thread")]
async fn unload_failure_is_retained_as_zombie() {
    let (grant, manifest, _now) = verified_tuple(4_096);
    let (_driver, runtime) = runtime(DriverMode::UnloadFailure, &grant);
    runtime.load_model(&grant, &manifest).await.expect("load");
    assert!(runtime
        .unload_model(&manifest.claims().model_id)
        .await
        .is_err());
    let snapshot = runtime.resource_snapshot().expect("snapshot");
    assert_eq!(snapshot.zombie_count, 1);
    assert_eq!(snapshot.accounted_memory_bytes, 1_024);
}
