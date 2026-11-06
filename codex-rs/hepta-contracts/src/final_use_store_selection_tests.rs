//! Real filesystem controls for the new explicit selection. These unit tests
//! do not substitute for the separate original Root/Worker custody fixture.

use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

fn private_directory() -> std::io::Result<tempfile::TempDir> {
    let root = tempfile::tempdir()?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(root)
}

fn head() -> FinalUseRevocations {
    FinalUseRevocations { authority_epoch: 4, revision: 8, revoked_grant_ids: BTreeSet::new() }
}

fn inventory(root: &Path) -> std::io::Result<Vec<(String, u64, u32, u32, u32, Vec<u8>)>> {
    let mut files = std::fs::read_dir(root)?
        .map(|entry| {
            let entry = entry?;
            let metadata = entry.metadata()?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| std::io::Error::other("fixture filename is not UTF-8"))?;
            Ok((
                name,
                metadata.ino(),
                metadata.uid(),
                metadata.gid(),
                metadata.mode(),
                std::fs::read(entry.path())?,
            ))
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    files.sort_by(|left, right| left.0.cmp(&right.0));
    Ok(files)
}

#[test]
fn existing_selection_never_creates_a_missing_directory_or_empty_store() {
    let parent = private_directory().unwrap();
    let missing = parent.path().join("missing");
    assert!(Store::open_key_ring_existing(&missing, "original", [7; 32], head()).is_err());
    assert!(!missing.exists());
    let empty = private_directory().unwrap();
    assert!(Store::open_key_ring_existing(empty.path(), "original", [7; 32], head()).is_err());
    assert!(inventory(empty.path()).unwrap().is_empty());
}

#[test]
fn fresh_selection_creates_consumer_owned_v3_once_and_existing_preserves_nonce() {
    let root = private_directory().unwrap();
    let (store, mut state) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
    let uid = rustix::process::geteuid().as_raw();
    for (_, _, owner, _, mode, _) in inventory(root.path()).unwrap() {
        assert_eq!(owner, uid);
        assert_eq!(mode & 0o077, 0);
    }
    store.append_claim(4, [9; 32]).unwrap();
    state.used_nonces.insert([9; 32]);
    drop(store);
    let before = inventory(root.path()).unwrap();
    assert!(Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).is_err());
    assert_eq!(inventory(root.path()).unwrap(), before);
    let (opened, observed) = Store::open_key_ring_existing(root.path(), "original", [7; 32], head()).unwrap();
    assert_eq!(observed.head, state.head);
    assert_eq!(observed.used_nonces, state.used_nonces);
    assert_eq!(inventory(root.path()).unwrap(), before);
    assert!(matches!(Store::open_key_ring_existing(root.path(), "original", [7; 32], head()), Err(FinalUseError::StateLocked)));
    drop(opened);
}

#[test]
fn missing_any_required_entry_is_not_recreated_by_existing_or_fresh() {
    for missing in ["authority.lock", "authority.json", "authority.claims"] {
        let root = private_directory().unwrap();
        let (store, _) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
        drop(store);
        std::fs::remove_file(root.path().join(missing)).unwrap();
        let before = inventory(root.path()).unwrap();
        assert!(Store::open_key_ring_existing(root.path(), "original", [7; 32], head()).is_err(), "missing {missing}");
        assert_eq!(inventory(root.path()).unwrap(), before);
        assert!(Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).is_err(), "partial {missing}");
        assert_eq!(inventory(root.path()).unwrap(), before);
    }
}

#[test]
fn incomplete_staging_is_not_completed_by_runtime_open() {
    for stale in ["authority.next", "authority.claims.next"] {
        let root = private_directory().unwrap();
        let (store, _) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
        drop(store);
        std::fs::write(root.path().join(stale), b"incomplete original write").unwrap();
        std::fs::set_permissions(root.path().join(stale), std::fs::Permissions::from_mode(0o600)).unwrap();
        let before = inventory(root.path()).unwrap();
        assert!(Store::open_key_ring_existing(root.path(), "original", [7; 32], head()).is_err());
        assert_eq!(inventory(root.path()).unwrap(), before);
    }
}

#[test]
fn legacy_key_ring_snapshot_is_not_migrated_by_runtime_open() {
    let root = private_directory().unwrap();
    let (store, _) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
    drop(store);
    let trust = [7_u8; 32];
    let nonces = vec![[9_u8; 32]];
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema": 2,
        "signer_id": "original",
        "issuer_trust_sha256": trust,
        "state": { "head": head(), "used_nonces": nonces }
    })).unwrap();
    std::fs::write(root.path().join("authority.json"), bytes).unwrap();
    let before = inventory(root.path()).unwrap();
    assert!(matches!(Store::open_key_ring_existing(root.path(), "original", [7; 32], head()), Err(FinalUseError::InvalidTrust)));
    assert_eq!(inventory(root.path()).unwrap(), before);
}

#[test]
fn fresh_selection_does_not_take_over_a_preexisting_lock_or_partial_claims() {
    for prior in ["authority.lock", "authority.claims", "authority.json", "authority.next", "authority.claims.next"] {
        let root = private_directory().unwrap();
        std::fs::write(root.path().join(prior), b"preserve failed attempt").unwrap();
        std::fs::set_permissions(root.path().join(prior), std::fs::Permissions::from_mode(0o600)).unwrap();
        let before = inventory(root.path()).unwrap();
        assert!(Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).is_err());
        assert_eq!(inventory(root.path()).unwrap(), before);
    }
}

#[test]
fn strict_owner_permanently_fences_a_replaced_lock_before_journal_mutation() {
    let root = private_directory().unwrap();
    let (owner, _) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
    let lock = root.path().join("authority.lock");
    let old = root.path().join("held-original-lock");
    std::fs::rename(&lock, &old).unwrap();
    std::fs::write(&lock, []).unwrap();
    std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o600)).unwrap();
    // A replacement inode is independently lockable. The retained owner must
    // not confuse that new lock with the original one it still holds.
    let (replacement, _) = Store::open_key_ring_existing(root.path(), "original", [7; 32], head()).unwrap();
    let before = std::fs::read(root.path().join("authority.claims")).unwrap();
    assert!(owner.append_claim(4, [11; 32]).is_err());
    assert_eq!(std::fs::read(root.path().join("authority.claims")).unwrap(), before);
    std::fs::remove_file(&lock).unwrap();
    std::fs::rename(old, &lock).unwrap();
    assert!(owner.revalidate_owner().is_err());
    assert!(replacement.revalidate_owner().is_err());
    assert_eq!(std::fs::read(root.path().join("authority.claims")).unwrap(), before);
}

#[test]
fn strict_owner_keeps_original_claims_replacement_and_length_guards() {
    for mutation in ["replace", "truncate", "extend"] {
        let root = private_directory().unwrap();
        let (owner, _) = Store::initialize_key_ring_fresh(root.path(), "original", [7; 32], head()).unwrap();
        owner.append_claim(4, [9; 32]).unwrap();
        let claims = root.path().join("authority.claims");
        let original = std::fs::read(&claims).unwrap();
        match mutation {
            "replace" => {
                std::fs::rename(&claims, root.path().join("held-original-claims")).unwrap();
                std::fs::write(&claims, &original).unwrap();
                std::fs::set_permissions(&claims, std::fs::Permissions::from_mode(0o600)).unwrap();
            }
            "truncate" => File::options().write(true).open(&claims).unwrap().set_len(0).unwrap(),
            "extend" => File::options().write(true).open(&claims).unwrap().set_len(original.len() as u64 + 1).unwrap(),
            _ => unreachable!(),
        }
        let after_mutation = std::fs::read(&claims).unwrap();
        assert!(owner.append_claim(4, [11; 32]).is_err(), "{mutation}");
        assert_eq!(std::fs::read(&claims).unwrap(), after_mutation);
        assert!(owner.revalidate_owner().is_err(), "{mutation} stays fenced");
    }
}
