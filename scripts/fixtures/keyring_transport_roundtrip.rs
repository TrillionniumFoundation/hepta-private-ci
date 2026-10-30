//! Run only through run_hepta_keyring_compatibility.py's private D-Bus session.
use anyhow::Context;
use anyhow::Result;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use keyring::Entry;
use keyring::secret_service::SsCredential;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::PathBuf;

fn check_value(service: &str, user: &str, expected: &str) -> Result<()> {
    assert_eq!(DefaultKeyringStore.load(service, user)?, Some(expected.to_owned()));
    assert_eq!(Entry::new_with_target("default", service, user)?.get_password()?, expected);
    let entry = Entry::new(service, user)?;
    let credential = entry
        .get_credential()
        .downcast_ref::<SsCredential>()
        .context("default persistent builder changed concrete provider")?;
    let actual = credential.new_from_matching_item()?;
    assert_eq!(
        actual.attributes,
        HashMap::from([
            ("service".to_owned(), service.to_owned()),
            ("username".to_owned(), user.to_owned()),
            ("target".to_owned(), "default".to_owned()),
            ("application".to_owned(), "rust-keyring".to_owned()),
            // The private GNOME daemon adds its generic Secret Service schema
            // attribute. It is part of the observed item, not a namespace key.
            ("xdg:schema".to_owned(), "org.freedesktop.Secret.Generic".to_owned()),
        ])
    );
    for other in [
        Entry::new(&format!("{service}-other"), user)?,
        Entry::new(service, &format!("{user}-other"))?,
        Entry::new_with_target("hepta-isolated-other", service, user)?,
    ] {
        assert!(matches!(other.get_password(), Err(keyring::Error::NoEntry)));
    }
    Ok(())
}

#[test]
fn isolated_transport_phase() -> Result<()> {
    let root = PathBuf::from(std::env::var("HEPTA_KEYRING_COMPAT_ROOT")?).canonicalize()?;
    let nonce = std::env::var("HEPTA_KEYRING_COMPAT_NONCE")?;
    anyhow::ensure!(nonce.len() >= 24 && nonce.bytes().all(|byte| byte.is_ascii_hexdigit()));
    anyhow::ensure!(std::fs::read_to_string(root.join("nonce"))? == nonce);
    for (key, child) in [("XDG_DATA_HOME", "data"), ("XDG_RUNTIME_DIR", "runtime")] {
        anyhow::ensure!(PathBuf::from(std::env::var(key)?).canonicalize()? == root.join(child));
    }
    let bus = std::env::var("DBUS_SESSION_BUS_ADDRESS")?;
    anyhow::ensure!(
        bus.split(',').next() == Some(format!("unix:path={}/runtime/bus", root.display()).as_str()),
        "refusing a non-private D-Bus session"
    );
    let phase = std::env::var("HEPTA_KEYRING_COMPAT_PHASE")?;
    let service = format!("hepta-transport-{nonce}");
    let user = format!("user-{nonce}");
    let first = format!("{nonce}:old-created:秘密");
    let second = format!("{nonce}:new-updated:é");
    let third = format!("{nonce}:old-updated:漢字");
    match phase.as_str() {
        "old-create" => {
            assert_eq!(DefaultKeyringStore.load(&service, &user)?, None);
            DefaultKeyringStore.save(&service, &user, &first)?;
            check_value(&service, &user, &first)?;
        }
        "new-read-update" => {
            check_value(&service, &user, &first)?;
            DefaultKeyringStore.save(&service, &user, &second)?;
            check_value(&service, &user, &second)?;
        }
        "old-read-update" => {
            check_value(&service, &user, &second)?;
            DefaultKeyringStore.save(&service, &user, &third)?;
            check_value(&service, &user, &third)?;
        }
        "new-read-delete" => {
            check_value(&service, &user, &third)?;
            assert!(DefaultKeyringStore.delete(&service, &user)?);
            assert_eq!(DefaultKeyringStore.load(&service, &user)?, None);
            assert!(!DefaultKeyringStore.delete(&service, &user)?);
            assert!(matches!(Entry::new_with_target("default", &service, &user)?.get_password(), Err(keyring::Error::NoEntry)));
        }
        "old-missing" => {
            assert_eq!(DefaultKeyringStore.load(&service, &user)?, None);
            assert!(!DefaultKeyringStore.delete(&service, &user)?);
            assert!(matches!(Entry::new_with_target("default", &service, &user)?.get_password(), Err(keyring::Error::NoEntry)));
        }
        unexpected => anyhow::bail!("unknown isolated phase {unexpected}"),
    }
    println!("private credential phase completed: {phase}");
    Ok(())
}
