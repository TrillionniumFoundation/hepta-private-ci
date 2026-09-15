use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;

fn signed_grant(
    issuer: &SigningKey,
    nonce: [u8; 32],
    authority_epoch: u64,
    grant_id: &str,
) -> SignedFinalUseGrant {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch,
        grant_id: grant_id.into(),
        nonce,
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: now - 1_000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn open(
    directory: &std::path::Path,
    issuer: &SigningKey,
    head: FinalUseRevocations,
) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir(
        directory,
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        head,
    )
}

fn private_tempdir() -> tempfile::TempDir {
    let directory = tempfile::tempdir().expect("tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private directory");
    directory
}

fn head(epoch: u64, revision: u64) -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: epoch,
        revision,
        revoked_grant_ids: BTreeSet::new(),
    }
}

#[test]
fn claims_append_fixed_records_without_rewriting_metadata() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).expect("open authority");
    let metadata_before = std::fs::read(directory.path().join("authority.json"))
        .expect("read authority metadata");

    let first = signed_grant(&issuer, [5; 32], 9, "claim-one");
    authority
        .claim(&first, &first.grant.binding)
        .expect("first claim");
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .expect("nonce log")
            .len(),
        40
    );
    assert_eq!(
        std::fs::read(directory.path().join("authority.json")).expect("metadata after first"),
        metadata_before
    );

    let second = signed_grant(&issuer, [6; 32], 9, "claim-two");
    authority
        .claim(&second, &second.grant.binding)
        .expect("second claim");
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .expect("nonce log")
            .len(),
        80
    );
    assert_eq!(
        std::fs::read(directory.path().join("authority.json")).expect("metadata after second"),
        metadata_before
    );
}

#[test]
fn legacy_v1_state_migrates_without_refunding_claimed_nonce() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let claimed_nonce = [7; 32];
    let legacy = serde_json::json!({
        "schema": 1,
        "signer_id": "security-owner",
        "verifying_key": issuer.verifying_key().to_bytes(),
        "state": State {
            head: head(9, 1),
            used_nonces: BTreeSet::from([claimed_nonce]),
            failed: false,
        },
    });
    let metadata_path = directory.path().join("authority.json");
    std::fs::write(
        &metadata_path,
        serde_json::to_vec(&legacy).expect("legacy json"),
    )
    .expect("write legacy metadata");
    std::fs::set_permissions(&metadata_path, std::fs::Permissions::from_mode(0o600))
        .expect("private metadata");
    let lock_path = directory.path().join("authority.lock");
    std::fs::write(&lock_path, b"").expect("legacy lock");
    std::fs::set_permissions(&lock_path, std::fs::Permissions::from_mode(0o600))
        .expect("private lock");

    let authority = open(directory.path(), &issuer, head(9, 1)).expect("migrate legacy state");
    let metadata: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&metadata_path).expect("read migrated metadata"),
    )
    .expect("decode migrated metadata");
    assert_eq!(metadata["schema"], 2);
    assert!(metadata.get("state").is_none());
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .expect("migrated nonce log")
            .len(),
        40
    );

    let replay = signed_grant(&issuer, claimed_nonce, 9, "legacy-replay");
    assert_eq!(
        authority.claim(&replay, &replay.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn truncated_incremental_record_fails_closed_on_restart() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).expect("open authority");
    let grant = signed_grant(&issuer, [8; 32], 9, "durable-claim");
    authority
        .claim(&grant, &grant.grant.binding)
        .expect("claim");
    drop(authority);

    let nonce_path = directory.path().join("authority.nonces");
    OpenOptions::new()
        .append(true)
        .open(&nonce_path)
        .expect("open nonce log")
        .write_all(&[0xff])
        .expect("write truncated tail");
    assert_eq!(
        open(directory.path(), &issuer, head(9, 1)).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn epoch_advance_rotates_nonce_log_after_head_commit() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).expect("open authority");
    let grant = signed_grant(&issuer, [9; 32], 9, "old-epoch-claim");
    authority
        .claim(&grant, &grant.grant.binding)
        .expect("claim");
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .expect("nonce log")
            .len(),
        40
    );

    authority
        .update_revocations(head(10, 2))
        .expect("advance epoch");
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .expect("rotated nonce log")
            .len(),
        0
    );
    assert_eq!(
        authority.claim(&grant, &grant.grant.binding).unwrap_err(),
        FinalUseError::EpochMismatch
    );
}
