use super::*;
use pretty_assertions::assert_eq;

// Exercise the active schema-3 authority.claims store, not the superseded
// authority.nonces/checksum parser. Its 40-byte frames reject torn tails;
// same-length rollback/corruption requires the independent trusted frontier.
// Legacy snapshot migration remains covered by store::tests.

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
            std::fs::metadata(directory.path().join("authority.claims"))
                .unwrap()
                .len(),
            u64::from(value) * 40,
        );
        grants.push(signed);
    }
    drop(authority);
    let reopened = reopen_nonce_fixture(&directory).unwrap();
    assert_eq!(reopened.capacity().unwrap().used_nonces, 32);
    assert_eq!(
        std::fs::metadata(directory.path().join("authority.claims"))
            .unwrap()
            .len(),
        32 * 40
    );
    for grant in grants {
        assert_eq!(
            reopened.claim(&grant, &grant.grant.binding).unwrap_err(),
            FinalUseError::AlreadyClaimed
        );
    }
}

#[test]
fn missing_nonce_log_is_not_an_empty_replay_registry() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    std::fs::remove_file(directory.path().join("authority.claims")).unwrap();
    assert_eq!(
        reopen_nonce_fixture(&directory).unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn truncated_live_log_fences_the_owner_before_another_claim() {
    for length in [0, 39] {
        assert_live_length_change_fences_owner(length).unwrap();
    }
}

#[test]
fn unexpected_live_log_growth_fences_the_owner_before_another_claim() {
    for length in [41, 80] {
        assert_live_length_change_fences_owner(length).unwrap();
    }
}

fn assert_live_length_change_fences_owner(length: u64) -> Result<(), Box<dyn std::error::Error>> {
    let (authority, signed, directory) = nonce_fixture()?;
    drop(authority.claim(&signed, &signed.grant.binding)?);
    std::fs::OpenOptions::new()
        .write(true)
        .open(directory.path().join("authority.claims"))?
        .set_len(length)?;
    let mut next = signed.grant;
    next.nonce = [9; 32];
    let signed = SignedFinalUseGrant {
        signature: SigningKey::from_bytes(&[47; 32])
            .sign(&next.signing_bytes()?)
            .to_bytes()
            .to_vec(),
        grant: next,
    };
    assert_eq!(
        authority.claim(&signed, &signed.grant.binding).err(),
        Some(FinalUseError::Unavailable)
    );
    assert_eq!(authority.capacity().err(), Some(FinalUseError::Unavailable));
    Ok(())
}

#[test]
fn revocation_snapshot_keeps_claims_if_old_journal_survives_replacement() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let path = directory.path().join("authority.claims");
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
fn epoch_snapshot_never_resurrects_old_grants_from_the_previous_journal() {
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    let path = directory.path().join("authority.claims");
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
    // The old-epoch frame is still physically present. Length tracking must
    // include it even though the current epoch's in-memory nonce set is empty.
    let mut next = signed.grant;
    next.authority_epoch = 10;
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
    assert_eq!(
        reopened.claim(&next, &next.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
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
fn torn_tail_is_rejected_without_rewriting_the_valid_prefix() {
    use std::io::Write;
    let (authority, signed, directory) = nonce_fixture().unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    let path = directory.path().join("authority.claims");
    std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(&[7; 19])
        .unwrap();
    let bytes = std::fs::read(&path).unwrap();
    for _ in 0..2 {
        assert_eq!(
            reopen_nonce_fixture(&directory).unwrap_err(),
            FinalUseError::InvalidTrust
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[test]
fn malformed_complete_claim_frames_are_rejected() {
    for invalid_epoch in [0_u64, 10] {
        let (authority, signed, directory) = nonce_fixture().unwrap();
        drop(authority.claim(&signed, &signed.grant.binding).unwrap());
        drop(authority);
        let path = directory.path().join("authority.claims");
        let mut bytes = std::fs::read(&path).unwrap();
        bytes[..8].copy_from_slice(&invalid_epoch.to_be_bytes());
        std::fs::write(&path, &bytes).unwrap();
        assert_eq!(
            reopen_nonce_fixture(&directory).unwrap_err(),
            FinalUseError::InvalidTrust
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[test]
fn external_frontier_rejects_lost_or_changed_claims_on_repeated_reopen() {
    for corruption in ["truncated", "torn", "changed_nonce"] {
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
        let path = directory.path().join("authority.claims");
        let mut bytes = std::fs::read(&path).unwrap();
        let expected = match corruption {
            "truncated" => {
                bytes.clear();
                FinalUseError::AntiRollbackViolation
            }
            "torn" => {
                bytes.truncate(31);
                FinalUseError::InvalidTrust
            }
            "changed_nonce" => {
                bytes[20] ^= 1;
                FinalUseError::AntiRollbackViolation
            }
            _ => unreachable!(),
        };
        std::fs::write(&path, &bytes).unwrap();
        for _ in 0..2 {
            assert_eq!(open().unwrap_err(), expected);
            assert_eq!(std::fs::read(&path).unwrap(), bytes);
        }
    }
}
