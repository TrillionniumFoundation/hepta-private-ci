use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Waker;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestResult<T = ()> = Result<T, Box<dyn StdError>>;

const PENDING: usize = 1;
const INDETERMINATE: usize = 2;
const REJECTED: usize = 3;
const NONTERMINAL: usize = 4;
const MISSING_USAGE: usize = 5;

#[derive(Default)]
struct DriverState {
    loads: AtomicUsize,
    runs: AtomicUsize,
    inspections: AtomicUsize,
    unloads: AtomicUsize,
    load_mode: AtomicUsize,
    run_mode: AtomicUsize,
    unload_mode: AtomicUsize,
}

impl DriverState {
    fn counts(&self) -> [usize; 4] {
        [
            self.loads.load(Ordering::SeqCst),
            self.runs.load(Ordering::SeqCst),
            self.inspections.load(Ordering::SeqCst),
            self.unloads.load(Ordering::SeqCst),
        ]
    }
}

#[derive(Clone, Default)]
struct TestDriver(Arc<DriverState>);

impl LocalModelDriver for TestDriver {
    fn load<'a>(
        &'a self,
        _operation: &'a OperationId,
        manifest: &'a VerifiedModelManifest,
        _grant: &'a VerifiedResourceGrant,
        _cancellation: &'a CancellationToken,
        _deadline: TrustedDeadline,
    ) -> DriverFuture<'a, UnverifiedModelHandle> {
        Box::pin(async move {
            self.0.loads.fetch_add(1, Ordering::SeqCst);
            match self.0.load_mode.load(Ordering::SeqCst) {
                PENDING => std::future::pending().await,
                INDETERMINATE => Err(DriverError::Indeterminate(
                    "load acknowledgement lost".to_string(),
                )),
                REJECTED => Err(DriverError::Rejected("load refused".to_string())),
                _ => Ok(UnverifiedModelHandle {
                    opaque_id: "handle".to_string(),
                    model_digest: manifest.envelope.model_digest.clone(),
                    device_id: manifest.envelope.device_id.clone(),
                    observed_memory_bytes: manifest.envelope.maximum_memory_bytes / 2,
                    attestation_digest: "a".repeat(64),
                    terminal_observed: self.0.load_mode.load(Ordering::SeqCst) != NONTERMINAL,
                }),
            }
        })
    }

    fn run<'a>(
        &'a self,
        _operation: &'a OperationId,
        handle: &'a AttestedModelHandle,
        _input: VerifiedInput,
        _cancellation: &'a CancellationToken,
        _deadline: TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunObservation> {
        Box::pin(async move {
            self.0.runs.fetch_add(1, Ordering::SeqCst);
            match self.0.run_mode.load(Ordering::SeqCst) {
                PENDING => std::future::pending().await,
                INDETERMINATE => Err(DriverError::Indeterminate(
                    "run acknowledgement lost".to_string(),
                )),
                REJECTED => Err(DriverError::Rejected("run refused".to_string())),
                NONTERMINAL => Ok(DriverRunObservation {
                    terminal_observed: false,
                    status: DriverTerminalStatus::Succeeded,
                    output_digest: None,
                    observed_usage_tokens: None,
                    observed_memory_bytes: handle.observed_memory_bytes,
                    attestation_digest: "b".repeat(64),
                }),
                mode => Ok(DriverRunObservation {
                    terminal_observed: true,
                    status: DriverTerminalStatus::Succeeded,
                    output_digest: Some("c".repeat(64)),
                    observed_usage_tokens: if mode == MISSING_USAGE { None } else { Some(7) },
                    observed_memory_bytes: handle.observed_memory_bytes,
                    attestation_digest: "b".repeat(64),
                }),
            }
        })
    }

    fn inspect<'a>(
        &'a self,
        _operation: &'a OperationId,
    ) -> DriverFuture<'a, DriverReconciliation> {
        Box::pin(async move {
            self.0.inspections.fetch_add(1, Ordering::SeqCst);
            Ok(DriverReconciliation::Unknown)
        })
    }

    fn unload<'a>(
        &'a self,
        _operation: &'a OperationId,
        handle: &'a AttestedModelHandle,
        _cancellation: &'a CancellationToken,
        _deadline: TrustedDeadline,
    ) -> DriverFuture<'a, DriverUnloadObservation> {
        Box::pin(async move {
            self.0.unloads.fetch_add(1, Ordering::SeqCst);
            match self.0.unload_mode.load(Ordering::SeqCst) {
                PENDING => std::future::pending().await,
                INDETERMINATE => Err(DriverError::Indeterminate(
                    "unload acknowledgement lost".to_string(),
                )),
                REJECTED => Err(DriverError::Rejected("unload refused".to_string())),
                _ => Ok(DriverUnloadObservation {
                    terminal_observed: true,
                    opaque_id: handle.opaque_id.clone(),
                    released_memory_bytes: handle.observed_memory_bytes,
                    attestation_digest: "d".repeat(64),
                }),
            }
        })
    }
}

fn claims() -> TestResult<ResourceGrantClaims> {
    let now = unix_time_ms()?;
    Ok(ResourceGrantClaims {
        schema_version: GRANT_SCHEMA,
        issuer_id: "issuer".to_string(),
        authority_epoch: 1,
        grant_id: "grant".to_string(),
        nonce: "nonce".to_string(),
        worker_subject: "worker".to_string(),
        worker_generation: 1,
        model_id: "model".to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_id: "device".to_string(),
        device_lease_id: "lease".to_string(),
        maximum_model_memory_bytes: 256,
        maximum_aggregate_memory_bytes: 1_024,
        maximum_models: 2,
        maximum_concurrency: 2,
        maximum_tokens_per_request: 128,
        maximum_total_usage_tokens: 1_000,
        not_before_unix_ms: now.saturating_sub(1),
        expires_at_unix_ms: now + 60_000,
        revocation_revision: 1,
        revocation_head_digest: "7".repeat(64),
        semantic_digest: String::new(),
    })
}

fn signed(mut claims: ResourceGrantClaims) -> SignedResourceGrant {
    claims.semantic_digest = claims.expected_semantic_digest();
    let key = SigningKey::from_bytes(&[7; 32]);
    let signature = key.sign(&claims.signing_bytes()).to_bytes().to_vec();
    SignedResourceGrant { claims, signature }
}

fn verifier(
    claims: &ResourceGrantClaims,
    revoked: BTreeSet<String>,
) -> TestResult<ResourceGrantVerifier> {
    Ok(ResourceGrantVerifier::new(
        claims.issuer_id.clone(),
        SigningKey::from_bytes(&[7; 32]).verifying_key().to_bytes(),
        ResourceRevocationHead {
            authority_epoch: claims.authority_epoch,
            revision: claims.revocation_revision,
            head_digest: claims.revocation_head_digest.clone(),
            revoked_grant_ids: revoked,
        },
    )?)
}

fn verified(claims: ResourceGrantClaims) -> TestResult<VerifiedResourceGrant> {
    Ok(verifier(&claims, BTreeSet::new())?.verify(signed(claims))?)
}

fn manifest(grant: &VerifiedResourceGrant) -> TestResult<VerifiedModelManifest> {
    let claims = grant.claims();
    let mut envelope = ModelManifestEnvelope {
        schema_version: MANIFEST_SCHEMA,
        model_id: claims.model_id.clone(),
        model_digest: claims.model_digest.clone(),
        weights_digest: claims.weights_digest.clone(),
        tokenizer_digest: claims.tokenizer_digest.clone(),
        preprocessor_digest: claims.preprocessor_digest.clone(),
        quantization_digest: claims.quantization_digest.clone(),
        runtime_digest: claims.runtime_digest.clone(),
        device_id: claims.device_id.clone(),
        device_lease_id: claims.device_lease_id.clone(),
        maximum_memory_bytes: 256,
        manifest_digest: String::new(),
    };
    envelope.manifest_digest = envelope.expected_digest();
    Ok(VerifiedModelManifest::verify(envelope, grant)?)
}

fn input(grant: &VerifiedResourceGrant) -> TestResult<VerifiedInput> {
    let bytes = b"test".to_vec();
    Ok(VerifiedInput::verify(
        bytes.clone(),
        &digest(&bytes),
        16,
        grant,
    )?)
}

fn deadline() -> TestResult<TrustedDeadline> {
    Ok(TrustedDeadline::from_absolute_unix_ms(
        unix_time_ms()? + 60_000,
    )?)
}

struct Fixture {
    // Drop the journal owner before removing the temporary directory.
    worker: ExperimentalLocalModelWorker<TestDriver>,
    grant: VerifiedResourceGrant,
    driver: TestDriver,
    _directory: tempfile::TempDir,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let grant = verified(claims()?)?;
        let resources = ResourceManager::from_grant(&grant)?;
        let directory = tempfile::tempdir()?;
        let control = DurableInferenceControl::open(directory.path().join("control.log"), 64)?;
        let driver = TestDriver::default();
        let worker = ExperimentalLocalModelWorker::new(
            "worker".to_string(),
            1,
            8,
            driver.clone(),
            control,
            resources,
        )?;
        Ok(Self {
            worker,
            grant,
            driver,
            _directory: directory,
        })
    }

    async fn load(&self) -> TestResult<AttestedModelHandle> {
        Ok(self
            .worker
            .load_model(
                OperationId::parse("load")?,
                manifest(&self.grant)?,
                &self.grant,
                &CancellationToken::new(),
                deadline()?,
            )
            .await?)
    }

    fn record(
        &self,
        request: &str,
    ) -> TestResult<Option<codex_hepta_infer_core::durable_control::native::NativeRunRecord>> {
        let control = self
            .worker
            .control
            .lock()
            .map_err(|_| "test journal lock poisoned")?;
        Ok(control.native_record(request).cloned())
    }
}

fn assert_pending_once<F: Future>(future: Pin<&mut F>) {
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.poll(&mut context).is_pending());
}
