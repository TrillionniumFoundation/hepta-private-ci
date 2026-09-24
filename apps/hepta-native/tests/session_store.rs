use codex_keyring_store::tests::MockKeyringStore;
use hepta_native::model::SessionIncarnation;
use hepta_native::session_store::GatewayCredentialStore;
use hepta_native::session_store::SessionReferenceStore;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";

#[test]
fn opaque_session_reference_round_trips_through_keyring_store() {
    let keyring = MockKeyringStore::default();
    let store = SessionReferenceStore::new(keyring);
    let session = SessionIncarnation {
        endpoint_id: "runtime.local".to_owned(),
        session_id: "session.local".to_owned(),
        generation: 7,
    };
    store.save(&session, D1).unwrap();
    let loaded = store.load("runtime.local").unwrap().unwrap();
    assert_eq!(loaded.session, session);
    assert_eq!(loaded.manifest_digest, D1);
    assert!(store.delete("runtime.local").unwrap());
    assert!(store.load("runtime.local").unwrap().is_none());
}

#[test]
fn gateway_capability_is_generated_stored_and_not_returned_in_receipt() {
    let keyring = MockKeyringStore::default();
    let store = GatewayCredentialStore::new(keyring);
    let receipt = store.provision_random("gateway.local").unwrap();
    assert_eq!(receipt.account, "gateway.local");
    assert_eq!(receipt.token_digest.len(), 64);

    let token = store.load("gateway.local").unwrap();
    assert!(token.len() >= 32);
    assert!(!receipt.token_digest.contains(&token));
    assert!(store.delete("gateway.local").unwrap());
    assert!(store.load("gateway.local").is_err());
}
