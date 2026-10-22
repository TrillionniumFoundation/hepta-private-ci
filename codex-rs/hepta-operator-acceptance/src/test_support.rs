#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use sha2::Digest as _;
use sha2::Sha256;
use sha2::Sha512;
use tempfile::TempDir;

pub(crate) struct PrivateTempDir {
    _temporary: TempDir,
    path: std::path::PathBuf,
}

impl PrivateTempDir {
    pub(crate) fn path(&self) -> &std::path::Path {
        &self.path
    }
}

pub(crate) fn private_tempdir(label: &str) -> PrivateTempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    #[cfg(not(windows))]
    let path = temporary.path().to_path_buf();
    #[cfg(windows)]
    let path = {
        // Only create a new fixture leaf. Never harden tempfile's existing ACL.
        let path = temporary.path().join("private");
        assert!(!path.exists());
        let directory = codex_utils_path::open_private_state_directory(&path)
            .unwrap_or_else(|error| panic!("create private {label}: {error}"));
        codex_utils_path::private_state_snapshot(&directory).expect("private fixture parent");
        path
    };
    PrivateTempDir {
        _temporary: temporary,
        path,
    }
}

#[cfg(windows)]
#[path = "windows_custody_test_support.rs"]
pub(crate) mod windows_custody;

// This module is compiled only for tests. These ephemeral fixture keys are never
// operator keys and never mint deployment authority. Frozen OpenSSH-produced
// signatures in sshsig_tests retain independent format interoperability coverage.
pub(crate) struct TestSshKey(SigningKey);

impl TestSshKey {
    pub(crate) fn new() -> Self {
        Self(SigningKey::from_bytes(&rand::random()))
    }

    fn public_blob(&self) -> Vec<u8> {
        let mut blob = Vec::new();
        append_ssh_string(&mut blob, b"ssh-ed25519");
        append_ssh_string(&mut blob, self.0.verifying_key().as_bytes());
        blob
    }

    pub(crate) fn public_key(&self) -> String {
        format!("ssh-ed25519 {}", STANDARD.encode(self.public_blob()))
    }

    pub(crate) fn fingerprint(&self) -> String {
        format!(
            "SHA256:{}",
            STANDARD_NO_PAD.encode(Sha256::digest(self.public_blob()))
        )
    }

    pub(crate) fn sign(&self, statement: &[u8], namespace: &str) -> Vec<u8> {
        let mut signed = b"SSHSIG".to_vec();
        append_ssh_string(&mut signed, namespace.as_bytes());
        append_ssh_string(&mut signed, b"");
        append_ssh_string(&mut signed, b"sha512");
        append_ssh_string(&mut signed, &Sha512::digest(statement));
        let signature = self.0.sign(&signed);
        let mut signature_blob = Vec::new();
        append_ssh_string(&mut signature_blob, b"ssh-ed25519");
        append_ssh_string(&mut signature_blob, &signature.to_bytes());

        let mut packet = b"SSHSIG".to_vec();
        packet.extend_from_slice(&1_u32.to_be_bytes());
        append_ssh_string(&mut packet, &self.public_blob());
        append_ssh_string(&mut packet, namespace.as_bytes());
        append_ssh_string(&mut packet, b"");
        append_ssh_string(&mut packet, b"sha512");
        append_ssh_string(&mut packet, &signature_blob);
        let mut armor = b"-----BEGIN SSH SIGNATURE-----\n".to_vec();
        for line in STANDARD.encode(packet).as_bytes().chunks(70) {
            armor.extend_from_slice(line);
            armor.push(b'\n');
        }
        armor.extend_from_slice(b"-----END SSH SIGNATURE-----\n");
        armor
    }
}

fn append_ssh_string(output: &mut Vec<u8>, value: &[u8]) {
    output.extend_from_slice(
        &u32::try_from(value.len())
            .expect("bounded fixture SSH string")
            .to_be_bytes(),
    );
    output.extend_from_slice(value);
}
