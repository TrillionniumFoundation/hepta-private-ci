use super::super::digest_bytes;
use super::*;
use crate::FinalUseProductionOutboxTarget;
use crate::PRODUCTION_DURABLE_WRITER_NAMESPACE;
use crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
use crate::ProductionDispatchFuture;
use crate::ProductionOutboxTarget;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tempfile::TempDir;

struct TestClock(AtomicU64);

impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct Fixture {
    _directory: TempDir,
    authority: FinalUseAuthority,
    clock: Arc<TestClock>,
    signed: SignedFinalUseGrant,
    request: ProductionDispatchRequest,
}

impl Fixture {
    fn new() -> Self {
        let directory = TempDir::new().expect("private authority directory");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
                .expect("private permissions");
        }
        let issuer = SigningKey::from_bytes(&[113; 32]);
        let clock = Arc::new(TestClock(AtomicU64::new(1_000)));
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "verified-dispatch-issuer".to_owned(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )
        .expect("actual durable FinalUse authority");
        let request = ProductionDispatchRequest {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_owned(),
            lease_id: "original-source-lease".to_owned(),
            occurrence_key: "original-effect".to_owned(),
            topic: "original-topic".to_owned(),
            payload_json: "original-payload".to_owned(),
            payload_sha256: Sha256Digest::for_bytes(b"original-payload"),
            idempotency_key: "original-effect".to_owned(),
            operation_scope_sha256: Sha256Digest::for_bytes(b"original-scope"),
            operation_subject_id: "original-subject".to_owned(),
            operation_destination_id: "original-destination".to_owned(),
            operation_semantic_sha256: Sha256Digest::for_bytes(b"original-semantic"),
            operation_policy_generation: 1,
            expected_predecessor_sha256: None,
            operation_digest: Sha256Digest::for_bytes(b"original-source-verified-operation"),
        };
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "verified-dispatch-issuer".to_owned(),
            authority_epoch: 1,
            grant_id: "original-grant".to_owned(),
            nonce: [17; 32],
            binding: FinalUseBinding {
                subject_id: request.operation_subject_id.clone(),
                destination_id: request.operation_destination_id.clone(),
                request_sha256: digest_bytes(&request.operation_digest).expect("request digest"),
                scope_sha256: digest_bytes(&request.operation_scope_sha256).expect("scope"),
                payload_sha256: digest_bytes(&request.payload_sha256).expect("payload"),
            },
            not_before_unix_ms: 900,
            expires_at_unix_ms: 2_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        Self {
            _directory: directory,
            authority,
            clock,
            signed: SignedFinalUseGrant { grant, signature },
            request,
        }
    }

    fn envelope(&self) -> ProductionVerifiedDispatch {
        let expected = self.signed.grant.binding.clone();
        ProductionVerifiedDispatch {
            request: self.request.clone(),
            authority: self.authority.clone(),
            token: self
                .authority
                .claim(&self.signed, &expected)
                .expect("verified one-shot claim"),
            expected,
        }
    }
}

#[test]
fn original_bound_request_crosses_only_its_pinned_authority_once() {
    let fixture = Fixture::new();
    let envelope = fixture.envelope();
    assert_eq!(envelope.request(), &fixture.request);
    assert_eq!(envelope.binding(), &fixture.signed.grant.binding);
    let observed = envelope
        .with_dispatch_boundary(&fixture.authority, Clone::clone)
        .expect("original boundary");
    assert_eq!(observed, fixture.request);
    assert!(matches!(
        fixture
            .authority
            .claim(&fixture.signed, &fixture.signed.grant.binding),
        Err(FinalUseError::AlreadyClaimed)
    ));

    let first = Fixture::new();
    let other = Fixture::new();
    let calls = AtomicUsize::new(0);
    let result = first
        .envelope()
        .with_dispatch_boundary(&other.authority, |_| calls.fetch_add(1, Ordering::SeqCst));
    assert_eq!(result, Err(FinalUseError::BindingMismatch));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn final_boundary_rechecks_expiry_and_revocation_after_preparation() {
    for expired in [false, true] {
        let fixture = Fixture::new();
        let envelope = fixture.envelope();
        let expected_error = if expired {
            fixture.clock.0.store(2_001, Ordering::SeqCst);
            FinalUseError::Expired
        } else {
            fixture
                .authority
                .update_revocations(FinalUseRevocations {
                    authority_epoch: 1,
                    revision: 2,
                    revoked_grant_ids: BTreeSet::from(["original-grant".to_owned()]),
                })
                .expect("trusted revocation");
            FinalUseError::Revoked
        };
        let calls = AtomicUsize::new(0);
        let result = envelope
            .with_dispatch_boundary(&fixture.authority, |_| calls.fetch_add(1, Ordering::SeqCst));
        assert_eq!(result, Err(expected_error));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn owner_preflight_is_non_consuming_and_never_replaces_the_final_live_check() {
    let fixture = Fixture::new();
    let envelope = fixture.envelope();
    let clone = fixture.authority.clone();
    let other_same_key_and_visible_binding = Fixture::new();
    assert_eq!(
        envelope.verify_target_authority(&other_same_key_and_visible_binding.authority),
        Err(FinalUseError::BindingMismatch)
    );
    assert_eq!(envelope.verify_target_authority(&clone), Ok(()));
    assert_eq!(envelope.verify_target_authority(&fixture.authority), Ok(()));
    fixture.clock.0.store(2_001, Ordering::SeqCst);
    assert_eq!(
        envelope.verify_target_authority(&fixture.authority),
        Ok(()),
        "identity alone does not validate the expired grant"
    );
    let calls = AtomicUsize::new(0);
    assert_eq!(
        envelope.with_dispatch_boundary(&clone, |_| calls.fetch_add(1, Ordering::SeqCst)),
        Err(FinalUseError::Expired)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

struct LegacyTarget(AtomicUsize);

impl ProductionOutboxTarget for LegacyTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Committed {
                receipt: "legacy-delivery-only".to_owned(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for LegacyTarget {
    fn destination_id(&self) -> &str {
        "original-destination"
    }
}

#[tokio::test]
async fn compatibility_default_preserves_delivery_and_typed_final_use_errors() {
    let fixture = Fixture::new();
    let target = LegacyTarget(AtomicUsize::new(0));
    let future = target.dispatch_verified(fixture.envelope());
    assert_eq!(
        target.0.load(Ordering::SeqCst),
        0,
        "unpolled future cannot enter legacy target"
    );
    fixture.clock.0.store(2_001, Ordering::SeqCst);
    assert_eq!(future.await, Err(FinalUseError::Expired));
    assert_eq!(target.0.load(Ordering::SeqCst), 0);

    let valid = Fixture::new();
    assert_eq!(
        target.dispatch_verified(valid.envelope()).await,
        Ok(ProductionTargetOutcome::Committed {
            receipt: "legacy-delivery-only".to_owned()
        })
    );
    assert_eq!(target.0.load(Ordering::SeqCst), 1);
}
