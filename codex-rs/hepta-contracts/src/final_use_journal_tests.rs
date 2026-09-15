use super::*;
use pretty_assertions::assert_eq;

#[test]
fn live_log_loss_and_aligned_truncation_permanently_fence_the_owner() {
    for remove in [false, true] {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let directory = private_tempdir();
        let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
        let first = signed_grant(&issuer, [1; 32], 9, "first");
        drop(authority.claim(&first, &first.grant.binding).unwrap());
        let path = directory.path().join("authority.nonces");
        let original = std::fs::read(&path).unwrap();
        if remove {
            std::fs::remove_file(&path).unwrap();
        } else {
            OpenOptions::new()
                .write(true)
                .open(&path)
                .unwrap()
                .set_len(0)
                .unwrap();
        }
        let next = signed_grant(&issuer, [2; 32], 9, "next");
        assert_eq!(
            authority.claim(&next, &next.grant.binding).unwrap_err(),
            FinalUseError::Unavailable
        );
        if remove {
            assert!(
                !path.exists(),
                "a failed append must not recreate the journal"
            );
        }
        std::fs::write(&path, original).unwrap();
        assert_eq!(
            authority.claim(&next, &next.grant.binding).unwrap_err(),
            FinalUseError::Unavailable
        );
    }
}

#[test]
fn restarted_owner_rejects_loss_of_whole_acknowledged_records() {
    for retained in [0, 40] {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let directory = private_tempdir();
        let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
        for nonce in [[1; 32], [2; 32]] {
            let grant = signed_grant(&issuer, nonce, 9, "claim");
            drop(authority.claim(&grant, &grant.grant.binding).unwrap());
        }
        drop(authority);
        OpenOptions::new()
            .write(true)
            .open(directory.path().join("authority.nonces"))
            .unwrap()
            .set_len(retained)
            .unwrap();
        assert_eq!(
            open(directory.path(), &issuer, head(9, 1)).unwrap_err(),
            FinalUseError::InvalidTrust
        );
    }
}

#[test]
fn complete_unacknowledged_tail_is_consumed_then_anchored() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let first = signed_grant(&issuer, [1; 32], 9, "first");
    drop(authority.claim(&first, &first.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.nonces");
    let mut file = OpenOptions::new().append(true).open(&path).unwrap();
    file.write_all(&9_u64.to_le_bytes()).unwrap();
    file.write_all(&[2; 32]).unwrap();
    file.sync_all().unwrap();
    drop(file);
    let recovered = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let second = signed_grant(&issuer, [2; 32], 9, "second");
    assert_eq!(
        recovered.claim(&second, &second.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(recovered.capacity().unwrap().claimed_nonces, 2);
    drop(recovered);
    OpenOptions::new()
        .write(true)
        .open(path)
        .unwrap()
        .set_len(40)
        .unwrap();
    assert_eq!(
        open(directory.path(), &issuer, head(9, 1)).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn same_length_content_substitution_is_rejected_on_recovery() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let grant = signed_grant(&issuer, [1; 32], 9, "claim");
    drop(authority.claim(&grant, &grant.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.nonces");
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[8] ^= 1;
    std::fs::write(path, bytes).unwrap();
    assert_eq!(
        open(directory.path(), &issuer, head(9, 1)).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn replacing_live_log_with_identical_bytes_does_not_replace_the_writer() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let path = directory.path().join("authority.nonces");
    let replacement = directory.path().join("replacement");
    std::fs::write(&replacement, std::fs::read(&path).unwrap()).unwrap();
    std::fs::set_permissions(&replacement, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::fs::rename(replacement, path).unwrap();
    assert_eq!(
        authority.capacity().unwrap_err(),
        FinalUseError::Unavailable
    );
}

#[test]
fn missing_anchor_or_lock_is_not_a_legacy_upgrade() {
    for name in ["authority.nonces.anchor", "authority.lock"] {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let directory = private_tempdir();
        drop(open(directory.path(), &issuer, head(9, 1)).unwrap());
        std::fs::remove_file(directory.path().join(name)).unwrap();
        assert_eq!(
            open(directory.path(), &issuer, head(9, 1)).unwrap_err(),
            FinalUseError::InvalidTrust
        );
    }
}

#[test]
fn final_callback_is_not_entered_after_live_journal_damage() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let grant = signed_grant(&issuer, [1; 32], 9, "claim");
    let token = authority.claim(&grant, &grant.grant.binding).unwrap();
    std::fs::remove_file(directory.path().join("authority.nonces.anchor")).unwrap();
    let entered = std::cell::Cell::new(false);
    assert_eq!(
        authority.with_verified_use(token, &grant.grant.binding, || entered.set(true)),
        Err(FinalUseError::Unavailable)
    );
    assert!(!entered.get());
}

#[test]
fn legacy_v2_upgrade_preserves_claims_and_installs_required_anchor() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    let grant = signed_grant(&issuer, [1; 32], 9, "claim");
    drop(authority.claim(&grant, &grant.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.json");
    let mut metadata: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    metadata["schema"] = 2.into();
    std::fs::write(&path, serde_json::to_vec(&metadata).unwrap()).unwrap();
    std::fs::remove_file(directory.path().join("authority.nonces.anchor")).unwrap();
    let upgraded = open(directory.path(), &issuer, head(9, 1)).unwrap();
    assert_eq!(
        upgraded.claim(&grant, &grant.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert!(directory.path().join("authority.nonces.anchor").is_file());
    let metadata: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    assert_eq!(metadata["schema"], 3);
}

#[test]
fn crash_between_epoch_head_log_and_anchor_publications_recovers_without_replay() {
    for restore_log in [false, true] {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let directory = private_tempdir();
        let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
        let old = signed_grant(&issuer, [1; 32], 9, "old");
        drop(authority.claim(&old, &old.grant.binding).unwrap());
        let log = directory.path().join("authority.nonces");
        let anchor = directory.path().join("authority.nonces.anchor");
        let old_log = std::fs::read(&log).unwrap();
        let old_anchor = std::fs::read(&anchor).unwrap();
        authority.update_revocations(head(10, 2)).unwrap();
        drop(authority);
        std::fs::write(anchor, old_anchor).unwrap();
        if restore_log {
            std::fs::write(&log, old_log).unwrap();
        }
        let recovered = open(directory.path(), &issuer, head(10, 2)).unwrap();
        assert_eq!(recovered.capacity().unwrap().claimed_nonces, 0);
        assert_eq!(
            recovered.claim(&old, &old.grant.binding).unwrap_err(),
            FinalUseError::EpochMismatch
        );
        assert_eq!(std::fs::metadata(log).unwrap().len(), 0);
    }
}

#[test]
fn repeated_owner_epochs_bound_recovery_and_do_not_reactivate_old_tokens() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    for revision in 1..=32 {
        let epoch = revision + 8;
        let authority = open(directory.path(), &issuer, head(epoch, revision)).unwrap();
        for nonce in [[1; 32], [2; 32], [3; 32], [4; 32]] {
            let grant = signed_grant(&issuer, nonce, epoch, "claim");
            drop(authority.claim(&grant, &grant.grant.binding).unwrap());
        }
        assert_eq!(
            authority.capacity().unwrap(),
            FinalUseCapacity {
                authority_epoch: epoch,
                revision,
                claimed_nonces: 4,
                remaining_claims: MAX_CLAIMS - 4,
                remaining_revocations: MAX_CLAIMS,
                maintenance_recommended: false,
            }
        );
        assert_eq!(
            std::fs::metadata(directory.path().join("authority.nonces"))
                .unwrap()
                .len(),
            160
        );
        assert!(
            std::fs::metadata(directory.path().join("authority.nonces.anchor"))
                .unwrap()
                .len()
                <= 1024
        );
        let old = signed_grant(&issuer, [5; 32], epoch - 1, "stale");
        assert_eq!(
            authority.claim(&old, &old.grant.binding).unwrap_err(),
            FinalUseError::EpochMismatch
        );
    }
}

#[test]
fn full_epoch_retains_claims_until_an_independently_supplied_epoch_advances() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = private_tempdir();
    drop(open(directory.path(), &issuer, head(9, 1)).unwrap());
    let used_nonces: BTreeSet<[u8; 32]> = (1..=MAX_CLAIMS)
        .map(|index| {
            let mut nonce = [0; 32];
            nonce[..8].copy_from_slice(&(index as u64).to_le_bytes());
            nonce
        })
        .collect();
    let legacy = serde_json::json!({
        "schema": 1,
        "signer_id": "security-owner",
        "verifying_key": issuer.verifying_key().to_bytes(),
        "state": State { head: head(9, 1), used_nonces, failed: false },
    });
    std::fs::write(
        directory.path().join("authority.json"),
        serde_json::to_vec(&legacy).unwrap(),
    )
    .unwrap();
    let authority = open(directory.path(), &issuer, head(9, 1)).unwrap();
    assert_eq!(
        authority.capacity().unwrap(),
        FinalUseCapacity {
            authority_epoch: 9,
            revision: 1,
            claimed_nonces: MAX_CLAIMS,
            remaining_claims: 0,
            remaining_revocations: MAX_CLAIMS,
            maintenance_recommended: true,
        }
    );
    let blocked = signed_grant(&issuer, [99; 32], 9, "full");
    assert_eq!(
        authority
            .claim(&blocked, &blocked.grant.binding)
            .unwrap_err(),
        FinalUseError::CapacityExceeded
    );
    authority.update_revocations(head(9, 2)).unwrap();
    assert_eq!(authority.capacity().unwrap().remaining_claims, 0);
    authority.update_revocations(head(10, 3)).unwrap();
    assert_eq!(authority.capacity().unwrap().remaining_claims, MAX_CLAIMS);
    assert_eq!(
        authority
            .claim(&blocked, &blocked.grant.binding)
            .unwrap_err(),
        FinalUseError::EpochMismatch
    );
    let renewed = signed_grant(&issuer, [99; 32], 10, "renewed");
    drop(authority.claim(&renewed, &renewed.grant.binding).unwrap());
    assert_eq!(
        authority.capacity().unwrap().remaining_claims,
        MAX_CLAIMS - 1
    );
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.nonces"))
            .unwrap()
            .len(),
        40
    );
}

#[test]
fn independent_owner_stores_do_not_share_capacity_or_failure_state() {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let first_directory = private_tempdir();
    let second_directory = private_tempdir();
    let first = open(first_directory.path(), &issuer, head(9, 1)).unwrap();
    let second = open(second_directory.path(), &issuer, head(9, 1)).unwrap();
    std::fs::remove_file(first_directory.path().join("authority.nonces")).unwrap();
    assert_eq!(first.capacity().unwrap_err(), FinalUseError::Unavailable);
    let grant = signed_grant(&issuer, [1; 32], 9, "independent");
    let token = second.claim(&grant, &grant.grant.binding).unwrap();
    assert_eq!(
        second.with_verified_use(token, &grant.grant.binding, || "delivered"),
        Ok("delivered")
    );
    assert_eq!(second.capacity().unwrap().claimed_nonces, 1);
}
