#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

pub(crate) struct TestSshIdentity {
    #[cfg(unix)]
    pub(crate) private_key: std::path::PathBuf,
    pub(crate) public_blob: String,
    pub(crate) fingerprint: String,
}

#[cfg(unix)]
pub(crate) fn test_ssh_identity(root: &std::path::Path) -> TestSshIdentity {
    use std::process::Command;

    let private_key = root.join("operator-key");
    let generated = Command::new("/usr/bin/ssh-keygen")
        .args(["-q", "-t", "ed25519", "-N", "", "-f"])
        .arg(&private_key)
        .status()
        .expect("start test-only ssh-keygen");
    assert!(generated.success(), "generate test-only Ed25519 key");
    let public_key = private_key.with_extension("pub");
    let public = std::fs::read_to_string(&public_key).expect("read generated public key");
    let mut fields = public.split_ascii_whitespace();
    assert_eq!(fields.next(), Some("ssh-ed25519"));
    let public_blob = fields.next().expect("OpenSSH public key blob").to_string();

    let output = Command::new("/usr/bin/ssh-keygen")
        .args(["-E", "sha256", "-lf"])
        .arg(public_key)
        .output()
        .expect("fingerprint test-only public key");
    assert!(output.status.success(), "fingerprint test-only Ed25519 key");
    let fingerprint = std::str::from_utf8(&output.stdout)
        .expect("UTF-8 fingerprint output")
        .split_ascii_whitespace()
        .nth(1)
        .expect("OpenSSH fingerprint field")
        .to_string();
    TestSshIdentity {
        private_key,
        public_blob,
        fingerprint,
    }
}

#[cfg(not(unix))]
pub(crate) fn test_ssh_identity(_root: &std::path::Path) -> TestSshIdentity {
    use base64::Engine as _;
    use base64::engine::general_purpose::STANDARD;
    use base64::engine::general_purpose::STANDARD_NO_PAD;
    use sha2::Digest as _;

    // Provide public material for the portable policy and challenge tests.
    // Verification still fails closed without the Unix descriptor backend.
    let public = ed25519_dalek::SigningKey::from_bytes(&[42; 32]).verifying_key();
    let mut blob = 11_u32.to_be_bytes().to_vec();
    blob.extend_from_slice(b"ssh-ed25519");
    blob.extend_from_slice(&32_u32.to_be_bytes());
    blob.extend_from_slice(public.as_bytes());
    TestSshIdentity {
        public_blob: STANDARD.encode(&blob),
        fingerprint: format!(
            "SHA256:{}",
            STANDARD_NO_PAD.encode(sha2::Sha256::digest(&blob))
        ),
    }
}

#[cfg(not(unix))]
pub(crate) const UNSUPPORTED_SSHSIG_TEST_ENVELOPE: &[u8] =
    b"-----BEGIN SSH SIGNATURE-----\nbackend-unavailable-test\n-----END SSH SIGNATURE-----\n";
