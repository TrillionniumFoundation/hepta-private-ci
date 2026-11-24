use std::error::Error;

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

fn main() -> Result<()> {
    let mode = std::env::args().nth(1).ok_or("missing probe mode")?;
    let backend = if cfg!(feature = "candidate") {
        "candidate"
    } else {
        "baseline"
    };
    let entry = keyring::Entry::new("wsp-synthetic", "alice")?;
    assert!(
        entry
            .get_credential()
            .is::<keyring::secret_service::SsCredential>()
    );
    match mode.as_str() {
        "seed" => {
            assert_eq!(load("wsp-synthetic", "alice")?, None);
            save("wsp-synthetic", "alice", "synthetic-原始-credential")?;
            assert_eq!(
                load("wsp-synthetic", "alice")?.as_deref(),
                Some("synthetic-原始-credential")
            );
        }
        "update" => {
            assert_eq!(
                load("wsp-synthetic", "alice")?.as_deref(),
                Some("synthetic-原始-credential")
            );
            save("wsp-synthetic", "alice", "synthetic-updated-凭据")?;
            assert_eq!(
                load("wsp-synthetic", "alice")?.as_deref(),
                Some("synthetic-updated-凭据")
            );
            assert_eq!(load("wsp-synthetic", "missing")?, None);
            assert!(!delete("wsp-synthetic", "missing")?);
            assert_eq!(
                load("locked", "fixture")?.as_deref(),
                Some("locked-synthetic")
            );
            assert!(load("ambiguous", "fixture").is_err());
            assert!(load("read_failure", "fixture").is_err());
            assert!(save("write_failure", "fixture", "never-stored").is_err());
            assert!(delete("delete_failure", "fixture").is_err());
        }
        "read_updated" => {
            assert_eq!(
                load("wsp-synthetic", "alice")?.as_deref(),
                Some("synthetic-updated-凭据")
            );
        }
        "delete" => {
            assert!(delete("wsp-synthetic", "alice")?);
            assert_eq!(load("wsp-synthetic", "alice")?, None);
            assert!(!delete("wsp-synthetic", "alice")?);
        }
        "missing" => assert_eq!(load("wsp-synthetic", "alice")?, None),
        _ => return Err("unknown mode".into()),
    }
    println!("{{\"backend\":\"{backend}\",\"mode\":\"{mode}\",\"passed\":true}}");
    Ok(())
}
