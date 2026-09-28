//! Test-only persisted registry fixture. Never exported by the production crate.

use std::fmt::Write as _;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PrivateIssuerRegistryDocument;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;

pub(crate) fn message_registration(
    issuer_id: StableId,
    key_epoch: Generation,
    verifying_key: VerifyingKey,
    revoked: bool,
) -> IssuerRegistration {
    let root = tempfile::tempdir().expect("registry fixture directory");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private registry directory");
    let path = root.path().join("message-issuer.json");
    let mut temporary = tempfile::NamedTempFile::new_in(root.path()).expect("registry file");
    temporary.as_file().set_permissions(std::fs::Permissions::from_mode(0o600))
        .expect("private registry file");
    let mut public_key_hex = String::new();
    for byte in verifying_key.as_bytes() {
        write!(&mut public_key_hex, "{byte:02x}").expect("hex encoding");
    }
    serde_json::to_writer(temporary.as_file_mut(), &serde_json::json!({
        "issuer_id": issuer_id.as_str(),
        "key_epoch": key_epoch.get(),
        "public_key_hex": public_key_hex,
        "revoked": revoked,
    })).expect("registry fixture document");
    temporary.as_file().sync_all().expect("registry fsync");
    temporary.persist(&path).expect("publish registry fixture");
    std::fs::File::open(root.path()).expect("registry directory handle")
        .sync_all().expect("registry directory fsync");
    PrivateIssuerRegistryDocument::load(&path, root.path(), 16 * 1024)
        .expect("load persisted registry")
        .message_issuer(&issuer_id, key_epoch)
        .expect("resolve sealed registration")
}
