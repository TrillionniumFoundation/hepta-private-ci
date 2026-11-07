use super::*;
use pretty_assertions::assert_eq;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[allow(clippy::unwrap_used)]
fn private_tempdir() -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    #[cfg(unix)]
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

#[test]
fn incompatible_experimental_pq_store_is_rejected_without_resetting_claims() {
    let directory = private_tempdir();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) =
        Store::open_pq_key_ring_exact(directory.path(), "owner", [91; 32], head.clone()).unwrap();
    owner.append_claim(9, [7; 32]).unwrap();
    drop(owner);
    // The earlier raw-key experimental profile used schema 3 and a distinct
    // trust namespace. Canonical PQ cannot reinterpret it as a fresh owner.
    let legacy = serde_json::json!({
        "schema": 3,
        "signer_id": "owner",
        "trust": { "MlDsa65IssuerKeyRingV2": ([91; 32]) },
        "head": head,
    });
    let state_path = directory.path().join("authority.json");
    std::fs::write(&state_path, serde_json::to_vec(&legacy).unwrap()).unwrap();
    let state = std::fs::read(&state_path).unwrap();
    let claims_path = directory.path().join("authority.claims");
    let claims = std::fs::read(&claims_path).unwrap();
    assert!(matches!(
        Store::open_pq_key_ring_exact(directory.path(), "owner", [91; 32], head.clone()),
        Err(FinalUseError::InvalidTrust)
    ));
    assert!(matches!(
        Store::open_key_ring_exact(directory.path(), "owner", [91; 32], head),
        Err(FinalUseError::InvalidTrust)
    ));
    assert_eq!(std::fs::read(state_path).unwrap(), state);
    assert_eq!(std::fs::read(claims_path).unwrap(), claims);
}

#[test]
fn legacy_single_key_and_key_ring_snapshots_preserve_nonce_claims() {
    for trust in [
        StoreTrust::SingleKey([47; 32]),
        StoreTrust::IssuerKeyRing([91; 32]),
    ] {
        let directory = private_tempdir();
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let state = State {
            head: head.clone(),
            used_nonces: BTreeSet::from([[5; 32], [6; 32]]),
            failed: false,
        };
        let (owner, _) =
            Store::open_inner(directory.path(), "owner", trust, head.clone(), false).unwrap();
        drop(owner);
        let legacy = match trust {
            StoreTrust::SingleKey(key) => serde_json::json!({
                "schema": 1, "signer_id": "owner", "verifying_key": key, "state": state,
            }),
            StoreTrust::IssuerKeyRing(digest) => serde_json::json!({
                "schema": 2, "signer_id": "owner", "issuer_trust_sha256": digest, "state": state,
            }),
            StoreTrust::PqIssuerKeyRing(_) => panic!("PQ stores have no legacy snapshot migration"),
        };
        std::fs::write(
            directory.path().join("authority.json"),
            serde_json::to_vec(&legacy).unwrap(),
        )
        .unwrap();
        std::fs::remove_file(directory.path().join("authority.claims")).unwrap();
        let (owner, migrated) =
            Store::open_inner(directory.path(), "owner", trust, head.clone(), false).unwrap();
        assert_eq!(migrated.head, state.head);
        assert_eq!(migrated.used_nonces, state.used_nonces);
        owner.append_claim(9, [7; 32]).unwrap();
        drop(owner);
        let (_, reopened) =
            Store::open_inner(directory.path(), "owner", trust, head, false).unwrap();
        assert_eq!(
            reopened.used_nonces,
            BTreeSet::from([[5; 32], [6; 32], [7; 32]])
        );
    }
}

#[test]
fn legacy_journal_keeps_trust_binding_and_exact_head_checks() {
    let directory = private_tempdir();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(directory.path(), "owner", [47; 32], head.clone()).unwrap();
    owner.append_claim(9, [5; 32]).unwrap();
    drop(owner);
    let legacy = serde_json::json!({
        "schema": 2, "signer_id": "owner", "verifying_key": ([47; 32]), "head": head,
    });
    std::fs::write(
        directory.path().join("authority.json"),
        serde_json::to_vec(&legacy).unwrap(),
    )
    .unwrap();
    assert!(matches!(
        Store::open(directory.path(), "owner", [48; 32], head.clone()),
        Err(FinalUseError::InvalidTrust)
    ));
    let (owner, migrated) =
        Store::open_exact(directory.path(), "owner", [47; 32], head.clone()).unwrap();
    assert_eq!(migrated.used_nonces, BTreeSet::from([[5; 32]]));
    drop(owner);
    let newer = FinalUseRevocations {
        revision: 2,
        ..head
    };
    assert!(matches!(
        Store::open_exact(directory.path(), "owner", [47; 32], newer),
        Err(FinalUseError::InvalidTrust)
    ));
}

#[test]
fn legacy_zero_nonce_rejects_before_original_stage_or_committed_bytes_change() {
    for trust in [
        StoreTrust::SingleKey([47; 32]),
        StoreTrust::IssuerKeyRing([91; 32]),
    ] {
        let directory = private_tempdir();
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let (owner, _) =
            Store::open_inner(directory.path(), "owner", trust, head.clone(), false).unwrap();
        drop(owner);
        let state = State {
            head: head.clone(),
            used_nonces: BTreeSet::from([[0; 32], [5; 32]]),
            failed: false,
        };
        let legacy = match trust {
            StoreTrust::SingleKey(key) => serde_json::json!({
                "schema": 1, "signer_id": "owner", "verifying_key": key, "state": state,
            }),
            StoreTrust::IssuerKeyRing(digest) => serde_json::json!({
                "schema": 2, "signer_id": "owner", "issuer_trust_sha256": digest, "state": state,
            }),
            StoreTrust::PqIssuerKeyRing(_) => panic!("PQ stores have no legacy snapshot migration"),
        };
        std::fs::write(
            directory.path().join("authority.json"),
            serde_json::to_vec(&legacy).unwrap(),
        )
        .unwrap();
        let names = [
            "authority.json",
            "authority.claims",
            "authority.next",
            "authority.claims.next",
        ];
        for name in &names[2..] {
            let path = directory.path().join(name);
            std::fs::write(&path, b"original-unselected-stage").unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
        let before = names.map(|name| std::fs::read(directory.path().join(name)).unwrap());
        for _ in 0..2 {
            assert!(matches!(
                Store::open_inner(directory.path(), "owner", trust, head.clone(), false),
                Err(FinalUseError::InvalidTrust)
            ));
            assert_eq!(
                names.map(|name| std::fs::read(directory.path().join(name)).unwrap()),
                before
            );
        }
    }
}

#[test]
fn live_claim_journal_length_drift_rejects_append_and_compaction_without_writes() {
    enum Mutation {
        Append,
        Compact,
    }
    for length in [0, (CLAIM_FRAME_BYTES * 2) as u64] {
        for operation in [Mutation::Append, Mutation::Compact] {
            let directory = private_tempdir();
            let head = FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            };
            let (owner, mut state) =
                Store::open(directory.path(), "owner", [47; 32], head).unwrap();
            owner.append_claim(9, [5; 32]).unwrap();
            state.used_nonces.insert([5; 32]);
            state.head.revision += 1;
            let claims_path = directory.path().join("authority.claims");
            std::fs::OpenOptions::new()
                .write(true)
                .open(&claims_path)
                .unwrap()
                .set_len(length)
                .unwrap();
            let claims = std::fs::read(&claims_path).unwrap();
            let snapshot_path = directory.path().join("authority.json");
            let snapshot = std::fs::read(&snapshot_path).unwrap();
            let result = match operation {
                Mutation::Append => owner.append_claim(9, [6; 32]),
                Mutation::Compact => owner.persist(&state),
            };
            assert_eq!(result, Err(FinalUseError::Unavailable));
            assert_eq!(owner.revalidate_owner(), Err(FinalUseError::Unavailable));
            assert_eq!(std::fs::read(&claims_path).unwrap(), claims);
            assert_eq!(std::fs::read(&snapshot_path).unwrap(), snapshot);
        }
    }
}

#[test]
fn identical_replacement_claim_journal_cannot_take_over_the_live_descriptor() {
    let directory = private_tempdir();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(directory.path(), "owner", [47; 32], head).unwrap();
    owner.append_claim(9, [5; 32]).unwrap();
    let claims_path = directory.path().join("authority.claims");
    let retained_path = directory.path().join("moved.claims");
    let claims = std::fs::read(&claims_path).unwrap();
    std::fs::rename(&claims_path, &retained_path).unwrap();
    std::fs::write(&claims_path, &claims).unwrap();
    std::fs::set_permissions(&claims_path, std::fs::Permissions::from_mode(0o600)).unwrap();

    assert_eq!(
        owner.append_claim(9, [6; 32]),
        Err(FinalUseError::Unavailable)
    );
    assert_eq!(std::fs::read(&claims_path).unwrap(), claims);
    assert_eq!(std::fs::read(&retained_path).unwrap(), claims);
    // Restoring the original name cannot unfence an owner which saw drift.
    std::fs::rename(&retained_path, &claims_path).unwrap();
    assert_eq!(
        owner.append_claim(9, [6; 32]),
        Err(FinalUseError::Unavailable)
    );
}

#[test]
fn compacted_claim_journal_keeps_the_new_descriptor_through_append_and_reopen() {
    let directory = private_tempdir();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, mut state) = Store::open(directory.path(), "owner", [47; 32], head).unwrap();
    owner.append_claim(9, [5; 32]).unwrap();
    state.used_nonces.insert([5; 32]);
    state.head.revision += 1;
    owner.persist(&state).unwrap();
    owner.append_claim(9, [6; 32]).unwrap();
    state.used_nonces.insert([6; 32]);
    drop(owner);
    let (owner, recovered) =
        Store::open_exact(directory.path(), "owner", [47; 32], state.head.clone()).unwrap();
    assert_eq!(recovered.head, state.head);
    assert_eq!(recovered.used_nonces, state.used_nonces);

    state.head.authority_epoch += 1;
    state.head.revision += 1;
    state.used_nonces.clear();
    owner.persist(&state).unwrap();
    owner.append_claim(10, [5; 32]).unwrap();
    state.used_nonces.insert([5; 32]);
    drop(owner);
    let (owner, recovered) =
        Store::open_exact(directory.path(), "owner", [47; 32], state.head.clone()).unwrap();
    assert_eq!(recovered.head, state.head);
    assert_eq!(recovered.used_nonces, state.used_nonces);
    owner.append_claim(10, [6; 32]).unwrap();
    owner.revalidate_owner().unwrap();
}

#[test]
fn pq_store_reopen_keeps_live_owner_fence_after_compaction() {
    let directory = private_tempdir();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, mut state) =
        Store::open_pq_key_ring_exact(directory.path(), "owner", [91; 32], head).unwrap();
    owner.append_claim(/*authority_epoch*/ 9, [5; 32]).unwrap();
    state.used_nonces.insert([5; 32]);
    state.head.revision += 1;
    owner.persist(&state).unwrap();
    owner.append_claim(/*authority_epoch*/ 9, [6; 32]).unwrap();
    state.used_nonces.insert([6; 32]);
    drop(owner);

    let (owner, recovered) =
        Store::open_pq_key_ring_exact(directory.path(), "owner", [91; 32], state.head.clone())
            .unwrap();
    assert_eq!(recovered.head, state.head);
    assert_eq!(recovered.used_nonces, state.used_nonces);
    owner.revalidate_owner().unwrap();

    let claims_path = directory.path().join("authority.claims");
    let retained_path = directory.path().join("retained.claims");
    let claims = std::fs::read(&claims_path).unwrap();
    let snapshot_path = directory.path().join("authority.json");
    let snapshot = std::fs::read(&snapshot_path).unwrap();
    std::fs::rename(&claims_path, &retained_path).unwrap();
    std::fs::write(&claims_path, &claims).unwrap();
    std::fs::set_permissions(&claims_path, std::fs::Permissions::from_mode(0o600)).unwrap();

    assert_eq!(owner.revalidate_owner(), Err(FinalUseError::Unavailable));
    assert_eq!(
        owner.append_claim(/*authority_epoch*/ 9, [7; 32]),
        Err(FinalUseError::Unavailable)
    );
    assert_eq!(owner.persist(&recovered), Err(FinalUseError::Unavailable));
    assert_eq!(std::fs::read(&claims_path).unwrap(), claims);
    assert_eq!(std::fs::read(&retained_path).unwrap(), claims);
    assert_eq!(std::fs::read(&snapshot_path).unwrap(), snapshot);
    std::fs::rename(&retained_path, &claims_path).unwrap();
    assert_eq!(owner.revalidate_owner(), Err(FinalUseError::Unavailable));
}
