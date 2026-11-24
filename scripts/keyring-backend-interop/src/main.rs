use std::error::Error;

#[cfg(feature = "baseline")]
use keyring_baseline as keyring;
#[cfg(feature = "candidate")]
use keyring_candidate as keyring;

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[cfg(feature = "candidate")]
use codex_keyring_store::KeyringStore;

fn load(service: &str, account: &str) -> Result<Option<String>> {
    #[cfg(feature = "candidate")]
    return Ok(codex_keyring_store::DefaultKeyringStore.load(service, account)?);
    #[cfg(feature = "baseline")]
    match keyring::Entry::new(service, account)?.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.into()),
    }
}

fn save(service: &str, account: &str, value: &str) -> Result<()> {
    #[cfg(feature = "candidate")]
    codex_keyring_store::DefaultKeyringStore.save(service, account, value)?;
    #[cfg(feature = "baseline")]
    keyring::Entry::new(service, account)?.set_password(value)?;
    Ok(())
}

fn delete(service: &str, account: &str) -> Result<bool> {
    #[cfg(feature = "candidate")]
    return Ok(codex_keyring_store::DefaultKeyringStore.delete(service, account)?);
    #[cfg(feature = "baseline")]
    match keyring::Entry::new(service, account)?.delete_credential() {
        Ok(()) => Ok(true),
        Err(keyring::Error::NoEntry) => Ok(false),
        Err(error) => Err(error.into()),
    }
}

#[cfg(feature = "candidate")]
fn wait_for_absent_key(cache: &keyring::keyutils::KeyutilsCredential) -> Result<()> {
    use keyring::credential::CredentialApi;

    // Upstream documents a short kernel invalidation cache. Confirm absence
    // before measuring backing-store recovery, with a bounded deadline.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
    loop {
        match cache.get_password() {
            Err(keyring::Error::NoEntry) => return Ok(()),
            Err(error) => return Err(error.into()),
            Ok(_) if std::time::Instant::now() >= deadline => {
                return Err("synthetic key invalidation exceeded its deadline".into());
            }
            Ok(_) => std::thread::sleep(std::time::Duration::from_millis(5)),
        }
    }
}

fn main() -> Result<()> {
    let mode = std::env::args().nth(1).ok_or("missing probe mode")?;
    let account = std::env::var("HEPTA_KEYRING_TEST_ACCOUNT")?;
    let account = account.as_str();
    let backend = if cfg!(feature = "candidate") {
        "candidate"
    } else {
        "baseline"
    };
    let entry = keyring::Entry::new("wsp-synthetic", account)?;
    assert!(
        entry
            .get_credential()
            .is::<keyring::secret_service::SsCredential>()
    );
    match mode.as_str() {
        "seed" => {
            assert_eq!(load("wsp-synthetic", account)?, None);
            save("wsp-synthetic", account, "synthetic-原始-credential")?;
            assert_eq!(
                load("wsp-synthetic", account)?.as_deref(),
                Some("synthetic-原始-credential")
            );
        }
        "update" => {
            assert_eq!(
                load("wsp-synthetic", account)?.as_deref(),
                Some("synthetic-原始-credential")
            );
            save("wsp-synthetic", account, "synthetic-updated-凭据")?;
            assert_eq!(
                load("wsp-synthetic", account)?.as_deref(),
                Some("synthetic-updated-凭据")
            );
            assert_eq!(load("wsp-synthetic", "missing")?, None);
            assert!(!delete("wsp-synthetic", "missing")?);
            assert_eq!(
                load("locked", account)?.as_deref(),
                Some("locked-synthetic")
            );
            assert!(load("ambiguous", account).is_err());
            assert!(load("read_failure", account).is_err());
            assert!(save("write_failure", account, "never-stored").is_err());
            assert!(delete("delete_failure", account).is_err());
        }
        "read_updated" => {
            assert_eq!(
                load("wsp-synthetic", account)?.as_deref(),
                Some("synthetic-updated-凭据")
            );
        }
        "delete" => {
            assert!(delete("wsp-synthetic", account)?);
            assert_eq!(load("wsp-synthetic", account)?, None);
            assert!(!delete("wsp-synthetic", account)?);
        }
        "missing" => assert_eq!(load("wsp-synthetic", account)?, None),
        #[cfg(feature = "candidate")]
        "keyutils_cycle" => {
            use keyring::credential::CredentialApi;
            use keyring::keyutils::KeyutilsCredential;
            use keyring::keyutils_persistent::KeyutilsPersistentCredential;

            let cache = KeyutilsCredential::new_with_target(
                /*target*/ None,
                "wsp-synthetic",
                account,
            )?;
            let combo = KeyutilsPersistentCredential::new_with_target(
                /*target*/ None,
                "wsp-synthetic",
                account,
            )?;
            combo.set_password("keyutils-backed-synthetic")?;
            assert_eq!(cache.get_password()?, "keyutils-backed-synthetic");
            cache.delete_credential()?;
            wait_for_absent_key(&cache)?;
            assert_eq!(combo.get_password()?, "keyutils-backed-synthetic");
            assert_eq!(cache.get_password()?, "keyutils-backed-synthetic");
            combo.delete_credential()?;
            wait_for_absent_key(&cache)?;
            assert_eq!(load("wsp-synthetic", account)?, None);

            let cache = KeyutilsCredential::new_with_target(
                /*target*/ None,
                "write_failure",
                account,
            )?;
            let combo = KeyutilsPersistentCredential::new_with_target(
                /*target*/ None,
                "write_failure",
                account,
            )?;
            cache.set_password("cached-before-synthetic-failure")?;
            assert!(combo.set_password("never-stored").is_err());
            assert_eq!(cache.get_password()?, "cached-before-synthetic-failure");
            cache.delete_credential()?;
        }
        _ => return Err("unknown mode".into()),
    }
    println!("{{\"backend\":\"{backend}\",\"mode\":\"{mode}\",\"passed\":true}}");
    Ok(())
}
