//! Filesystem-backed canonical identity checks for the legacy store opener.
//!
//! This checks an existing path; it is not a descriptor-bound recovery guard.

use std::io;
use std::path::Path;
use std::path::PathBuf;

/// Return the OS canonical spelling only when no path component redirects it.
/// Windows drive/UNC verbatim prefixes are namespace spellings, not redirects.
pub(crate) fn canonical_path_without_redirection(path: &Path) -> io::Result<Option<PathBuf>> {
    let canonical = path.canonicalize()?;
    if !same_components(&canonical, path) {
        return Ok(None);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;

        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        for ancestor in path.ancestors() {
            if std::fs::symlink_metadata(ancestor)?.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT
                != 0
            {
                return Ok(None);
            }
        }
    }
    Ok(Some(canonical))
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
#[path = "cognitive_path_tests.rs"]
mod tests;
