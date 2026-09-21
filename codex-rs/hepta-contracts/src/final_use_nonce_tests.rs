use super::*;
use pretty_assertions::assert_eq;

// These storage regressions exercise the actual final-use admission path.
// They measure written bytes, not a throughput or target-host capacity claim.
#[test]
fn nonce_claims_append_fixed_records_and_reopen_preserves_consumption() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let snapshot = std::fs::read(directory.path().join("authority.json")).unwrap();
    let mut grants = Vec::new();
    for value in 1..=32_u8 {
        let mut grant = signed.grant.clone();
        grant.nonce = [value; 32];
        let signed = SignedFinalUseGrant {
            signature: issuer
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        };
        drop(authority.claim(&signed, &signed.grant.binding).unwrap());
        assert_eq!(
            std::fs::read(directory.path().join("authority.json")).unwrap(),
            snapshot
        );
        assert_eq!(
            std::fs::metadata(directory.path().join("authority.nonces"))
                .unwrap()
                .len(),
            u64::from(value) * nonce_log::RECORD_BYTES as u64,
        );
        grants.push(signed);
    }
    drop(authority);
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().used_nonces, 32);
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .unwrap()
            .len(),
        0
    );
    for grant in grants {
        assert_eq!(
            reopened.claim(&grant, &grant.grant.binding).unwrap_err(),
            FinalUseError::AlreadyClaimed
        );
    }
}

fn reopen_nonce_fixture(directory: &tempfile::TempDir) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir_with_clock(
        directory.path(),
        "security-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        Arc::new(FixedClock(2_000)),
    )
}

#[test]
fn missing_nonce_log_is_not_an_empty_replay_registry() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    std::fs::remove_file(directory.path().join("authority.nonces")).unwrap();
    assert!(reopen_nonce_fixture(&directory).is_err());
}

#[test]
fn truncated_live_log_fences_the_owner_before_another_claim() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    std::fs::OpenOptions::new()
        .write(true)
        .open(directory.path().join("authority.nonces"))
        .unwrap()
        .set_len(0)
        .unwrap();
    let mut next = signed.grant.clone();
    next.nonce = [9; 32];
    let signed = SignedFinalUseGrant {
        signature: SigningKey::from_bytes(&[47; 32])
            .sign(&next.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        grant: next,
    };
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Unavailable
    );
    assert_eq!(
        authority.capacity().unwrap_err(),
        FinalUseError::Unavailable
    );
}

#[test]
fn torn_tail_is_checkpointed_before_append_and_second_reopen() {
    use std::io::Write;
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.nonces");
    std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(&[7; 19])
        .unwrap();
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().used_nonces, 1);
    assert_eq!(std::fs::metadata(&path).unwrap().len(), 0);
    let mut next = signed.grant.clone();
    next.nonce = [12; 32];
    let next = SignedFinalUseGrant {
        signature: SigningKey::from_bytes(&[47; 32])
            .sign(&next.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        grant: next,
    };
    drop(reopened.claim(&next, &next.grant.binding).unwrap());
    drop(reopened);
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    for grant in [signed, next] {
        assert_eq!(
            reopened.claim(&grant, &grant.grant.binding).unwrap_err(),
            FinalUseError::AlreadyClaimed
        );
    }
}

#[test]
fn corrupt_complete_record_cannot_be_replayed() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.nonces");
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[20] ^= 1;
    std::fs::write(&path, &bytes).unwrap();
    assert_eq!(
        reopen_nonce_fixture(&directory).unwrap_err(),
        FinalUseError::InvalidTrust
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
}

#[test]
fn checkpoint_before_log_truncation_replays_idempotently() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let path = directory.path().join("authority.nonces");
    let old_log = std::fs::read(&path).unwrap();
    drop(authority);
    drop(reopen_nonce_fixture(&directory).unwrap());
    // Recreate only the crash cut after checkpoint durability and before the
    // already-checkpointed log has been discarded. No nonce may be refunded.
    std::fs::write(&path, old_log).unwrap();
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().used_nonces, 1);
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn legacy_single_key_checkpoint_upgrades_without_refunding_nonce() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    drop(reopen_nonce_fixture(&directory).unwrap());
    let path = directory.path().join("authority.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["schema"] = serde_json::json!(1);
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    std::fs::remove_file(directory.path().join("authority.nonces")).unwrap();
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    let value: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(value["schema"], serde_json::json!(3));
}

#[test]
fn legacy_checkpoint_with_live_deltas_rejects_partial_restore() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["schema"] = serde_json::json!(1);
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert_eq!(
        reopen_nonce_fixture(&directory).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn nonce_replay_rejects_future_revision_and_wrong_owner_digest() {
    let initial = State {
        head: FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        used_nonces: BTreeSet::new(),
        failed: false,
    };
    let record = nonce_log::encode(&initial, [3; 32], [4; 32]);
    assert_eq!(
        nonce_log::replay(&record, &mut initial.clone(), [5; 32]),
        Err(FinalUseError::InvalidTrust)
    );
    let mut future = initial.clone();
    future.head.revision = 2;
    let record = nonce_log::encode(&future, [3; 32], [4; 32]);
    assert_eq!(
        nonce_log::replay(&record, &mut initial.clone(), [4; 32]),
        Err(FinalUseError::InvalidTrust)
    );
    let mut newer = initial;
    newer.head.revision = 3;
    assert_eq!(
        nonce_log::replay(&record, &mut newer, [4; 32]),
        Err(FinalUseError::InvalidTrust)
    );
}

fn nonce_fixture()
-> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), Box<dyn std::error::Error>> {
    let (authority, mut signed, directory) = fixture()?;
    drop(authority);
    signed.grant.not_before_unix_ms = 1_000;
    signed.grant.expires_at_unix_ms = 30_000;
    signed.signature = SigningKey::from_bytes(&[47; 32])
        .sign(&signed.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok((reopen_nonce_fixture(&directory)?, signed, directory))
}

#[test]
fn external_frontier_rejects_a_lost_claim_in_a_torn_tail() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority);
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&head).unwrap(),
    )));
    let open = || {
        FinalUseAuthority::open_state_dir_with_trust(
            directory.path(),
            "security-owner".into(),
            SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
            head.clone(),
            Arc::new(FixedClock(2_000)),
            frontier.clone(),
        )
    };
    let authority = open().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    std::fs::OpenOptions::new()
        .write(true)
        .open(directory.path().join("authority.nonces"))
        .unwrap()
        .set_len(31)
        .unwrap();
    assert_eq!(open().unwrap_err(), FinalUseError::AntiRollbackViolation);
    // Checkpointing the validated prefix cannot repair an externally witnessed
    // lost claim, even after a second reopen.
    assert_eq!(open().unwrap_err(), FinalUseError::AntiRollbackViolation);
}

#[test]
fn revocation_checkpoint_keeps_claims_if_old_log_survives_truncation() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let path = directory.path().join("authority.nonces");
    let old_log = std::fs::read(&path).unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from(["another-grant".into()]),
        })
        .unwrap();
    drop(authority);
    std::fs::write(&path, old_log).unwrap();
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().revision, 2);
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
}

#[test]
fn epoch_checkpoint_never_resurrects_old_grants_from_the_previous_log() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let path = directory.path().join("authority.nonces");
    let old_log = std::fs::read(&path).unwrap();
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 10,
            revision: 2,
            revoked_grant_ids: BTreeSet::new(),
        })
        .unwrap();
    drop(authority);
    std::fs::write(&path, old_log).unwrap();
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().used_nonces, 0);
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::EpochMismatch
    );
}

#[test]
fn legacy_key_ring_checkpoint_migrates_without_changing_external_frontier() {
    let (authority, signed, _unused) = nonce_fixture().unwrap();
    drop(authority);
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head(&head).unwrap(),
    )));
    let open = || {
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            directory.path(),
            "security-owner".into(),
            vec![FinalUseIssuerTrustKey {
                key_id: "pinned".into(),
                verifying_key: SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 20,
            }],
            head.clone(),
            Arc::new(FixedClock(2_000)),
            frontier.clone(),
        )
    };
    let authority = open().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let expected = authority.frontier().unwrap();
    drop(authority);
    drop(open().unwrap());
    let path = directory.path().join("authority.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["schema"] = serde_json::json!(2);
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    std::fs::remove_file(directory.path().join("authority.nonces")).unwrap();
    let reopened = open().unwrap();
    assert_eq!(reopened.frontier().unwrap(), expected);
    assert_eq!(
        reopened.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    let value: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(value["schema"], serde_json::json!(4));
}
