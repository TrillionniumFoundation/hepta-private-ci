//! On unsupported filesystems, signing a packet must never grant a Worker
//! permission to create or consume a Final-use nonce.

use super::*;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;

#[test]
fn final_use_state_directory_is_denied_without_verified_windows_owner_acl() {
    let temp = tempfile::tempdir().expect("temporary root");
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let state_path = temp.path().join("final-use");
    assert!(matches!(
        FinalUseAuthority::open_state_dir(
            &state_path,
            "security-owner".to_string(),
            signing_key.verifying_key().to_bytes(),
            head,
        ),
        Err(FinalUseError::UnsafeStateDirectory)
    ));
    assert!(!state_path.exists());
}
