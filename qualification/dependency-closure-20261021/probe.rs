//! Exercises the actual product store with independent old/new Cargo graphs.
//! The orchestrator supplies a private session bus and synthetic test data.
#[path = "../../codex-rs/keyring-store/src/lib.rs"]
#[allow(dead_code)]
mod product;

use keyring_core::Entry;
use keyring_core::Error;
use pretty_assertions::assert_eq;
use product::CredentialStoreError;
use product::DefaultKeyringStore;
use product::KeyringStore;
use std::collections::HashMap;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const FIRST: &str = "synthetic-dependency-first-62a57266";
const SECOND: &str = "synthetic-dependency-updated-🔐-82f584bf";
const PERSISTENT: &str = "synthetic-persistent-f73e6dfd";
const BINARY: &[u8] = &[0, 255, 128, 1, 13, 10, 42];

fn native_attributes(entry: &Entry) -> Result<HashMap<String, String>> {
    let mut attributes = entry.get_attributes()?;
    // GNOME may add its own schema annotation. Verify that annotation if
    // present, then compare every application attribute exactly.
    if let Some(schema) = attributes.remove("xdg:schema") {
        assert_eq!(schema, "org.freedesktop.Secret.Generic");
    }
    Ok(attributes)
}

fn attributes(service: &str) -> Result<()> {
    let entry = Entry::new(service, "primary")?;
    let actual = native_attributes(&entry)?;
    assert_eq!(
        actual,
        HashMap::from([
            ("service".to_owned(), service.to_owned()),
            ("username".to_owned(), "primary".to_owned()),
            ("qualification".to_owned(), "preserved".to_owned()),
        ])
    );
    let native = entry
        .as_any()
        .downcast_ref::<zbus_secret_service_keyring_store::cred::Specifier>()
        .ok_or("native store changed")?;
    assert_eq!(native.get_label()?, format!("keyring:primary@{service}"));
    assert!(matches!(
        entry.update_attributes(&HashMap::from([("service", "retargeted")])),
        Err(Error::Invalid(_, _))
    ));
    Ok(())
}

fn ambiguity(service: &str) -> Result<()> {
    let service = format!("{service}-ambiguous");
    let store = DefaultKeyringStore;
    assert!(
        matches!(store.load(&service, "primary").map_err(CredentialStoreError::into_error), Err(Error::Ambiguous(entries)) if entries.len() == 2)
    );
    assert!(
        matches!(store.save(&service, "primary", "rejected ambiguous write").map_err(CredentialStoreError::into_error), Err(Error::Ambiguous(entries)) if entries.len() == 2)
    );
    assert!(
        matches!(store.delete(&service, "primary").map_err(CredentialStoreError::into_error), Err(Error::Ambiguous(entries)) if entries.len() == 2)
    );
    let targeted =
        Entry::new_with_modifiers(&service, "primary", &HashMap::from([("target", "default")]))?;
    assert_eq!(targeted.get_password()?, FIRST);
    assert_eq!(
        native_attributes(&targeted)?,
        HashMap::from([
            ("service".to_owned(), service),
            ("username".to_owned(), "primary".to_owned()),
            ("target".to_owned(), "default".to_owned()),
        ])
    );
    Ok(())
}

fn round_trip(service: &str, account: &str) -> Result<()> {
    let store = DefaultKeyringStore;
    assert_eq!(store.load(service, account)?, None);
    assert!(!store.delete(service, account)?);
    store.save(service, account, FIRST)?;
    assert_eq!(store.load(service, account)?, Some(FIRST.to_owned()));
    store.save(service, account, SECOND)?;
    assert_eq!(store.load(service, account)?, Some(SECOND.to_owned()));
    assert!(store.delete(service, account)?);
    assert!(!store.delete(service, account)?);
    Ok(())
}

fn phase(name: &str, service: &str) -> Result<()> {
    let store = DefaultKeyringStore;
    match name {
        "seed" => {
            assert_eq!(store.load(service, "primary")?, None);
            store.save(service, "primary", FIRST)?;
            store.save(&format!("{service}-other"), "primary", "other service")?;
            store.save(service, "persistent", PERSISTENT)?;
            Entry::new(service, "primary")?
                .update_attributes(&HashMap::from([("qualification", "preserved")]))?;
            attributes(service)?;
            let ambiguous_service = format!("{service}-ambiguous");
            store.save(&ambiguous_service, "primary", FIRST)?;
            Entry::new_with_modifiers(
                &ambiguous_service,
                "primary",
                &HashMap::from([("target", "default")]),
            )?
            .set_password(FIRST)?;
            ambiguity(service)?;
        }
        "update" => {
            assert_eq!(store.load(service, "primary")?, Some(FIRST.to_owned()));
            attributes(service)?;
            ambiguity(service)?;
            store.save(service, "primary", SECOND)?;
            store.save(service, "other-account", "other account")?;
            Entry::new(service, "binary")?.set_secret(BINARY)?;
        }
        "verify" => {
            assert_eq!(store.load(service, "primary")?, Some(SECOND.to_owned()));
            assert_eq!(
                store.load(service, "other-account")?,
                Some("other account".to_owned())
            );
            assert_eq!(
                store.load(&format!("{service}-other"), "primary")?,
                Some("other service".to_owned())
            );
            attributes(service)?;
            ambiguity(service)?;
            assert_eq!(Entry::new(service, "binary")?.get_secret()?, BINARY);
            assert!(matches!(
                store
                    .load(service, "binary")
                    .map_err(CredentialStoreError::into_error),
                Err(Error::BadEncoding(_))
            ));
        }
        "delete" => {
            assert!(store.delete(service, "primary")?);
            assert_eq!(store.load(service, "primary")?, None);
            assert!(!store.delete(service, "primary")?);
            assert!(store.delete(service, "binary")?);
            assert!(store.delete(service, "other-account")?);
            assert!(store.delete(&format!("{service}-other"), "primary")?);
            for entry in Entry::search(&HashMap::from([(
                "service",
                format!("{service}-ambiguous").as_str(),
            )]))? {
                entry.delete_credential()?;
            }
        }
        "absent" => {
            assert_eq!(store.load(service, "primary")?, None);
            assert!(!store.delete(service, "primary")?);
        }
        "persistent" => {
            assert_eq!(
                store.load(service, "persistent")?,
                Some(PERSISTENT.to_owned())
            );
        }
        "finish" => {
            assert_eq!(
                store.load(service, "persistent")?,
                Some(PERSISTENT.to_owned())
            );
            assert!(store.delete(service, "persistent")?);
        }
        "round-trip" => round_trip(service, "runtime")?,
        "unavailable" => {
            // Factory initialization failure is cached by keyring v1. None of
            // the product operations may silently report a missing credential.
            assert!(matches!(
                store
                    .load(service, "primary")
                    .map_err(CredentialStoreError::into_error),
                Err(Error::Invalid(_, _))
            ));
            assert!(matches!(
                store
                    .save(service, "primary", FIRST)
                    .map_err(CredentialStoreError::into_error),
                Err(Error::Invalid(_, _))
            ));
            assert!(matches!(
                store
                    .delete(service, "primary")
                    .map_err(CredentialStoreError::into_error),
                Err(Error::Invalid(_, _))
            ));
            assert!(keyring_core::get_default_store().is_none());
        }
        "concurrent" => {
            // Initialization is on a thread which then exits. All operations
            // below share the original native store and its connection/mutex.
            std::thread::scope(|scope| -> Result<()> {
                scope
                    .spawn(|| round_trip(service, "init-thread"))
                    .join()
                    .map_err(|_| "initialization thread panicked")??;
                let workers: Vec<_> = (0..4)
                    .map(|worker| {
                        scope.spawn(move || -> Result<()> {
                            for iteration in 0..5 {
                                round_trip(service, &format!("worker-{worker}-{iteration}"))?;
                            }
                            Ok(())
                        })
                    })
                    .collect();
                for worker in workers {
                    worker.join().map_err(|_| "credential worker panicked")??;
                }
                Ok(())
            })?;
        }
        _ => return Err(format!("unknown phase: {name}").into()),
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let [_, mode, name, service] = args.as_slice() else {
        return Err("usage: credential-probe MODE PHASE SERVICE".into());
    };
    match mode.as_str() {
        "sync" => phase(name, service)?,
        "current-thread" => {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?
                .block_on(async { phase(name, service) })?;
        }
        "multi-thread" => {
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()?
                .block_on(async { phase(name, service) })?;
        }
        "spawn-blocking" => {
            let phase_name = name.clone();
            let service_name = service.clone();
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?
                .block_on(async {
                    tokio::task::spawn_blocking(move || phase(&phase_name, &service_name)).await
                })??;
        }
        _ => return Err(format!("unknown runtime: {mode}").into()),
    }
    if name == "round-trip" && mode != "sync" {
        // The ambient Tokio runtime above has been destroyed. Its shutdown
        // must not strand a store initialized inside it.
        round_trip(service, "after-runtime-drop")?;
    }
    println!("passed runtime={mode} phase={name}");
    Ok(())
}
