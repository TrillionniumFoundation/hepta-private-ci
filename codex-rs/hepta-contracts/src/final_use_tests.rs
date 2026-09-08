use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

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
