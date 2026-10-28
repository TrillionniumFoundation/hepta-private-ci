//! A browser dispatch port cannot synthesize the required durable authority.

use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;

#[test]
fn unsupported_final_use_owner_cannot_be_constructed_for_browser_dispatch() {
    let temporary = tempfile::tempdir().expect("authority fixture");
    let directory = temporary.path().join("authority");
    let signing = SigningKey::from_bytes(&[7; 32]);
    let result = FinalUseAuthority::open_state_dir(
        &directory,
        "browser-test-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    );
    assert!(matches!(result, Err(FinalUseError::UnsafeStateDirectory)));
    assert!(!directory.exists());
}
