//! Filesystem-backed canonical identity checks for the legacy store opener.
//!
//! This checks an existing path; it is not a descriptor-bound recovery guard.

use std::io;
use std::path::Path;
use std::path::PathBuf;

/// Return the OS canonical spelling only when no path component redirects it.
/// Windows spellings are resolved from a no-reparse handle, not case folding.
pub(crate) fn canonical_path_without_redirection(path: &Path) -> io::Result<Option<PathBuf>> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        use std::path::Component;

        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        if !path.is_absolute()
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir))
        {
            return Ok(None);
        }
        for ancestor in path.ancestors() {
            if std::fs::symlink_metadata(ancestor)?.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT
                != 0
            {
                return Ok(None);
            }
        }
        // NtCreateFile refuses reparse traversal atomically, including a swap
        // after the diagnostic checks above. The returned spelling comes from
        // the actual retained object, so case and 8.3 aliases converge without
        // merging separate objects in a case-sensitive directory. This legacy
        // path observation does not replace the owner's retained recovery guard.
        codex_utils_path::canonical_existing_path_without_reparse(path).map(Some)
    }
    #[cfg(not(windows))]
    {
        let canonical = path.canonicalize()?;
        Ok((canonical == path).then_some(canonical))
    }
}

#[cfg(test)]
#[path = "cognitive_path_tests.rs"]
mod tests;
