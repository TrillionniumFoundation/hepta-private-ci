use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PrivateIssuerRegistryDocument;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

#[cfg(unix)]
pub(crate) fn issuer_registration(
    issuer_id: &str,
    key_epoch: u64,
    key: &SigningKey,
    revoked: bool,
) -> IssuerRegistration {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().expect("private issuer registry root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private issuer registry root mode");
    let path = root.path().join("issuer-registry.json");
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .expect("create private issuer registry");
    serde_json::to_writer(
        &mut file,
        &serde_json::json!({
            "issuer_id": issuer_id,
            "key_epoch": key_epoch,
            "public_key_hex": public_key_hex,
            "revoked": revoked,
        }),
    )
    .expect("write private issuer registry");
    file.flush().expect("flush private issuer registry");
    file.sync_all().expect("sync private issuer registry");
    let registry = PrivateIssuerRegistryDocument::load(&path, root.path(), 16 * 1024)
        .expect("load private issuer registry");
    registry
        .message_issuer(
            &StableId::new(issuer_id.to_owned()).expect("issuer id"),
            Generation::new(key_epoch).expect("issuer epoch"),
        )
        .expect("resolve sealed issuer")
}

#[cfg(not(unix))]
pub(crate) fn issuer_registration(
    _issuer_id: &str,
    _key_epoch: u64,
    _key: &SigningKey,
    _revoked: bool,
) -> IssuerRegistration {
    panic!("private issuer registries require Unix metadata semantics")
}
