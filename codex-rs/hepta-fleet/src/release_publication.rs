use std::fs::Metadata;
use std::path::Path;

// The catalog is administrator-owned. A failed seal can be rolled back only
// while the published name still denotes our original writable directory.
// Recheck the moved directory before allowing the caller to clean its contents.
#[cfg(unix)]
pub(super) fn restore_unsealed_staging(
    published: &Path,
    staging: &Path,
    expected: &Metadata,
) -> bool {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let is_original_unsealed = |path: &Path| {
        std::fs::symlink_metadata(path).is_ok_and(|actual| {
            actual.file_type().is_dir()
                && actual.dev() == expected.dev()
                && actual.ino() == expected.ino()
                && actual.permissions().mode() & 0o222 != 0
        })
    };
    if !is_original_unsealed(published)
        || !matches!(std::fs::symlink_metadata(staging), Err(error) if error.kind() == std::io::ErrorKind::NotFound)
        || std::fs::rename(published, staging).is_err()
    {
        return false;
    }
    is_original_unsealed(staging)
}

#[cfg(not(unix))]
pub(super) fn restore_unsealed_staging(
    _published: &Path,
    _staging: &Path,
    _expected: &Metadata,
) -> bool {
    // Without a retained directory identity, leave the unsealed publication
    // rejected by catalog admission rather than deleting by pathname.
    false
}

#[cfg(all(test, unix))]
#[path = "release_publication_tests.rs"]
mod tests;
