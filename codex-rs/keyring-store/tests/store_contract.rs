//! Exercise the public wrapper with an isolated process-memory credential store.
//! Native keyring and Secret Service qualification is a separate integration gate.

use codex_keyring_store::CredentialStoreError;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use keyring::Entry;
use keyring::Error;
use keyring::credential::Credential;
use keyring::credential::CredentialApi;
use keyring::credential::CredentialBuilderApi;
use keyring::credential::CredentialPersistence;
use keyring::mock::MockCredential;
use std::any::Any;
use std::collections::HashMap;
use std::io;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Debug, Default)]
struct MemoryStore {
    credentials: Mutex<HashMap<(String, String), Arc<MockCredential>>>,
    next_build_error: Mutex<Option<Error>>,
}

impl MemoryStore {
    fn credential(&self, service: &str, account: &str) -> keyring::Result<Arc<MockCredential>> {
        let mut credentials = self.credentials.lock().map_err(|_| {
            Error::NoStorageAccess(Box::new(io::Error::other("credential map lock poisoned")))
        })?;
        Ok(Arc::clone(
            credentials
                .entry((service.to_owned(), account.to_owned()))
                .or_default(),
        ))
    }
}

struct MemoryBuilder(Arc<MemoryStore>);

impl CredentialBuilderApi for MemoryBuilder {
    fn build(
        &self,
        target: Option<&str>,
        service: &str,
        account: &str,
    ) -> keyring::Result<Box<Credential>> {
        assert!(
            target.is_none(),
            "the public wrapper uses an untargeted entry"
        );
        if let Some(error) = self
            .0
            .next_build_error
            .lock()
            .map_err(|_| {
                Error::NoStorageAccess(Box::new(io::Error::other("builder error lock poisoned")))
            })?
            .take()
        {
            return Err(error);
        }
        Ok(Box::new(SharedCredential(
            self.0.credential(service, account)?,
        )))
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn persistence(&self) -> CredentialPersistence {
        CredentialPersistence::ProcessOnly
    }
}

struct SharedCredential(Arc<MockCredential>);

impl CredentialApi for SharedCredential {
    fn set_secret(&self, secret: &[u8]) -> keyring::Result<()> {
        self.0.set_secret(secret)
    }

    fn get_secret(&self) -> keyring::Result<Vec<u8>> {
        self.0.get_secret()
    }

    fn delete_credential(&self) -> keyring::Result<()> {
        self.0.delete_credential()
    }

    fn as_any(&self) -> &dyn Any {
        self
    }
}

#[derive(Clone, Copy)]
enum Operation {
    Load,
    Save,
    Delete,
}

fn assert_invalid_error(error: CredentialStoreError, field: &str, reason: &str) {
    let expected = Error::Invalid(field.to_owned(), reason.to_owned()).to_string();
    assert_eq!(
        (error.message(), error.to_string()),
        (expected.clone(), expected)
    );
    match error.into_error() {
        Error::Invalid(actual_field, actual_reason) => {
            assert_eq!(
                (actual_field, actual_reason),
                (field.to_owned(), reason.to_owned())
            );
        }
        other => panic!("the original Invalid error must survive the wrapper: {other:?}"),
    }
}

#[test]
fn default_store_preserves_entry_identity_values_and_error_contract() {
    // One testcase owns the process-global builder. Each call creates a new Entry,
    // while the controlled backend shares state by both service and account.
    // No platform builder, user credential, DBus session or environment is accessed.
    let memory = Arc::new(MemoryStore::default());
    keyring::set_default_credential_builder(Box::new(MemoryBuilder(Arc::clone(&memory))));
    let store = DefaultKeyringStore;
    let other_store = DefaultKeyringStore;
    let service = "hepta-contract-service-a";
    let other_service = "hepta-contract-service-b";
    let account = "synthetic-alice";
    let other_account = "synthetic-bob";

    assert_eq!(store.load(service, account).expect("missing load"), None);
    assert!(!store.delete(service, account).expect("missing delete"));
    let original = "{\"token\":\"synthetic-only\",\"unicode\":\"多模态\"}\n\0tail";
    store
        .save(service, account, original)
        .expect("save serialized value");
    store
        .save(other_service, account, "other service")
        .expect("separate service");
    store
        .save(service, other_account, "other account")
        .expect("separate account");
    assert_eq!(
        [
            other_store.load(service, account).expect("fresh entry"),
            other_store
                .load(other_service, account)
                .expect("fresh service entry"),
            other_store
                .load(service, other_account)
                .expect("fresh account entry"),
        ],
        [
            Some(original.to_owned()),
            Some("other service".to_owned()),
            Some("other account".to_owned())
        ],
    );
    other_store
        .save(service, account, "")
        .expect("empty overwrite");
    assert_eq!(
        store.load(service, account).expect("empty is present"),
        Some(String::new())
    );
    assert!(store.delete(service, account).expect("existing delete"));
    assert_eq!(
        other_store.load(service, account).expect("deleted load"),
        None
    );
    assert!(!other_store.delete(service, account).expect("repeat delete"));
    assert_eq!(
        store
            .load(other_service, account)
            .expect("other service retained"),
        Some("other service".to_owned())
    );

    let credential = memory
        .credential(service, other_account)
        .expect("memory credential");
    let operations = [
        ("load", Operation::Load),
        ("save", Operation::Save),
        ("delete", Operation::Delete),
    ];
    for (name, operation) in operations {
        credential.set_error(Error::Invalid("credential".to_owned(), name.to_owned()));
        let result = match operation {
            Operation::Load => store.load(service, other_account).map(|_| ()),
            Operation::Save => store.save(service, other_account, "must not replace"),
            Operation::Delete => store.delete(service, other_account).map(|_| ()),
        };
        assert_invalid_error(
            result.expect_err("credential operation must fail"),
            "credential",
            name,
        );
        assert_eq!(
            other_store
                .load(service, other_account)
                .expect("failed operation preserves value"),
            Some("other account".to_owned())
        );
    }
    for (name, operation) in operations {
        *memory.next_build_error.lock().expect("builder error lock") =
            Some(Error::Invalid("builder".to_owned(), name.to_owned()));
        let result = match operation {
            Operation::Load => store.load(service, other_account).map(|_| ()),
            Operation::Save => store.save(service, other_account, "must not replace"),
            Operation::Delete => store.delete(service, other_account).map(|_| ()),
        };
        assert_invalid_error(
            result.expect_err("entry construction must fail"),
            "builder",
            name,
        );
        assert_eq!(
            other_store
                .load(service, other_account)
                .expect("construction failure preserves value"),
            Some("other account".to_owned())
        );
    }

    let invalid_utf8 = vec![0xff, 0x80, 0xfe];
    Entry::new(service, other_account)
        .expect("controlled entry")
        .set_secret(&invalid_utf8)
        .expect("inject encoded bytes");
    match store
        .load(service, other_account)
        .expect_err("invalid password encoding")
        .into_error()
    {
        Error::BadEncoding(actual) => assert_eq!(actual, invalid_utf8),
        other => panic!("the original bytes must survive BadEncoding: {other:?}"),
    }
    store
        .save(service, other_account, original)
        .expect("restore valid password");

    credential.set_error(Error::NoStorageAccess(Box::new(io::Error::new(
        io::ErrorKind::PermissionDenied,
        "synthetic storage denial",
    ))));
    match store
        .load(service, other_account)
        .expect_err("storage denial")
        .into_error()
    {
        Error::NoStorageAccess(inner) => {
            let original_error = inner
                .downcast_ref::<io::Error>()
                .expect("original platform error type");
            assert_eq!(
                (original_error.kind(), original_error.to_string()),
                (
                    io::ErrorKind::PermissionDenied,
                    "synthetic storage denial".to_owned()
                )
            );
        }
        other => panic!("storage access errors must retain their inner type: {other:?}"),
    }
    credential.set_error(Error::NoEntry);
    assert!(matches!(
        store
            .save(service, other_account, "must not replace")
            .expect_err("NoEntry during save is an error")
            .into_error(),
        Error::NoEntry
    ));
    *memory.next_build_error.lock().expect("builder error lock") = Some(Error::NoEntry);
    assert!(matches!(
        store
            .load(service, other_account)
            .expect_err("NoEntry during construction is an error")
            .into_error(),
        Error::NoEntry
    ));
    assert_eq!(
        store
            .load(service, other_account)
            .expect("original value remains"),
        Some(original.to_owned())
    );
    assert!(
        store
            .delete(service, other_account)
            .expect("cleanup account")
    );
    assert!(
        store
            .delete(other_service, account)
            .expect("cleanup service")
    );
}
