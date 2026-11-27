use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_utils_absolute_path::AbsolutePathBuf;
use sha2::Digest;
use sha2::Sha256;

/// Recover the registered physical spelling after a transport URI roundtrip.
/// Windows URI paths omit the verbatim prefix used by canonical registry paths.
/// Namespace spelling may differ; symlink traversal, parent components, missing
/// roots and non-directory workspaces must still fail closed.
pub(crate) fn registered_workspace_path(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute()
        || path
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return None;
    }
    let canonical = path.canonicalize().ok()?;
    if !canonical.is_dir()
        || AbsolutePathBuf::from_absolute_path_checked(path).ok()?
            != AbsolutePathBuf::from_absolute_path_checked(&canonical).ok()?
    {
        return None;
    }
    Some(canonical)
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
