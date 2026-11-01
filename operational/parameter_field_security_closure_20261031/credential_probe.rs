//! Exercise unchanged product code with original and repaired keyring v3 graphs.

#[allow(dead_code)]
mod product {
    include!(env!("HEPTA_PRODUCT_KEYRING_SOURCE"));
}

use keyring::Entry;
use keyring::Error;
use product::CredentialStoreError;
use product::DefaultKeyringStore;
use product::KeyringStore;
use std::collections::HashMap;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const FIRST: &str = "synthetic-dependency-first-62a57266";
const SECOND: &str = "synthetic-dependency-updated-🔐-82f584bf";
const PERSISTENT: &str = "synthetic-persistent-f73e6dfd";
const BINARY: &[u8] = &[0, 255, 128, 1, 13, 10, 42];

fn assert_native(service: &str) -> Result<()> {
    let entry = Entry::new(service, "primary")?;
    // The exact upstream v3 builder currently creates SsCredential even when
    // linux-native-async-persistent is selected. Preserve and verify that fact;
    // do not label these observations as a positive keyutils-cache test.
    assert!(entry.get_credential().is::<keyring::secret_service::SsCredential>());
    Ok(())
}

fn attributes(service: &str) -> Result<()> {
    let entry = Entry::new(service, "primary")?;
    let mut actual = entry.get_attributes()?;
    if let Some(schema) = actual.remove("xdg:schema") {
        assert_eq!(schema, "org.freedesktop.Secret.Generic");
    }
    assert_eq!(actual, HashMap::from([
        ("application".to_owned(), "rust-keyring".to_owned()),
        ("label".to_owned(), format!("primary@{service}:default (keyring v3.6.3)")),
        ("qualification".to_owned(), "preserved".to_owned()),
    ]));
    // v3 ignores writes to controlled selector attributes. It must neither
    // retarget a credential nor adopt the different v4 error contract.
    entry.update_attributes(&HashMap::from([("service", "retargeted")]))?;
    assert!(Entry::new(service, "primary")?.get_password().is_ok());
    assert!(matches!(Entry::new("retargeted", "primary")?.get_password(), Err(Error::NoEntry)));
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
    store.save(service, account, "")?;
    assert_eq!(store.load(service, account)?, Some(String::new()));
    assert!(store.delete(service, account)?);
    assert!(!store.delete(service, account)?);
    Ok(())
}

fn phase(name: &str, service: &str) -> Result<()> {
    let store = DefaultKeyringStore;
    assert_native(service)?;
    match name {
        "seed" => {
            assert_eq!(store.load(service, "primary")?, None);
            store.save(service, "primary", FIRST)?;
            store.save(&format!("{service}-other"), "primary", "other service")?;
            store.save(service, "persistent", PERSISTENT)?;
            Entry::new(service, "primary")?.update_attributes(&HashMap::from([("qualification", "preserved")]))?;
            attributes(service)?;
        }
        "update" => {
            assert_eq!(store.load(service, "primary")?, Some(FIRST.to_owned()));
            attributes(service)?;
            store.save(service, "primary", SECOND)?;
            store.save(service, "other-account", "other account")?;
            Entry::new(service, "binary")?.set_secret(BINARY)?;
        }
        "verify" => {
            assert_eq!(store.load(service, "primary")?, Some(SECOND.to_owned()));
            assert_eq!(store.load(service, "other-account")?, Some("other account".to_owned()));
            assert_eq!(store.load(&format!("{service}-other"), "primary")?, Some("other service".to_owned()));
            attributes(service)?;
            assert_eq!(Entry::new(service, "binary")?.get_secret()?, BINARY);
            assert!(matches!(store.load(service, "binary").map_err(CredentialStoreError::into_error), Err(Error::BadEncoding(_))));
        }
        "delete" => {
            assert!(store.delete(service, "primary")?);
            assert_eq!(store.load(service, "primary")?, None);
            assert!(!store.delete(service, "primary")?);
            assert!(store.delete(service, "binary")?);
            assert!(store.delete(service, "other-account")?);
            assert!(store.delete(&format!("{service}-other"), "primary")?);
        }
        "absent" => {
            assert_eq!(store.load(service, "primary")?, None);
            assert!(!store.delete(service, "primary")?);
        }
        "persistent" => assert_eq!(store.load(service, "persistent")?, Some(PERSISTENT.to_owned())),
        "finish" => {
            assert_eq!(store.load(service, "persistent")?, Some(PERSISTENT.to_owned()));
            assert!(store.delete(service, "persistent")?);
        }
        "round-trip" => round_trip(service, "runtime")?,
        "unavailable" => {
            assert!(matches!(store.load(service, "primary").map_err(CredentialStoreError::into_error), Err(Error::PlatformFailure(_))));
            assert!(matches!(store.save(service, "primary", FIRST).map_err(CredentialStoreError::into_error), Err(Error::PlatformFailure(_))));
            assert!(matches!(store.delete(service, "primary").map_err(CredentialStoreError::into_error), Err(Error::PlatformFailure(_))));
        }
        "concurrent" => std::thread::scope(|scope| -> Result<()> {
            scope.spawn(|| round_trip(service, "init-thread")).join().map_err(|_| "initialization thread panicked")??;
            let workers: Vec<_> = (0..4).map(|worker| scope.spawn(move || -> Result<()> {
                for iteration in 0..5 {
                    round_trip(service, &format!("worker-{worker}-{iteration}"))?;
                }
                Ok(())
            })).collect();
            for worker in workers {
                worker.join().map_err(|_| "credential worker panicked")??;
            }
            Ok(())
        })?,
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
        "current-thread" => tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async { phase(name, service) })?,
        "multi-thread" => tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build()?.block_on(async { phase(name, service) })?,
        "spawn-blocking" => {
            let name = name.clone();
            let service = service.clone();
            tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async {
                tokio::task::spawn_blocking(move || phase(&name, &service)).await
            })??;
        }
        _ => return Err(format!("unknown runtime: {mode}").into()),
    }
    if name == "round-trip" && mode != "sync" {
        round_trip(service, "after-runtime-drop")?;
    }
    println!("passed runtime={mode} phase={name} backend=keyring_v3_SsCredential");
    Ok(())
}
