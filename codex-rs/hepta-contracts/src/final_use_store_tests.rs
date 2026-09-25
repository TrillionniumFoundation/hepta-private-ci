use super::*;
use pretty_assertions::assert_eq;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

fn private_tempdir() -> std::io::Result<tempfile::TempDir> {
    let directory = tempfile::tempdir()?;
    #[cfg(unix)]
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

#[test]
fn legacy_single_key_and_key_ring_snapshots_preserve_nonce_claims() {
    for trust in [
        StoreTrust::SingleKey([47; 32]),
        StoreTrust::IssuerKeyRing([91; 32]),
    ] {
        let directory = private_tempdir().unwrap();
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
    let directory = private_tempdir().unwrap();
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
