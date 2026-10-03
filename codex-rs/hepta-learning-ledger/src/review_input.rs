//! Read-only protected inputs shared by ordinary hosts and finite review purposes.
use std::path::Path;
use crate::protected_review_files as files;
use files::Access;
use files::ReviewResult;

/// Open an immutable root-owned review input for a read-only consumer.
pub fn open_root_review_input(path: &Path) -> ReviewResult<std::fs::File> {
    files::root_file(path, Access::Immutable)
}
/// Read a bounded immutable root-owned review input.
pub fn read_root_review_input(path: &Path, maximum: u64) -> ReviewResult<Vec<u8>> {
    files::read_root(path, maximum, Access::Immutable)
}
