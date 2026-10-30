use std::path::Path;
use std::path::PathBuf;

use codex_utils_path_uri::PathUri;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;

/// Restore the registered native spelling after a lossless workspace URI hop.
/// Windows canonical roots have a verbatim prefix which file URIs omit. Only
/// the canonical path or its exact URI rendering is accepted; arbitrary
/// symlink, parent-component and relative aliases do not gain authority.
pub(crate) fn canonical_workspace_path(path: &Path) -> Option<PathBuf> {
    // Windows path equality can normalize a `child/..` spelling into an
    // accepted URI path. Reject traversal lexically before canonicalization.
    if !path.is_absolute()
        || path
            .components()
            .any(|component| component.as_os_str() == std::ffi::OsStr::new(".."))
    {
        return None;
    }
    let canonical = std::fs::canonicalize(path).ok()?;
    if path == canonical {
        return Some(canonical);
    }
    let transported = PathUri::from_host_native_path(&canonical)
        .ok()?
        .to_path_buf();
    (path == transported).then_some(canonical)
}

pub(crate) fn workspace_digest(path: &Path) -> Sha256Digest {
    codex_hepta_memory::workspace_binding_digest(path)
}

#[cfg(unix)]
pub(crate) fn path_identity_bytes(path: &Path) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt;

    path.as_os_str().as_bytes().to_vec()
}

#[cfg(windows)]
pub(crate) fn path_identity_bytes(path: &Path) -> Vec<u8> {
    use std::os::windows::ffi::OsStrExt;

    path.as_os_str()
        .encode_wide()
        .flat_map(u16::to_le_bytes)
        .collect()
}

#[cfg(not(any(unix, windows)))]
pub(crate) fn path_identity_bytes(path: &Path) -> Vec<u8> {
    path.as_os_str().to_string_lossy().as_bytes().to_vec()
}

pub(crate) fn domain_digest(domain: &[u8], value: &[u8]) -> Sha256Digest {
    digest_many(domain, &[value])
}

pub(crate) fn digest_many(domain: &[u8], values: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, domain);
    for value in values {
        hash_part(&mut hasher, value);
    }
    Sha256Digest::for_bytes(&hasher.finalize())
}

pub(crate) fn hash_part(hasher: &mut Sha256, part: &[u8]) {
    hasher.update((part.len() as u64).to_be_bytes());
    hasher.update(part);
}

#[cfg(test)]
#[path = "framing_tests.rs"]
mod tests;
