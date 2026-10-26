use super::super::Store;
use super::*;
use crate::FinalUseRevocations;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;

fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 11,
        revision: 3,
        revoked_grant_ids: BTreeSet::from(["revoked-old-grant".to_string()]),
    }
}

#[test]
fn windows_nonce_burn_persists_across_real_private_store_reopen() {
    let temporary = tempfile::tempdir().expect("private state fixture");
    let root = temporary.path().join("final-use-state");
    let key = [17_u8; 32];
    let (store, before) = Store::open(&root, "windows-final-use-owner", key, head())
        .expect("create Windows private final-use owner");
    assert!(before.used_nonces.is_empty());
    store
        .append_claim(11, [29_u8; 32])
        .expect("fsync first replay-protection claim");
    drop(store);

    let (reopened, after) = Store::open_exact(&root, "windows-final-use-owner", key, head())
        .expect("reopen exact original snapshot and nonce journal");
    assert_eq!(after.head, head());
    assert_eq!(after.used_nonces, BTreeSet::from([[29_u8; 32]]));
    drop(reopened);

    // A corrupted claim tail is never treated as a clean fresh install.
    let mut claims = std::fs::OpenOptions::new()
        .append(true)
        .open(root.join("authority.claims"))
        .expect("existing closed claims file");
    use std::io::Write;
    claims.write_all(&[1_u8]).expect("inject incomplete frame");
    claims.sync_all().expect("durably inject incomplete frame");
    drop(claims);
    assert!(matches!(
        Store::open_exact(&root, "windows-final-use-owner", key, head()),
        Err(FinalUseError::InvalidTrust)
    ));
}

#[test]
fn windows_final_use_rejects_hardlinked_claims_before_nonce_replay() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("final-use-state");
    let key = [21_u8; 32];
    let (store, _) =
        Store::open(&root, "windows-final-use-owner", key, head()).expect("private owner start");
    drop(store);
    std::fs::hard_link(root.join("authority.claims"), root.join("claims-alias"))
        .expect("NTFS hardlink adversary");
    assert!(matches!(
        Store::open_exact(&root, "windows-final-use-owner", key, head()),
        Err(FinalUseError::UnsafeStateDirectory)
    ));
}

#[test]
fn windows_final_use_denies_issuer_or_epoch_substitution() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let root = temporary.path().join("final-use-state");
    let key = [23_u8; 32];
    let (store, _) =
        Store::open(&root, "windows-final-use-owner", key, head()).expect("create pinned owner");
    drop(store);
    assert!(matches!(
        Store::open_exact(&root, "windows-final-use-owner", [24_u8; 32], head()),
        Err(FinalUseError::InvalidTrust)
    ));
    let mut altered = head();
    altered.authority_epoch = 12;
    assert!(matches!(
        Store::open_exact(&root, "windows-final-use-owner", key, altered),
        Err(FinalUseError::InvalidTrust)
    ));
}
