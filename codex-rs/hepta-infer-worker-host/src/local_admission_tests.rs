use super::*;
use std::collections::BTreeSet;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct TestClock(AtomicU64);

impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> std::result::Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

// This memory-only oracle is a test fixture, not production anti-rollback.
struct TestFrontier(Mutex<FinalUseFrontier>);

impl AuthorityFrontierStore<FinalUseFrontier> for TestFrontier {
    fn load(&self, owner_id: &str) -> std::result::Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != "local-issuer" {
            return Err(AuthorityTrustError::Invalid);
        }
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> std::result::Result<(), AuthorityTrustError> {
        if owner_id != "local-issuer" {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut current = self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *current != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

struct Fixture {
    verifier: LocalAdmissionVerifier,
    clock: Arc<TestClock>,
    frontier: Arc<TestFrontier>,
    signing: SigningKey,
    _root: tempfile::TempDir,
}

fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}

fn fixture() -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let signing = SigningKey::from_bytes(&[7; 32]);
    let clock = Arc::new(TestClock(AtomicU64::new(1_000)));
    let frontier = Arc::new(TestFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&head()).unwrap(),
    )));
    let verifier = LocalAdmissionVerifier::open(
        LocalAuthorityConfig {
            state_directory: root.path().canonicalize().unwrap().join("authority"),
            signer_id: "local-issuer".to_string(),
            verifying_key: signing.verifying_key().to_bytes(),
            revocations: head(),
            worker_id: "worker-1".to_string(),
            worker_generation: 3,
            device_lease_id: "device-lease-1".to_string(),
        },
        clock.clone(),
        frontier.clone(),
    )
    .unwrap();
    Fixture {
        verifier,
        clock,
        frontier,
        signing,
        _root: root,
    }
}

fn request(input: &[u8]) -> LocalAdmissionRequest {
    LocalAdmissionRequest {
        operation_id: "operation-1".to_string(),
        operation: LocalOperationKind::RunModel,
        worker_id: "worker-1".to_string(),
        worker_generation: 3,
        device_lease_id: "device-lease-1".to_string(),
        manifest: ModelManifest {
            model_id: "model-1".to_string(),
            model_digest: "1".repeat(64),
            weights_digest: "2".repeat(64),
            tokenizer_digest: "3".repeat(64),
            preprocessor_digest: "4".repeat(64),
            quantization_digest: "5".repeat(64),
            runtime_digest: "6".repeat(64),
            device_digest: "7".repeat(64),
            maximum_tokens: 128,
            maximum_resident_bytes: 1_024,
        },
        limits: LocalResourceLimits {
            maximum_aggregate_memory_bytes: 8_192,
            maximum_models: 2,
            maximum_active_requests: 4,
            maximum_tokens: 64,
            maximum_kv_bytes: 1_024,
            maximum_transient_bytes: 1_024,
        },
        input_sha256: Sha256::digest(input).into(),
        deadline_unix_ms: 5_000,
    }
}

fn sign(key: &SigningKey, request: &LocalAdmissionRequest) -> SignedFinalUseGrant {
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "local-issuer".to_string(),
        authority_epoch: 1,
        grant_id: "grant-1".to_string(),
        nonce: [1; 32],
        binding: request.binding().unwrap(),
        not_before_unix_ms: 900,
        expires_at_unix_ms: 6_000,
    };
    let signature = key
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[test]
fn exact_kernel_claim_retains_verified_input_manifest_and_witness() {
    let fixture = fixture();
    let input = b"actual local input".to_vec();
    let request = request(&input);
    let signed = sign(&fixture.signing, &request);
    let verified = fixture
        .verifier
        .claim(request.clone(), &signed, input.clone())
        .unwrap();
    assert_eq!(verified.manifest().manifest(), &request.manifest);
    assert_eq!(verified.input().as_bytes(), input.as_slice());
    assert_eq!(verified.input().sha256(), request.input_sha256);
    assert_eq!(verified.limits(), &request.limits);
    assert_eq!(verified.binding(), &signed.grant.binding);
    assert_eq!(
        verified.deadline().absolute_unix_ms(),
        request.deadline_unix_ms
    );
    assert!(verified.deadline().remaining().unwrap() <= Duration::from_millis(4_000));
    assert!(verified.check_live().is_ok());
    let witness = verified.witness();
    assert_eq!(witness.semantic_sha256, signed.grant.binding.request_sha256);
    assert_ne!(witness.authority_witness_sha256, [0; 32]);
    assert!(fixture.verifier.claim(request, &signed, input).is_err());
}

#[test]
fn forged_signature_and_changed_input_never_claim_the_legitimate_nonce() {
    let fixture = fixture();
    let input = b"payload".to_vec();
    let request = request(&input);
    let signed = sign(&fixture.signing, &request);
    let forged = sign(&SigningKey::from_bytes(&[9; 32]), &request);
    assert!(
        fixture
            .verifier
            .claim(request.clone(), &forged, input.clone())
            .is_err()
    );
    assert!(matches!(
        fixture
            .verifier
            .claim(request.clone(), &signed, b"changed".to_vec()),
        Err(LocalAdmissionError::InputMismatch)
    ));
    assert!(fixture.verifier.claim(request, &signed, input).is_ok());
}

#[test]
fn every_resource_model_and_operation_field_is_bound_to_the_signature() {
    type Mutation = fn(&mut LocalAdmissionRequest);
    let mutations: &[Mutation] = &[
        |value| value.operation_id.push_str("-other"),
        |value| value.operation = LocalOperationKind::LoadModel,
        |value| value.worker_id.push_str("-other"),
        |value| value.worker_generation += 1,
        |value| value.device_lease_id.push_str("-other"),
        |value| value.manifest.model_id.push_str("-other"),
        |value| value.manifest.model_digest = "a".repeat(64),
        |value| value.manifest.weights_digest = "a".repeat(64),
        |value| value.manifest.tokenizer_digest = "a".repeat(64),
        |value| value.manifest.preprocessor_digest = "a".repeat(64),
        |value| value.manifest.quantization_digest = "a".repeat(64),
        |value| value.manifest.runtime_digest = "a".repeat(64),
        |value| value.manifest.device_digest = "a".repeat(64),
        |value| value.manifest.maximum_resident_bytes += 1,
        |value| value.manifest.maximum_tokens += 1,
        |value| value.limits.maximum_aggregate_memory_bytes += 1,
        |value| value.limits.maximum_models += 1,
        |value| value.limits.maximum_active_requests += 1,
        |value| value.limits.maximum_tokens += 1,
        |value| value.limits.maximum_kv_bytes += 1,
        |value| value.limits.maximum_transient_bytes += 1,
        |value| value.input_sha256 = [8; 32],
        |value| value.deadline_unix_ms += 1,
    ];
    let fixture = fixture();
    let input = b"payload".to_vec();
    let original = request(&input);
    let signed = sign(&fixture.signing, &original);
    for (index, change) in mutations.iter().enumerate() {
        let mut changed = original.clone();
        change(&mut changed);
        assert_ne!(
            changed.binding().unwrap(),
            signed.grant.binding,
            "field {index}"
        );
        assert!(
            fixture
                .verifier
                .claim(changed, &signed, input.clone())
                .is_err()
        );
    }
    assert!(fixture.verifier.claim(original, &signed, input).is_ok());
}

#[test]
fn correctly_signed_other_worker_generation_or_device_is_still_denied() {
    let fixture = fixture();
    for index in 0..3 {
        let mut request = request(b"payload");
        match index {
            0 => request.worker_id = "other-worker".to_string(),
            1 => request.worker_generation += 1,
            _ => request.device_lease_id = "other-device".to_string(),
        }
        let signed = sign(&fixture.signing, &request);
        assert!(matches!(
            fixture
                .verifier
                .claim(request, &signed, b"payload".to_vec()),
            Err(LocalAdmissionError::InvalidRequest)
        ));
    }
}

#[test]
fn rollback_fences_the_shared_clock_and_cannot_be_cleared_by_time_advancing() {
    let fixture = fixture();
    let request = request(b"payload");
    let signed = sign(&fixture.signing, &request);
    let verified = fixture
        .verifier
        .claim(request, &signed, b"payload".to_vec())
        .unwrap();
    fixture.clock.0.store(999, Ordering::SeqCst);
    assert!(matches!(
        verified.check_live(),
        Err(LocalAdmissionError::Trust(AuthorityTrustError::Conflict))
    ));
    fixture.clock.0.store(1_001, Ordering::SeqCst);
    assert!(matches!(
        verified.check_live(),
        Err(LocalAdmissionError::Trust(AuthorityTrustError::Unavailable))
    ));
}

#[test]
fn wall_and_monotonic_expiry_each_fence_an_existing_claim() {
    for monotonic in [false, true] {
        let fixture = fixture();
        let request = request(b"payload");
        let signed = sign(&fixture.signing, &request);
        let mut verified = fixture
            .verifier
            .claim(request, &signed, b"payload".to_vec())
            .unwrap();
        if monotonic {
            verified.deadline.monotonic = Instant::now();
        } else {
            fixture.clock.0.store(5_000, Ordering::SeqCst);
        }
        assert!(matches!(
            verified.check_live(),
            Err(LocalAdmissionError::DeadlineElapsed)
        ));
    }
}

#[test]
fn revocation_update_invalidates_prepared_claim_without_a_new_effect() {
    let fixture = fixture();
    let request = request(b"payload");
    let signed = sign(&fixture.signing, &request);
    let verified = fixture
        .verifier
        .claim(request, &signed, b"payload".to_vec())
        .unwrap();
    let mut revoked = head();
    revoked.revision += 1;
    revoked.revoked_grant_ids.insert("grant-1".to_string());
    fixture.verifier.update_revocations(revoked).unwrap();
    assert!(matches!(
        verified.check_live(),
        Err(LocalAdmissionError::Authority(
            FinalUseError::StaleRevocationHead
        ))
    ));
    assert!(fixture.verifier.update_revocations(head()).is_err());
}

#[test]
fn resource_overflow_and_budget_violation_are_rejected_before_claim() {
    let fixture = fixture();
    let input = b"payload".to_vec();
    let original = request(&input);
    let signed = sign(&fixture.signing, &original);
    let mut overflow = original.clone();
    overflow.limits.maximum_kv_bytes = u64::MAX;
    assert!(matches!(
        fixture.verifier.claim(overflow, &signed, input.clone()),
        Err(LocalAdmissionError::ArithmeticOverflow)
    ));
    let mut over_budget = original.clone();
    over_budget.limits.maximum_aggregate_memory_bytes = 2_000;
    assert!(matches!(
        fixture.verifier.claim(over_budget, &signed, input.clone()),
        Err(LocalAdmissionError::InvalidRequest)
    ));
    assert!(fixture.verifier.claim(original, &signed, input).is_ok());
}

#[test]
fn external_frontier_conflict_cannot_produce_a_verified_grant() {
    let fixture = fixture();
    let request = request(b"payload");
    let signed = sign(&fixture.signing, &request);
    fixture.frontier.0.lock().unwrap().state_sha256 = [8; 32];
    assert!(
        fixture
            .verifier
            .claim(request, &signed, b"payload".to_vec())
            .is_err()
    );
}

#[test]
fn claimed_nonce_survives_verifier_reopen_with_the_same_external_frontier() {
    let Fixture {
        verifier,
        clock,
        frontier,
        signing,
        _root: root,
    } = fixture();
    let request = request(b"payload");
    let signed = sign(&signing, &request);
    let verified = verifier
        .claim(request.clone(), &signed, b"payload".to_vec())
        .unwrap();
    drop(verified);
    drop(verifier);
    let reopened = LocalAdmissionVerifier::open(
        LocalAuthorityConfig {
            state_directory: root.path().canonicalize().unwrap().join("authority"),
            signer_id: "local-issuer".to_string(),
            verifying_key: signing.verifying_key().to_bytes(),
            revocations: head(),
            worker_id: "worker-1".to_string(),
            worker_generation: 3,
            device_lease_id: "device-lease-1".to_string(),
        },
        clock,
        frontier,
    )
    .unwrap();
    assert!(
        reopened
            .claim(request, &signed, b"payload".to_vec())
            .is_err()
    );
}
