use pretty_assertions::assert_eq;

use super::*;

#[test]
fn windows_nonce_journal_reopens_with_exact_trust_and_exclusive_owner()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("owner");
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, initial) = Store::open(&root, "owner", [47; 32], head.clone())?;
    assert!(initial.used_nonces.is_empty());
    assert!(matches!(
        Store::open(&root, "owner", [47; 32], head.clone()),
        Err(FinalUseError::StateLocked)
    ));
    owner.append_claim(9, [5; 32])?;
    owner.append_claim(9, [6; 32])?;
    drop(owner);
    assert!(matches!(
        Store::open_exact(&root, "owner", [48; 32], head.clone()),
        Err(FinalUseError::InvalidTrust)
    ));
    let (owner, reopened) = Store::open_exact(&root, "owner", [47; 32], head.clone())?;
    assert_eq!(reopened.head, head);
    assert_eq!(reopened.used_nonces, BTreeSet::from([[5; 32], [6; 32]]));
    drop(owner);
    let newer = FinalUseRevocations {
        revision: 2,
        ..head
    };
    assert!(matches!(
        Store::open_exact(&root, "owner", [47; 32], newer),
        Err(FinalUseError::InvalidTrust)
    ));
    Ok(())
}

#[test]
fn windows_missing_claims_are_rejected_without_recreating_the_journal()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("owner");
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(&root, "owner", [47; 32], head.clone())?;
    owner.append_claim(9, [5; 32])?;
    let snapshot = std::fs::read(root.join("authority.json"))?;
    std::fs::remove_file(root.join("authority.claims"))?;
    assert!(matches!(
        owner.append_claim(9, [6; 32]),
        Err(FinalUseError::Unavailable)
    ));
    assert!(!root.join("authority.claims").exists());
    drop(owner);
    assert!(matches!(
        Store::open_exact(&root, "owner", [47; 32], head),
        Err(FinalUseError::InvalidTrust)
    ));
    assert!(!root.join("authority.claims").exists());
    assert_eq!(std::fs::read(root.join("authority.json"))?, snapshot);
    Ok(())
}
