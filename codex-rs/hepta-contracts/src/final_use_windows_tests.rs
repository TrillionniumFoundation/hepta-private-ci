use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[derive(Debug)]
struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(10_000)
    }
}

struct Fixture {
    parent: tempfile::TempDir,
    issuer: SigningKey,
    head: FinalUseRevocations,
}

impl Fixture {
    fn new() -> Self {
        Self {
            parent: tempfile::tempdir()
                .unwrap_or_else(|error| panic!("create final-use fixture directory: {error}")),
            issuer: SigningKey::from_bytes(&[47; 32]),
            head: FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        }
    }

    fn directory(&self) -> std::path::PathBuf {
        self.parent.path().join("authority")
    }

    fn open(&self) -> Result<FinalUseAuthority, FinalUseError> {
        FinalUseAuthority::open_state_dir_with_clock(
            &self.directory(),
            "security-owner".into(),
            self.issuer.verifying_key().to_bytes(),
            self.head.clone(),
            Arc::new(FixedClock),
        )
    }

    fn signed(&self) -> SignedFinalUseGrant {
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 9,
            grant_id: "read-one".into(),
            nonce: [5; 32],
            binding: FinalUseBinding {
                subject_id: "agent-one".into(),
                destination_id: "provider:heptabao".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: 9_000,
            expires_at_unix_ms: 20_000,
        };
        let signature = self
            .issuer
            .sign(
                &grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("encode final-use fixture grant: {error}")),
            )
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }
}

#[test]
fn native_owner_lock_and_claim_replay_survive_reopen() {
    let fixture = Fixture::new();
    let authority = fixture.open().unwrap();
    assert_eq!(fixture.open().unwrap_err(), FinalUseError::StateLocked);
    let signed = fixture.signed();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    let reopened = fixture.open().unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn native_revocation_replacement_survives_reopen_and_missing_state_fails_closed() {
    let mut fixture = Fixture::new();
    let authority = fixture.open().unwrap();
    let signed = fixture.signed();
    fixture.head.revision += 1;
    fixture
        .head
        .revoked_grant_ids
        .insert(signed.grant.grant_id.clone());
    authority.update_revocations(fixture.head.clone()).unwrap();
    drop(authority);
    let reopened = fixture.open().unwrap();
    assert_eq!(reopened.revocation_head().unwrap(), fixture.head);
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Revoked
    );
    drop(reopened);
    std::fs::remove_file(fixture.directory().join("authority.json")).unwrap();
    assert_eq!(fixture.open().unwrap_err(), FinalUseError::InvalidTrust);
}

#[test]
fn native_missing_claim_journal_is_never_recreated() {
    let fixture = Fixture::new();
    let authority = fixture.open().unwrap();
    let signed = fixture.signed();
    let journal = fixture.directory().join("authority.claims");
    std::fs::remove_file(&journal).unwrap();
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Unavailable
    );
    assert!(!journal.exists());
    drop(authority);
    assert_eq!(fixture.open().unwrap_err(), FinalUseError::InvalidTrust);
}
