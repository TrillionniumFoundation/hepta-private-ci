use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Debug)]
struct FixedClock(u64);

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0)
    }
}

#[derive(Debug)]
struct MemoryFinalUseFrontier(Mutex<FinalUseFrontier>);

impl AuthorityFrontierStore<FinalUseFrontier> for MemoryFinalUseFrontier {
    fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        self.0
            .lock()
            .map(|frontier| *frontier)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        _owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
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

fn fixture()
-> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), Box<dyn std::error::Error>> {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
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
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    Ok((
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    ))
}

#[test]
fn signed_claim_is_single_use_and_delivers_under_same_owner() {
    let (authority, signed, _directory) = fixture().unwrap();
    let binding = &signed.grant.binding;
    let token = authority.claim(&signed, binding).unwrap();
    assert_eq!(
        authority.claim(&signed, binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(authority.with_verified_use(token, binding, || 7), Ok(7));
}

#[test]
fn changing_signed_data_or_substituting_a_key_does_not_authorize() {
    let (authority, mut signed, _directory) = fixture().unwrap();
    signed.grant.binding.request_sha256 = [6; 32];
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::InvalidSignature
    );
    let attacker = SigningKey::from_bytes(&[63; 32]);
    signed.signature = attacker
        .sign(&signed.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::InvalidSignature
    );
}

#[test]
fn revocation_after_claim_prevents_delivery_and_cannot_be_rolled_back() {
    let (authority, signed, _directory) = fixture().unwrap();
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .unwrap();
    let mut called = false;
    assert_eq!(
        authority.with_verified_use(token, &signed.grant.binding, || called = true),
        Err(FinalUseError::Revoked)
    );
    assert!(!called);
    assert_eq!(
        authority.update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 3,
            revoked_grant_ids: BTreeSet::new(),
        }),
        Err(FinalUseError::StaleRevocationHead)
    );
}

#[test]
fn epoch_change_fences_outstanding_claims_and_old_grants() {
    let (authority, signed, _directory) = fixture().unwrap();
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 10,
            revision: 2,
            revoked_grant_ids: BTreeSet::new(),
        })
        .unwrap();
    assert_eq!(
        authority.with_verified_use(token, &signed.grant.binding, || ()),
        Err(FinalUseError::EpochMismatch)
    );
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::EpochMismatch
    );
}

#[test]
fn capacity_snapshot_tracks_claims_revocations_and_epoch_rollover() {
    let (authority, signed, _directory) = fixture().unwrap();
    let empty = authority.capacity().unwrap();
    assert_eq!(empty.authority_epoch, 9);
    assert_eq!(empty.revision, 1);
    assert_eq!(empty.used_nonces, 0);
    assert_eq!(empty.revoked_grants, 0);
    assert_eq!(empty.remaining_claims(), empty.max_claims);
    assert!(!empty.rollover_required_with_reserve(0));

    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    drop(token);
    let claimed = authority.capacity().unwrap();
    assert_eq!(claimed.used_nonces, 1);
    assert_eq!(claimed.remaining_claims(), claimed.max_claims - 1);

    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .unwrap();
    let revoked = authority.capacity().unwrap();
    assert_eq!(revoked.revision, 2);
    assert_eq!(revoked.revoked_grants, 1);

    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 10,
            revision: 3,
            revoked_grant_ids: BTreeSet::new(),
        })
        .unwrap();
    let rolled = authority.capacity().unwrap();
    assert_eq!(rolled.authority_epoch, 10);
    assert_eq!(rolled.used_nonces, 0);
    assert_eq!(rolled.revoked_grants, 0);
}

#[test]
fn expired_grant_is_denied_using_verifier_clock() {
    let (authority, mut signed, _directory) = fixture().unwrap();
    signed.grant.not_before_unix_ms = 1;
    signed.grant.expires_at_unix_ms = 2;
    signed.signature = SigningKey::from_bytes(&[47; 32])
        .sign(&signed.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Expired
    );
}

fn reopen(directory: &std::path::Path) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir(
        directory,
        "security-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
}

#[test]
fn injected_clock_is_the_only_final_use_time_source() {
    let issuer = SigningKey::from_bytes(&[57; 32]);
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "clock-owner".into(),
        authority_epoch: 3,
        grant_id: "clock-use".into(),
        nonce: [8; 32],
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [11; 32],
            scope_sha256: [12; 32],
            payload_sha256: [13; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    };
    let signed = SignedFinalUseGrant {
        signature: issuer
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        grant,
    };
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        directory.path(),
        "clock-owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 3,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        Arc::new(FixedClock(2_000)),
    )
    .unwrap();
    assert!(authority.claim(&signed, &signed.grant.binding).is_ok());
}

#[test]
fn external_final_use_frontier_detects_restored_claim_snapshot() {
    let issuer = SigningKey::from_bytes(&[58; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 4,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "frontier-owner".into(),
        authority_epoch: 4,
        grant_id: "frontier-use".into(),
        nonce: [14; 32],
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [15; 32],
            scope_sha256: [16; 32],
            payload_sha256: [17; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: issuer
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        grant,
    };
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let frontier_store = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&head).unwrap(),
    )));
    let authority = FinalUseAuthority::open_state_dir_with_trust(
        directory.path(),
        "frontier-owner".into(),
        issuer.verifying_key().to_bytes(),
        head.clone(),
        Arc::new(FixedClock(2_000)),
        frontier_store.clone(),
    )
    .unwrap();
    let initial = std::fs::read(directory.path().join("authority.json")).unwrap();
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    drop(token);
    let advanced = frontier_store.load("frontier-owner").unwrap();
    assert_ne!(advanced, FinalUseFrontier::for_initial_head(&head).unwrap());
    drop(authority);
    std::fs::write(directory.path().join("authority.json"), initial).unwrap();
    assert_eq!(
        FinalUseAuthority::open_state_dir_with_trust(
            directory.path(),
            "frontier-owner".into(),
            issuer.verifying_key().to_bytes(),
            head,
            Arc::new(FixedClock(2_000)),
            frontier_store,
        )
        .unwrap_err(),
        FinalUseError::AntiRollbackViolation
    );
}

#[test]
fn issuer_key_ring_supports_overlap_and_epoch_retirement() {
    let old = SigningKey::from_bytes(&[61; 32]);
    let next = SigningKey::from_bytes(&[62; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let frontier_store = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&head).unwrap(),
    )));
    let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
        directory.path(),
        "rotating-owner".into(),
        vec![
            FinalUseIssuerTrustKey {
                key_id: "old".into(),
                verifying_key: old.verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 9,
            },
            FinalUseIssuerTrustKey {
                key_id: "next".into(),
                verifying_key: next.verifying_key().to_bytes(),
                not_before_authority_epoch: 9,
                not_after_authority_epoch: 20,
            },
        ],
        head,
        Arc::new(FixedClock(2_000)),
        frontier_store,
    )
    .unwrap();
    assert_eq!(authority.issuer_key_ids(), vec!["next", "old"]);

    let make = |grant_id: &str, nonce: [u8; 32], signer: &SigningKey| {
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "rotating-owner".into(),
            authority_epoch: 9,
            grant_id: grant_id.into(),
            nonce,
            binding: FinalUseBinding {
                subject_id: "agent-one".into(),
                destination_id: "provider:heptabao".into(),
                request_sha256: [21; 32],
                scope_sha256: [22; 32],
                payload_sha256: [23; 32],
            },
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 3_000,
        };
        SignedFinalUseGrant {
            signature: signer
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        }
    };
    let old_grant = make("old-key-use", [24; 32], &old);
    let next_grant = make("next-key-use", [25; 32], &next);
    assert!(authority
        .claim(&old_grant, &old_grant.grant.binding)
        .is_ok());
    assert!(authority
        .claim(&next_grant, &next_grant.grant.binding)
        .is_ok());

    let retired_head = FinalUseRevocations {
        authority_epoch: 10,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let retired_dir = tempfile::tempdir().unwrap();
    std::fs::set_permissions(
        retired_dir.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let retired_frontier = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&retired_head).unwrap(),
    )));
    let retired = FinalUseAuthority::open_state_dir_with_issuer_keys(
        retired_dir.path(),
        "rotating-owner".into(),
        vec![
            FinalUseIssuerTrustKey {
                key_id: "old".into(),
                verifying_key: old.verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 9,
            },
            FinalUseIssuerTrustKey {
                key_id: "next".into(),
                verifying_key: next.verifying_key().to_bytes(),
                not_before_authority_epoch: 9,
                not_after_authority_epoch: 20,
            },
        ],
        retired_head,
        Arc::new(FixedClock(2_000)),
        retired_frontier,
    )
    .unwrap();
    let mut retired_old = old_grant.clone();
    retired_old.grant.authority_epoch = 10;
    retired_old.grant.grant_id = "retired-old-key".into();
    retired_old.grant.nonce = [26; 32];
    retired_old.signature = old
        .sign(&retired_old.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert_eq!(
        retired
            .claim(&retired_old, &retired_old.grant.binding)
            .unwrap_err(),
        FinalUseError::InvalidSignature
    );
}

#[test]
fn replay_state_survives_owner_restart_and_prevents_concurrent_owners() {
    let (authority, signed, directory) = fixture().unwrap();
    assert_eq!(
        reopen(directory.path()).unwrap_err(),
        FinalUseError::StateLocked
    );
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    drop(token);
    drop(authority);
    let reopened = reopen(directory.path()).unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn revocation_survives_restart_and_missing_state_is_not_reset() {
    let (authority, signed, directory) = fixture().unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .unwrap();
    drop(authority);
    let reopened = reopen(directory.path()).unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Revoked
    );
    drop(reopened);
    std::fs::remove_file(directory.path().join("authority.json")).unwrap();
    assert_eq!(
        reopen(directory.path()).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[cfg(unix)]
#[test]
fn authority_rejects_shared_state_directory_and_symlinked_files() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(
        reopen(directory.path()).unwrap_err(),
        FinalUseError::UnsafeStateDirectory
    );
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let target = tempfile::NamedTempFile::new().unwrap();
    std::os::unix::fs::symlink(target.path(), directory.path().join("authority.lock")).unwrap();
    assert!(reopen(directory.path()).is_err());
}

#[test]
fn killed_owner_releases_lock_but_keeps_claim() {
    const CHILD_STATE: &str = "HEPTA_FINAL_USE_TEST_CHILD_STATE";
    if let Some(path) = std::env::var_os(CHILD_STATE) {
        let (_, signed, _fixture_directory) = fixture().unwrap();
        let authority = reopen(std::path::Path::new(&path)).unwrap();
        let _token = authority.claim(&signed, &signed.grant.binding).unwrap();
        std::fs::write(std::path::Path::new(&path).join("ready"), b"ready").unwrap();
        loop {
            std::thread::park();
        }
    }
    let (authority, signed, directory) = fixture().unwrap();
    drop(authority);
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "final_use::tests::killed_owner_releases_lock_but_keeps_claim",
            "--nocapture",
        ])
        .env(CHILD_STATE, directory.path())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap();
    let ready = directory.path().join("ready");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while !ready.exists() && std::time::Instant::now() < deadline {
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    let was_ready = ready.exists();
    let locked = if was_ready {
        reopen(directory.path()).unwrap_err()
    } else {
        FinalUseError::Unavailable
    };
    child.kill().unwrap();
    child.wait().unwrap();
    assert!(was_ready, "child did not persist its claim");
    assert_eq!(locked, FinalUseError::StateLocked);
    let reopened = reopen(directory.path()).unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn startup_trusted_head_can_advance_but_cannot_rollback_persisted_revocations() {
    let (authority, signed, directory) = fixture().unwrap();
    drop(authority);
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 2,
        revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
    };
    let reopened = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        head,
    )
    .unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Revoked
    );
    drop(reopened);
    let stale_startup = reopen(directory.path()).unwrap();
    assert_eq!(
        stale_startup
            .claim(&signed, &signed.grant.binding)
            .unwrap_err(),
        FinalUseError::Revoked
    );
}
