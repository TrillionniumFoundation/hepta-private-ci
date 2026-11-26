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

#[test]
fn lifecycle_credentials_have_separate_storage_and_cannot_reuse_read_proof_key() {
    let store = GatewayCredentialStore::new(ServiceAwareKeyring::default());
    store.import_read("desktop", &"r".repeat(64)).unwrap();
    assert!(store.load_lifecycle("desktop").is_err());
    store.import_lifecycle("desktop", &"c".repeat(64)).unwrap();
    assert_eq!(store.load("desktop").unwrap(), "r".repeat(64));
    assert_eq!(store.load_lifecycle("desktop").unwrap(), "c".repeat(64));
    assert!(
        hepta_native::backend::LoopbackGatewayBackend::new(
            "127.0.0.1:7373".parse().unwrap(),
            "r".repeat(64)
        )
        .unwrap()
        .with_fleet_lifecycle_capability("r".repeat(64))
        .is_err()
    );
    assert!(store.delete_lifecycle("desktop").unwrap());
    assert_eq!(store.load("desktop").unwrap(), "r".repeat(64));
    assert!(store.import_lifecycle("desktop", "invalid\n").is_err());
}

#[derive(Debug, Default)]
struct ServiceAwareKeyring(MockKeyringStore);
impl codex_keyring_store::KeyringStore for ServiceAwareKeyring {
    fn load(
        &self,
        service: &str,
        account: &str,
    ) -> Result<Option<String>, codex_keyring_store::CredentialStoreError> {
        self.0.load(service, &format!("{service}:{account}"))
    }
    fn save(
        &self,
        service: &str,
        account: &str,
        value: &str,
    ) -> Result<(), codex_keyring_store::CredentialStoreError> {
        self.0.save(service, &format!("{service}:{account}"), value)
    }
    fn delete(
        &self,
        service: &str,
        account: &str,
    ) -> Result<bool, codex_keyring_store::CredentialStoreError> {
        self.0.delete(service, &format!("{service}:{account}"))
    }
}
