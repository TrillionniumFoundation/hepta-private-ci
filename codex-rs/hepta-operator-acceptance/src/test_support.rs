use std::fs::OpenOptions;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;
use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

pub(crate) enum SigningMode {
    Unsigned,
    OpenSsh,
}

// Policy-only tests need a valid public key and fingerprint, without an OpenSSH process.
// This deterministic test identity never signs a statement or creates a private-key file.
pub(crate) fn unsigned_ssh_public_key() -> (String, String) {
    let public_key = SigningKey::from_bytes(&[0x42; 32]).verifying_key();
    let mut blob = Vec::with_capacity(/*capacity*/ 51);
    blob.extend_from_slice(&11_u32.to_be_bytes());
    blob.extend_from_slice(b"ssh-ed25519");
    blob.extend_from_slice(&32_u32.to_be_bytes());
    blob.extend_from_slice(public_key.as_bytes());
    let public = format!("ssh-ed25519 {}", STANDARD.encode(&blob));
    let fingerprint = format!("SHA256:{}", STANDARD_NO_PAD.encode(Sha256::digest(&blob)));
    (public, fingerprint)
}

// Seed external policy/revocation inputs using the existing private fixture convention.
// Product challenge and assessment outputs still use the real durable writer.
pub(crate) fn write_private_fixture(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)
}
