#[path = "production_keyring_store.rs"]
mod production;

use production::DefaultKeyringStore;
use production::KeyringStore;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(args.len(), 5, "operation service account expected-value");
    let operation = args[1].as_str();
    let service = args[2].as_str();
    let account = args[3].as_str();
    let expected = args[4].as_str();
    let entry = keyring::Entry::new(service, account).expect("default Entry construction");
    assert!(
        entry
            .get_credential()
            .is::<keyring::secret_service::SsCredential>(),
        "official persistent default builder must remain the Secret Service store"
    );
    let store = DefaultKeyringStore;
    match operation {
        "save" => {
            store.save(service, account, expected).expect("save");
            assert_eq!(
                store.load(service, account).expect("load"),
                Some(expected.into())
            );
        }
        "load" => {
            assert_eq!(
                store.load(service, account).expect("load"),
                Some(expected.into())
            );
        }
        "missing" => assert_eq!(store.load(service, account).expect("missing load"), None),
        "delete" => assert!(store.delete(service, account).expect("delete")),
        "delete-missing" => assert!(!store.delete(service, account).expect("missing delete")),
        "reject-dh" => {
            let error = store
                .load(service, account)
                .expect_err("DH rejection must fail");
            assert!(matches!(
                error.into_error(),
                keyring::Error::PlatformFailure(_)
            ));
        }
        _ => panic!("unknown probe operation {operation}"),
    }
    println!("PASS: {operation}");
}
