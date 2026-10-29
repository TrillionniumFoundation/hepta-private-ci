#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use sha2::Digest as _;
use sha2::Sha256;
use sha2::Sha512;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

/// Deterministic, test-only key material. Production still delegates SSHSIG
/// verification to its pinned Unix OpenSSH executable and inherited pipes.
pub(crate) struct TestSshKey(SigningKey);

impl TestSshKey {
    pub(crate) fn new() -> Self {
        Self(SigningKey::from_bytes(&[42; 32]))
    }

    fn public_blob(&self) -> Vec<u8> {
        let mut blob = ssh_string(b"ssh-ed25519");
        blob.extend(ssh_string(self.0.verifying_key().as_bytes()));
        blob
    }

    pub(crate) fn allowed_signer(&self) -> String {
        format!(
            "operator@example ssh-ed25519 {}\n",
            STANDARD.encode(self.public_blob())
        )
    }

    pub(crate) fn fingerprint(&self) -> String {
        format!(
            "SHA256:{}",
            STANDARD_NO_PAD.encode(Sha256::digest(self.public_blob()))
        )
    }

    pub(crate) fn sign(&self, statement: &[u8], namespace: &str) -> Vec<u8> {
        // OpenSSH PROTOCOL.sshsig sections 2 and 3: the signature covers the
        // domain-separated message digest, not the envelope's version/key.
        let mut signed = b"SSHSIG".to_vec();
        signed.extend(ssh_string(namespace.as_bytes()));
        signed.extend(ssh_string(b""));
        signed.extend(ssh_string(b"sha512"));
        signed.extend(ssh_string(&Sha512::digest(statement)));
        let mut signature = ssh_string(b"ssh-ed25519");
        signature.extend(ssh_string(&self.0.sign(&signed).to_bytes()));

        let mut blob = b"SSHSIG".to_vec();
        blob.extend(1_u32.to_be_bytes());
        blob.extend(ssh_string(&self.public_blob()));
        blob.extend(ssh_string(namespace.as_bytes()));
        blob.extend(ssh_string(b""));
        blob.extend(ssh_string(b"sha512"));
        blob.extend(ssh_string(&signature));
        let encoded = STANDARD.encode(blob);
        let mut armored = b"-----BEGIN SSH SIGNATURE-----\n".to_vec();
        for line in encoded.as_bytes().chunks(76) {
            armored.extend(line);
            armored.push(b'\n');
        }
        armored.extend(b"-----END SSH SIGNATURE-----\n");
        armored
    }
}

fn ssh_string(bytes: &[u8]) -> Vec<u8> {
    let mut encoded = u32::try_from(bytes.len())
        .expect("test SSH string length")
        .to_be_bytes()
        .to_vec();
    encoded.extend(bytes);
    encoded
}
