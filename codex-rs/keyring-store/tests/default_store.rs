use codex_keyring_store::CredentialStoreError;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use keyring_core::CredentialStore;
use keyring_core::Entry;
use keyring_core::Error;
use pretty_assertions::assert_eq;
use std::sync::Arc;

struct RestoreDefaultStore(Option<Arc<CredentialStore>>);

impl Drop for RestoreDefaultStore {
    fn drop(&mut self) {
        keyring_core::unset_default_store();
        if let Some(store) = self.0.take() {
            keyring_core::set_default_store(store);
        }
    }
}

#[test]
fn installed_store_preserves_round_trips_isolation_and_errors()
-> Result<(), Box<dyn std::error::Error>> {
    let _restore = RestoreDefaultStore(keyring_core::get_default_store());
    let installed_store = keyring_core::mock::Store::new()?;
    keyring_core::set_default_store(installed_store.clone());
    let store = DefaultKeyringStore;

    assert_eq!(store.load("first-service", "account")?, None);
    assert!(!store.delete("first-service", "account")?);

    store.save("first-service", "account", "initial secret")?;
    store.save("second-service", "account", "other service")?;
    store.save("first-service", "other-account", "other account")?;
    store.save("first-service", "account", "updated secret 🔐")?;
    assert_eq!(
        [
            store.load("first-service", "account")?,
            store.load("second-service", "account")?,
            store.load("first-service", "other-account")?,
        ],
        [
            Some("updated secret 🔐".to_string()),
            Some("other service".to_string()),
            Some("other account".to_string()),
        ]
    );

    // A platform failure must remain an error, never an absent credential or a
    // successful write. All operations still use the caller-installed store.
    let entry = Entry::new("first-service", "account")?;
    let credential = entry
        .as_any()
        .downcast_ref::<keyring_core::mock::Cred>()
        .ok_or("the caller-installed credential store was replaced")?;
    credential.set_error(Error::NoStorageAccess(Box::new(std::io::Error::other(
        "store is locked",
    ))));
    assert!(matches!(
        store
            .load("first-service", "account")
            .map_err(CredentialStoreError::into_error),
        Err(Error::NoStorageAccess(_))
    ));
    credential.set_error(Error::Invalid(
        "secret".to_string(),
        "write rejected".to_string(),
    ));
    assert!(matches!(
        store
            .save("first-service", "account", "rejected replacement")
            .map_err(CredentialStoreError::into_error),
        Err(Error::Invalid(_, _))
    ));
    credential.set_error(Error::PlatformFailure(Box::new(std::io::Error::other(
        "delete rejected",
    ))));
    assert!(matches!(
        store
            .delete("first-service", "account")
            .map_err(CredentialStoreError::into_error),
        Err(Error::PlatformFailure(_))
    ));
    assert_eq!(
        store.load("first-service", "account")?,
        Some("updated secret 🔐".to_string())
    );

    assert!(store.delete("first-service", "account")?);
    assert_eq!(store.load("first-service", "account")?, None);
    assert!(!store.delete("first-service", "account")?);
    let current_store = keyring_core::get_default_store().ok_or("default store was removed")?;
    let installed_store: Arc<CredentialStore> = installed_store;
    assert!(Arc::ptr_eq(&installed_store, &current_store));
    Ok(())
}
