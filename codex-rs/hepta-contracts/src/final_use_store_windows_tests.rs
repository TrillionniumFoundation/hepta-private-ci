use super::*;
use pretty_assertions::assert_eq;

#[test]
fn windows_claim_journal_survives_reopen_and_rejects_changed_trust() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("authority");
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(&root, "owner", [47; 32], head.clone()).unwrap();
    assert!(matches!(
        Store::open(&root, "owner", [47; 32], head.clone()),
        Err(FinalUseError::StateLocked)
    ));
    owner.append_claim(/*authority_epoch*/ 9, [5; 32]).unwrap();
    owner.append_claim(/*authority_epoch*/ 9, [6; 32]).unwrap();
    drop(owner);
    assert!(matches!(
        Store::open_exact(&root, "owner", [48; 32], head.clone()),
        Err(FinalUseError::InvalidTrust)
    ));
    let (_, reopened) = Store::open_exact(&root, "owner", [47; 32], head.clone()).unwrap();
    assert_eq!(reopened.head, head);
    assert_eq!(reopened.used_nonces, BTreeSet::from([[5; 32], [6; 32]]));
}
