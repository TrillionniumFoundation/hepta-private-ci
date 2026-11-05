//! Executable integration tests for the public credential-store contract.
//! These exercise the owner-facing mock behavior, not an OS keyring or a
//! Secret Service encryption claim. Live encrypted vendor tests are separate.
use codex_keyring_store::KeyringStore;
use codex_keyring_store::tests::MockKeyringStore;
use keyring::Error as KeyringError;

#[test]
fn mock_store_keeps_secret_roundtrip_and_deletion_idempotent() {
    let store = MockKeyringStore::default();
    let service = "hepta-ci-contract";
    let account = "probe-user";

    assert!(matches!(store.load(service, account), Ok(None)));
    assert!(store.save(service, account, "ephemeral-secret").is_ok());
    assert!(matches!(
        store.load(service, account),
        Ok(Some(value)) if value == "ephemeral-secret"
    ));
    assert!(matches!(store.delete(service, account), Ok(true)));
    assert!(matches!(store.load(service, account), Ok(None)));
    assert!(matches!(store.delete(service, account), Ok(false)));
    assert!(!store.contains(account));
}

#[test]
fn mock_store_preserves_backend_failure_instead_of_treating_it_as_absence() {
    let store = MockKeyringStore::default();
    let service = "hepta-ci-contract";
    let account = "error-probe";
    store.credential(account);
    store.set_error(
        account,
        KeyringError::Invalid("backend".to_string(), "credential denied".to_string()),
    );
    let result = store.load(service, account);
    assert!(matches!(result, Err(error) if error.message().contains("credential denied")));
}
