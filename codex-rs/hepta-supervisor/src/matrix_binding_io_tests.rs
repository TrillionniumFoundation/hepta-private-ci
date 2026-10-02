//! Real substitution across the binding reader's existing metadata/open cut.

use std::io;

use super::read_binding_after_metadata;
use crate::SupervisorError;
use crate::regular_file_io::tests::make_fifo;
use crate::regular_file_io::tests::with_fifo_watchdog;

#[test]
fn fifo_swap_after_binding_metadata_is_rejected_before_watchdog_release() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("binding.json");
    std::fs::write(&path, b"{}")?;
    let metadata = std::fs::symlink_metadata(&path)?;
    assert!(metadata.file_type().is_file());
    let fifo = directory.path().join("replacement.fifo");
    make_fifo(&fifo)?;
    std::fs::rename(&fifo, &path)?;
    let result = with_fifo_watchdog(&path, || read_binding_after_metadata(&path, &metadata))?;
    assert!(
        matches!(result, Err(SupervisorError::Io(error)) if error.kind() == io::ErrorKind::InvalidData)
    );
    assert!(!std::fs::symlink_metadata(&path)?.file_type().is_file());
    Ok(())
}
