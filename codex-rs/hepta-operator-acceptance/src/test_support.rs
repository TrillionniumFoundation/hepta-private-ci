#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

pub(crate) fn test_key(root: &Path) -> (PathBuf, String, String) {
    let key = root.join("operator-key");
    #[cfg(unix)]
    {
        let generated = std::process::Command::new("/usr/bin/ssh-keygen")
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .status()
            .expect("start test key generation");
        assert!(generated.success(), "generate test-only Ed25519 key");
        let public = std::fs::read_to_string(key.with_extension("pub")).expect("read public key");
        let output = std::process::Command::new("/usr/bin/ssh-keygen")
            .args(["-E", "sha256", "-lf"])
            .arg(key.with_extension("pub"))
            .output()
            .expect("fingerprint test public key");
        assert!(output.status.success());
        let fingerprint = std::str::from_utf8(&output.stdout)
            .expect("UTF-8 fingerprint")
            .split_ascii_whitespace()
            .nth(1)
            .expect("OpenSSH fingerprint field")
            .to_string();
        (key, public, fingerprint)
    }
    #[cfg(not(unix))]
    {
        use base64::Engine as _;
        use base64::engine::general_purpose::STANDARD;
        use base64::engine::general_purpose::STANDARD_NO_PAD;
        use sha2::Digest as _;

        // Policy parsing remains cross-platform. Only Unix signing tests need
        // a private key file or ssh-keygen; this is a real fixed Ed25519 key.
        let public = ed25519_dalek::SigningKey::from_bytes(&[91; 32])
            .verifying_key()
            .to_bytes();
        let mut blob = Vec::new();
        for value in [b"ssh-ed25519".as_slice(), public.as_slice()] {
            blob.extend(
                u32::try_from(value.len())
                    .expect("SSH string length")
                    .to_be_bytes(),
            );
            blob.extend(value);
        }
        let encoded = format!("ssh-ed25519 {} test-only\n", STANDARD.encode(&blob));
        let fingerprint = format!(
            "SHA256:{}",
            STANDARD_NO_PAD.encode(sha2::Sha256::digest(&blob))
        );
        (key, encoded, fingerprint)
    }
}

#[cfg(not(unix))]
pub(crate) fn capture_tree(root: &Path) -> std::collections::BTreeMap<PathBuf, Option<Vec<u8>>> {
    let mut result = std::collections::BTreeMap::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory).expect("read fixture tree") {
            let path = entry.expect("fixture entry").path();
            let relative = path
                .strip_prefix(root)
                .expect("fixture child")
                .to_path_buf();
            if path.is_dir() {
                result.insert(relative, None);
                pending.push(path);
            } else {
                result.insert(relative, Some(std::fs::read(path).expect("fixture bytes")));
            }
        }
    }
    result
}
