use std::path::Path;
use std::path::PathBuf;

/// Restore the canonical identity used by WorkspaceBinding on Windows.
///
/// PathUri removes Windows namespace prefixes for transport. Authorization keeps
/// the original v1 digest of the canonical path; it does not equate digests of
/// different spellings. Only the existing namespace conversion is accepted:
/// following a symlink or changing another path component fails closed.
pub(super) fn from_transport(path: &Path) -> std::io::Result<PathBuf> {
    #[cfg(windows)]
    {
        use codex_utils_absolute_path::AbsolutePathBuf;

        let logical = AbsolutePathBuf::from_absolute_path_checked(path)?;
        let canonical = path.canonicalize()?;
        let canonical_logical = AbsolutePathBuf::from_absolute_path_checked(&canonical)?;
        if logical != canonical_logical || !canonical.is_dir() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "federated workspace must retain its canonical directory identity",
            ));
        }
        Ok(canonical)
    }
    #[cfg(not(windows))]
    {
        Ok(path.to_path_buf())
    }
}
