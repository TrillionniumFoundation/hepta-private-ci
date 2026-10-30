#![cfg(target_os = "linux")]

use keyring::Entry;
use keyring::credential::CredentialPersistence;
use keyring::keyutils_persistent::default_credential_builder;
use keyring::secret_service::SsCredential;
use pretty_assertions::assert_eq;
use std::collections::HashMap;

#[test]
fn persistent_builder_retains_existing_secret_service_credential() -> keyring::Result<()> {
    let builder = default_credential_builder();
    assert!(matches!(builder.persistence(), CredentialPersistence::UntilDelete));
    // keyring 3.6.3's persistent builder constructs SsCredential. Keep this
    // observed behavior instead of introducing a new kernel-cache side effect.
    let credential = builder.build(/*target*/ None, "hepta-compat-服务", "account")?;
    let secret_service = credential
        .as_any()
        .downcast_ref::<SsCredential>()
        .expect("persistent provider must retain its existing concrete credential");
    let entry = Entry::new("hepta-compat-服务", "account")?;
    let selected = entry
        .get_credential()
        .downcast_ref::<SsCredential>()
        .expect("default Linux builder must select the persistent Secret Service provider");
    assert_eq!(
        (&selected.attributes, &selected.label),
        (&secret_service.attributes, &secret_service.label)
    );
    Ok(())
}

#[test]
fn service_user_and_target_namespace_remain_compatible() -> keyring::Result<()> {
    let service = "hepta-compat-服务";
    let user = "account-用户";
    let implicit = SsCredential::new_with_target(/*target*/ None, service, user)?;
    let explicit = SsCredential::new_with_target(Some("default"), service, user)?;
    assert_eq!(
        (&implicit.attributes, &implicit.label),
        (&explicit.attributes, &explicit.label)
    );
    assert_eq!(
        implicit.attributes,
        HashMap::from([
            ("service".to_owned(), service.to_owned()),
            ("username".to_owned(), user.to_owned()),
            ("target".to_owned(), "default".to_owned()),
            ("application".to_owned(), "rust-keyring".to_owned()),
        ])
    );
    let alternate = SsCredential::new_with_target(Some("alternate"), service, user)?;
    let mut expected = explicit.attributes;
    expected.insert("target".to_owned(), "alternate".to_owned());
    assert_eq!(alternate.attributes, expected);
    assert!(matches!(
        SsCredential::new_with_target(Some(""), service, user),
        Err(keyring::Error::Invalid(_, _))
    ));
    Ok(())
}
