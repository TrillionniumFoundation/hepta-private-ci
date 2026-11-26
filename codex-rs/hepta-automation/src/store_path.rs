//! Prepare one private Automation root without accepting filesystem redirects.

use std::fs;
use std::path::Path;
use std::path::PathBuf;

use super::AutomationError;
use super::unavailable;

pub(super) fn create_private_directory(path: &Path) -> Result<PathBuf, AutomationError> {
    fs::create_dir_all(path).map_err(unavailable)?;
    let canonical = path.canonicalize().map_err(unavailable)?;
    if !same_components(&canonical, path) {
        return Err(AutomationError::Invalid);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;

        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        for ancestor in path.ancestors() {
            if fs::symlink_metadata(ancestor)
                .map_err(unavailable)?
                .file_attributes()
                & FILE_ATTRIBUTE_REPARSE_POINT
                != 0
            {
                return Err(AutomationError::Invalid);
            }
        }
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&canonical, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
    }
    // Use one database identity for ordinary and OS-verbatim Windows spellings.
    Ok(canonical)
}

#[cfg(not(windows))]
fn same_components(canonical: &Path, requested: &Path) -> bool {
    canonical == requested
}

#[cfg(windows)]
fn same_components(canonical: &Path, requested: &Path) -> bool {
    use std::path::Component;
    use std::path::Prefix;

    let mut canonical = canonical.components();
    let mut requested = requested.components();
    let (Some(Component::Prefix(left)), Some(Component::Prefix(right))) =
        (canonical.next(), requested.next())
    else {
        return false;
    };
    let same_prefix = match (left.kind(), right.kind()) {
        (
            Prefix::Disk(left) | Prefix::VerbatimDisk(left),
            Prefix::Disk(right) | Prefix::VerbatimDisk(right),
        ) => left == right,
        (
            Prefix::UNC(left_server, left_share) | Prefix::VerbatimUNC(left_server, left_share),
            Prefix::UNC(right_server, right_share) | Prefix::VerbatimUNC(right_server, right_share),
        ) => left_server == right_server && left_share == right_share,
        _ => false,
    };
    same_prefix && canonical.eq(requested)
}

#[cfg(test)]
#[path = "store_path_tests.rs"]
mod tests;
