//! Bounded reads of host-owned trust/configuration files from one verified handle.

use std::fs;
use std::io::Read;
use std::path::Path;

use crate::AgentdError;

pub(crate) fn read_protected_file(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be absolute, canonical and symlink-free"
        )));
    }
    // Reject ordinary nonregular paths before opening, including FIFOs.
    if !fs::symlink_metadata(path)?.is_file() {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    read_opened_file(path, fs::File::open(path)?, max_bytes, label)
}

fn read_opened_file(
    path: &Path,
    file: fs::File,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    let metadata = file.metadata()?;
    let linked = fs::symlink_metadata(path)?;
    if !metadata.is_file() || !linked.is_file() || path.canonicalize()? != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular canonical non-symlink file"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if metadata.dev() != linked.dev() || metadata.ino() != linked.ino() {
            return Err(AgentdError::Invalid(format!(
                "{label} changed identity while opening"
            )));
        }
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    let limit = max_bytes
        .checked_add(1)
        .ok_or_else(|| AgentdError::Invalid(format!("{label} has an invalid read bound")))?;
    let mut bytes = Vec::new();
    // The same handle supplies metadata and bytes. A concurrent growth cannot
    // turn the metadata check into an unbounded allocation or a second open.
    file.take(limit).read_to_end(&mut bytes)?;
    if bytes.is_empty() || u64::try_from(bytes.len()).unwrap_or(u64::MAX) > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    Ok(bytes)
}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::PermissionsExt;

    use super::*;

    #[allow(
        clippy::expect_used,
        reason = "private file fixtures must fail before exercising trust-file reads"
    )]
    fn fixture() -> (tempfile::TempDir, std::path::PathBuf) {
        let temp = tempfile::tempdir().expect("private file fixture");
        let path = temp
            .path()
            .canonicalize()
            .expect("canonical root")
            .join("trust.json");
        fs::write(&path, b"trusted").expect("fixture contents");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private mode");
        (temp, path)
    }

    #[test]
    #[expect(
        clippy::expect_used,
        reason = "private fixtures must fail before checking protected reads"
    )]
    fn opened_handle_cannot_be_rebound_to_a_replacement_path() {
        let (_temp, path) = fixture();
        let opened = fs::File::open(&path).expect("old handle");
        fs::rename(&path, path.with_extension("retired")).expect("replace old name");
        fs::write(&path, b"replacement").expect("replacement contents");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private replacement");
        assert!(read_opened_file(&path, opened, /*max_bytes*/ 64, "fixture").is_err());
    }

    #[test]
    #[expect(
        clippy::expect_used,
        reason = "private fixtures must fail before checking protected reads"
    )]
    fn opened_handle_cannot_be_rebound_through_a_symlink() {
        let (_temp, path) = fixture();
        let opened = fs::File::open(&path).expect("old handle");
        let retired = path.with_extension("retired");
        fs::rename(&path, &retired).expect("retire old name");
        std::os::unix::fs::symlink(&retired, &path).expect("substitute symlink");
        assert!(read_opened_file(&path, opened, /*max_bytes*/ 64, "fixture").is_err());
    }

    #[test]
    #[expect(
        clippy::expect_used,
        reason = "private fixtures must fail before checking protected reads"
    )]
    fn handle_permissions_and_actual_read_bound_are_enforced() {
        let (_temp, path) = fixture();
        assert_eq!(
            read_protected_file(&path, /*max_bytes*/ 7, "fixture").expect("bounded read"),
            b"trusted"
        );
        assert!(read_protected_file(&path, /*max_bytes*/ 6, "fixture").is_err());
        let opened = fs::File::open(&path).expect("old handle");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("expose fixture");
        assert!(read_opened_file(&path, opened, /*max_bytes*/ 64, "fixture").is_err());
    }
}
