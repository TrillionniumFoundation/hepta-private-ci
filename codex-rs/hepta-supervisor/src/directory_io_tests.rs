//! A real observed directory is replaced at the shared sync-open boundary.

use std::io;

use super::sync_directory;
use crate::regular_file_io::tests::make_fifo;
use crate::regular_file_io::tests::with_fifo_watchdog;

#[test]
fn fifo_swap_after_directory_observation_is_rejected_before_watchdog_release() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let parent = temporary.path().join("parent");
    std::fs::create_dir(&parent)?;
    std::fs::write(parent.join("retained-state"), b"exact durable contents")?;
    let observed = std::fs::symlink_metadata(&parent)?;
    assert!(observed.is_dir() && !observed.file_type().is_symlink());
    sync_directory(&parent)?;

    let fifo = temporary.path().join("replacement-fifo");
    make_fifo(&fifo)?;
    let retained = temporary.path().join("retained-directory");
    std::fs::rename(&parent, &retained)?;
    std::fs::rename(&fifo, &parent)?;
    let result = with_fifo_watchdog(&parent, || sync_directory(&parent))?;
    assert_eq!(
        result
            .expect_err("directory sync must reject the substituted FIFO")
            .kind(),
        io::ErrorKind::NotADirectory
    );
    assert!(!std::fs::symlink_metadata(&parent)?.is_dir());
    assert_eq!(
        std::fs::read(retained.join("retained-state"))?,
        b"exact durable contents"
    );
    Ok(())
}
