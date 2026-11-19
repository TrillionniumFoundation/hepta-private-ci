//! Isolated qualification inputs only; no fixture is a production trust source.

use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct FixtureClock(Option<u64>);

impl AuthorityClock for FixtureClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.0.ok_or(AuthorityTrustError::Unavailable)
    }
}

struct FixtureFrontier {
    state: Mutex<Option<FinalUseFrontier>>,
    commits: AtomicUsize,
}

impl AuthorityFrontierStore<FinalUseFrontier> for FixtureFrontier {
    fn load(&self, owner: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner != "isolated-composition-issuer" {
            return Err(AuthorityTrustError::Invalid);
        }
        self.state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .ok_or(AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner != "isolated-composition-issuer" {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if state.as_ref() != Some(expected) {
            return Err(AuthorityTrustError::Conflict);
        }
        *state = Some(*next);
        self.commits.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    key: SigningKey,
    head: FinalUseRevocations,
    frontier: Arc<FixtureFrontier>,
}

impl Fixture {
    fn new() -> Self {
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::from(["blocked-grant".to_string()]),
        };
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        Self {
            directory,
            key: SigningKey::from_bytes(&[61; 32]),
            frontier: Arc::new(FixtureFrontier {
                state: Mutex::new(Some(FinalUseFrontier::for_initial_head(&head).unwrap())),
                commits: AtomicUsize::new(0),
            }),
            head,
        }
    }

    fn inputs(&self) -> AgentdFinalUseHostInputs {
        AgentdFinalUseHostInputs {
            state_directory: self.directory.path().to_path_buf(),
            signer_id: "isolated-composition-issuer".to_string(),
            issuer_keys: vec![FinalUseIssuerTrustKey {
                key_id: "fixture-key-1".to_string(),
                verifying_key: self.key.verifying_key().to_bytes(),
                not_before_authority_epoch: 8,
                not_after_authority_epoch: 9,
            }],
            revocations: self.head.clone(),
            clock: Arc::new(FixtureClock(Some(10_000))),
            frontier_store: self.frontier.clone(),
        }
    }

    fn grant(&self, mutate: impl FnOnce(&mut FinalUseGrant)) -> SignedFinalUseGrant {
        let mut grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "isolated-composition-issuer".to_string(),
            authority_epoch: 9,
            grant_id: "fixture-grant".to_string(),
            nonce: [7; 32],
            binding: FinalUseBinding {
                subject_id: "fixture-agent".to_string(),
                destination_id: "fixture-target".to_string(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: 9_000,
            expires_at_unix_ms: 20_000,
        };
        mutate(&mut grant);
        let signature = self
            .key
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }
}

#[test]
fn original_authority_uses_the_injected_clock_keyring_and_external_cas() {
    let fixture = Fixture::new();
    let authority = fixture.inputs().open().unwrap();
    let grant = fixture.grant(|_| {});
    let token = authority.claim(&grant, &grant.grant.binding).unwrap();
    assert_eq!(fixture.frontier.commits.load(Ordering::SeqCst), 1);
    assert!(
        token
            .enter(&grant.grant.binding)
            .unwrap()
            .matches(&grant.grant.binding)
    );
    assert_eq!(
        authority.claim(&grant, &grant.grant.binding).err(),
        Some(FinalUseError::AlreadyClaimed)
    );
}

#[test]
fn missing_clock_keyring_or_external_frontier_has_no_compatibility_fallback() {
    let fixture = Fixture::new();
    let mut inputs = fixture.inputs();
    inputs.clock = Arc::new(FixtureClock(None));
    assert_eq!(inputs.open().err(), Some(FinalUseError::Unavailable));
    let mut inputs = fixture.inputs();
    inputs.issuer_keys.clear();
    assert_eq!(inputs.open().err(), Some(FinalUseError::InvalidTrust));
    *fixture.frontier.state.lock().unwrap() = None;
    assert_eq!(
        fixture.inputs().open().err(),
        Some(FinalUseError::Unavailable)
    );
    assert_eq!(fixture.frontier.commits.load(Ordering::SeqCst), 0);
}

#[test]
fn external_frontier_mismatch_is_not_repaired_from_the_local_directory() {
    let fixture = Fixture::new();
    let mut external_head = fixture.head.clone();
    external_head.revision = 2;
    *fixture.frontier.state.lock().unwrap() =
        Some(FinalUseFrontier::for_initial_head(&external_head).unwrap());
    assert_eq!(
        fixture.inputs().open().err(),
        Some(FinalUseError::AntiRollbackViolation)
    );
    assert_eq!(fixture.frontier.commits.load(Ordering::SeqCst), 0);
}

#[test]
fn expired_revoked_and_wrong_epoch_grants_never_reach_nonce_admission() {
    let fixture = Fixture::new();
    let authority = fixture.inputs().open().unwrap();
    let expired = fixture.grant(|grant| {
        grant.not_before_unix_ms = 1;
        grant.expires_at_unix_ms = 2;
    });
    let revoked = fixture.grant(|grant| grant.grant_id = "blocked-grant".to_string());
    let old_epoch = fixture.grant(|grant| grant.authority_epoch = 8);
    assert_eq!(
        authority.claim(&expired, &expired.grant.binding).err(),
        Some(FinalUseError::Expired)
    );
    assert_eq!(
        authority.claim(&revoked, &revoked.grant.binding).err(),
        Some(FinalUseError::Revoked)
    );
    assert_eq!(
        authority.claim(&old_epoch, &old_epoch.grant.binding).err(),
        Some(FinalUseError::EpochMismatch)
    );
    assert_eq!(fixture.frontier.commits.load(Ordering::SeqCst), 0);
}

#[test]
fn rejected_keyring_drift_preserves_original_durable_claims() {
    let fixture = Fixture::new();
    let grant = fixture.grant(|_| {});
    let authority = fixture.inputs().open().unwrap();
    drop(authority.claim(&grant, &grant.grant.binding).unwrap());
    drop(authority);
    let mut changed = fixture.inputs();
    changed.issuer_keys[0].verifying_key =
        SigningKey::from_bytes(&[62; 32]).verifying_key().to_bytes();
    assert!(changed.open().is_err());
    let original = fixture.inputs().open().unwrap();
    assert_eq!(
        original.claim(&grant, &grant.grant.binding).err(),
        Some(FinalUseError::AlreadyClaimed)
    );
    assert_eq!(fixture.frontier.commits.load(Ordering::SeqCst), 1);
}
