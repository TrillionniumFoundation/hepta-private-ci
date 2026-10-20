#![cfg(target_os = "linux")]

use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use keyring::credential::CredentialApi;
use keyring::secret_service::SsCredential;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[test]
fn native_secret_service_round_trip() {
    assert!(
        std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_some(),
        "run this qualification in an isolated dbus-run-session with an unlocked Secret Service"
    );
    let service = "hepta-security-backport-qualification";
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock is after the epoch")
        .as_nanos();
    let account = format!("{}-{nonce}", std::process::id());
    let store = DefaultKeyringStore;
    let first = "ephemeral test credential";
    let updated = "updated test credential: 桜";

    assert_eq!(store.load(service, &account).unwrap(), None);
    store.save(service, &account, first).unwrap();
    assert_eq!(
        store.load(service, &account).unwrap(),
        Some(first.to_owned())
    );

    // Read the persistent service directly as well as through the application
    // facade, so an in-process or kernel cache cannot satisfy the whole test.
    let persistent = SsCredential::new_with_target(/*target*/ None, service, &account).unwrap();
    assert_eq!(persistent.get_password().unwrap(), first);

    store.save(service, &account, updated).unwrap();
    assert_eq!(persistent.get_password().unwrap(), updated);
    assert_eq!(
        store.load(service, &account).unwrap(),
        Some(updated.to_owned())
    );
    assert!(store.delete(service, &account).unwrap());
    assert_eq!(store.load(service, &account).unwrap(), None);
    assert!(!store.delete(service, &account).unwrap());
}
