use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::FinalUseGrant;
use crate::claim_final_use;
use crate::dispatch_final_use_with_witness;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

// Test custody is a separate real file, not a claim of root deployment or
// power-loss durability. Production keeps its existing protected backend.
struct Frontier(Mutex<File>);
impl Frontier {
    fn write(file: &mut File, value: &FinalUseFrontier) -> std::io::Result<()> {
        file.seek(SeekFrom::Start(0))?;
        file.set_len(0)?;
        file.write_all(&serde_json::to_vec(value)?)?;
        file.sync_all()
    }

    fn read(file: &mut File) -> std::io::Result<FinalUseFrontier> {
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        Ok(serde_json::from_slice(&bytes)?)
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        Self::read(&mut self.0.lock().unwrap()).map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(&self, _owner_id: &str, expected: &FinalUseFrontier, next: &FinalUseFrontier) -> Result<(), AuthorityTrustError> {
        let mut file = self.0.lock().unwrap();
        if Self::read(&mut file).map_err(|_| AuthorityTrustError::Unavailable)? != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        Self::write(&mut file, next).map_err(|_| AuthorityTrustError::Unavailable)
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    frontier: Arc<Frontier>,
    clock: Arc<Clock>,
    issuer: SigningKey,
    head: FinalUseRevocations,
    signed: SignedFinalUseGrant,
}

impl Fixture {
    fn new() -> Self {
        let issuer = SigningKey::from_bytes(&[71; 32]);
        let head = FinalUseRevocations { authority_epoch: 4, revision: 1, revoked_grant_ids: BTreeSet::new() };
        let grant = FinalUseGrant {
            schema_version: 1, signer_id: "retained-owner".into(), authority_epoch: 4,
            grant_id: "replace-task".into(), nonce: [72; 32],
            binding: FinalUseBinding {
                subject_id: "agent".into(), destination_id: "cell".into(),
                request_sha256: [73; 32], scope_sha256: [74; 32], payload_sha256: [75; 32],
            },
            not_before_unix_ms: 1_000, expires_at_unix_ms: 3_000,
        };
        let signed = SignedFinalUseGrant { signature: issuer.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec(), grant };
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let mut file = tempfile::tempfile().unwrap();
        Frontier::write(&mut file, &FinalUseFrontier::for_initial_head(&head).unwrap()).unwrap();
        Self { directory, frontier: Arc::new(Frontier(Mutex::new(file))), clock: Arc::new(Clock(AtomicU64::new(2_000))), issuer, head, signed }
    }

    fn open(&self) -> FinalUseAuthority {
        FinalUseAuthority::open_state_dir_with_trust(
            self.directory.path(), "retained-owner".into(), self.issuer.verifying_key().to_bytes(),
            self.head.clone(), self.clock.clone(), self.frontier.clone(),
        ).unwrap()
    }

    fn enter(&self, authority: &FinalUseAuthority) -> VerifiedUseTokenWitnessV1 {
        let token = claim_final_use(authority, &self.signed, &self.signed.grant.binding).unwrap();
        let ((), witness) = dispatch_final_use_with_witness(authority, token, &self.signed.grant.binding, |_| ()).unwrap();
        witness
    }
}

#[test]
fn retained_entry_survives_grant_expiry_and_cold_owner_reopen_without_claiming_again() {
    let fixture = Fixture::new();
    let authority = fixture.open();
    let witness = fixture.enter(&authority);
    let before = authority.current_external_frontier().unwrap();
    let claims = std::fs::read(fixture.directory.path().join("authority.claims")).unwrap();
    fixture.clock.0.store(9_000, Ordering::SeqCst);
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Ok(fixture.head.clone()));
    assert_eq!(authority.current_external_frontier().unwrap(), before);
    drop(authority);
    let reopened = fixture.open();
    assert_eq!(reopened.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Ok(fixture.head.clone()));
    assert_eq!(std::fs::read(fixture.directory.path().join("authority.claims")).unwrap(), claims);
    assert_eq!(reopened.capacity().unwrap().used_nonces, 1);
    assert_eq!(claim_final_use(&reopened, &fixture.signed, &fixture.signed.grant.binding).unwrap_err(), FinalUseError::Expired);
}

#[test]
fn retained_entry_rejects_another_owner_unspent_nonce_and_changed_signature() {
    let fixture = Fixture::new();
    let authority = fixture.open();
    let witness = fixture.enter(&authority);
    let other = Fixture::new();
    assert_eq!(other.open().verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Err(FinalUseError::InvalidGrant));
    let mut unsigned_nonce = fixture.signed.clone();
    unsigned_nonce.grant.nonce = [80; 32];
    unsigned_nonce.signature = fixture.issuer.sign(&unsigned_nonce.grant.signing_bytes().unwrap()).to_bytes().to_vec();
    assert_eq!(authority.verify_retained_use(&unsigned_nonce, &unsigned_nonce.grant.binding, &witness), Err(FinalUseError::InvalidGrant));
    let mut bad_signature = fixture.signed.clone();
    bad_signature.signature[0] ^= 1;
    assert_eq!(authority.verify_retained_use(&bad_signature, &bad_signature.grant.binding, &witness), Err(FinalUseError::InvalidSignature));
    assert_eq!(authority.capacity().unwrap().used_nonces, 1);
}

#[test]
fn retained_witness_must_match_original_dispatch_binding_and_entry_window() {
    let fixture = Fixture::new();
    let authority = fixture.open();
    let witness = fixture.enter(&authority);
    let mut changed = witness.clone();
    changed.boundary = VerifiedUseBoundaryV1::ConsumerEntry;
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &changed), Err(FinalUseError::BindingMismatch));
    changed = witness.clone();
    changed.verified_at_unix_ms = fixture.signed.grant.expires_at_unix_ms;
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &changed), Err(FinalUseError::BindingMismatch));
    let mut binding = fixture.signed.grant.binding.clone();
    binding.payload_sha256 = [90; 32];
    assert_eq!(authority.verify_retained_use(&fixture.signed, &binding, &witness), Err(FinalUseError::BindingMismatch));
}

#[test]
fn actual_revocation_and_epoch_rollover_deny_retained_use() {
    let fixture = Fixture::new();
    let authority = fixture.open();
    let witness = fixture.enter(&authority);
    authority.update_revocations(FinalUseRevocations { authority_epoch: 4, revision: 2, revoked_grant_ids: BTreeSet::from([fixture.signed.grant.grant_id.clone()]) }).unwrap();
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Err(FinalUseError::Revoked));
    authority.update_revocations(FinalUseRevocations { authority_epoch: 5, revision: 3, revoked_grant_ids: BTreeSet::new() }).unwrap();
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Err(FinalUseError::EpochMismatch));
}

#[test]
fn independent_frontier_rollback_fences_readers_and_all_owner_clones() {
    let fixture = Fixture::new();
    let authority = fixture.open();
    let before = authority.current_external_frontier().unwrap();
    let witness = fixture.enter(&authority);
    let clone = authority.clone();
    let after = authority.current_external_frontier().unwrap();
    Frontier::write(&mut fixture.frontier.0.lock().unwrap(), &before).unwrap();
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Err(FinalUseError::AntiRollbackViolation));
    Frontier::write(&mut fixture.frontier.0.lock().unwrap(), &after).unwrap();
    assert_eq!(clone.current_external_frontier(), Err(FinalUseError::Unavailable));
}

#[test]
fn compatibility_owner_cannot_substitute_for_external_frontier_custody() {
    let fixture = Fixture::new();
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        fixture.directory.path(), "retained-owner".into(), fixture.issuer.verifying_key().to_bytes(),
        fixture.head.clone(), fixture.clock.clone(),
    ).unwrap();
    let witness = fixture.enter(&authority);
    assert_eq!(authority.current_external_frontier(), Err(FinalUseError::InvalidTrust));
    assert_eq!(authority.verify_retained_use(&fixture.signed, &fixture.signed.grant.binding, &witness), Err(FinalUseError::InvalidTrust));
}
