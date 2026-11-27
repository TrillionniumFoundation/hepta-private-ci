//! Physical byte sensitivity, bounded reads and retained lock/cursor state.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::ObservationError;
use super::read;

struct TestFile(PathBuf);

impl TestFile {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "hepta-evaluation-file-observation-{}-{}",
            std::process::id(),
            NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed)
        )))
    }

    fn create(&self, readable: bool) -> File {
        OpenOptions::new()
            .read(readable)
            .write(true)
            .create_new(true)
            .open(&self.0)
            .unwrap()
    }

    fn contender(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .unwrap()
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[test]
fn original_handle_bytes_detect_equal_length_changes_and_retain_lock_and_cursor() {
    let path = TestFile::new();
    let mut owner = path.create(/*readable*/ true);
    owner.try_lock().unwrap();
    owner.write_all(b"first").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    let before = read(&mut owner, /*maximum_bytes*/ 32).unwrap();
    assert_eq!(before, b"first");
    assert_eq!(owner.stream_position().unwrap(), 2);
    let contender = path.contender();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    #[cfg(windows)]
    assert_eq!(fs::read(&path.0).unwrap_err().raw_os_error(), Some(33));

    owner.rewind().unwrap();
    owner.write_all(b"other").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    let after = read(&mut owner, /*maximum_bytes*/ 32).unwrap();
    assert_eq!(after, b"other");
    assert_eq!(after.len(), before.len());
    assert_ne!(after, before);
    assert_eq!(owner.stream_position().unwrap(), 2);
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
}

#[test]
fn bounded_original_handle_reads_restore_cursor_after_io_error() {
    let path = TestFile::new();
    let mut owner = path.create(/*readable*/ false);
    owner.try_lock().unwrap();
    owner.write_all(b"first").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    for maximum_bytes in [0, 4, 8 * 1024 * 1024 + 1] {
        assert!(matches!(
            read(&mut owner, maximum_bytes),
            Err(ObservationError::Capacity)
        ));
        assert_eq!(owner.stream_position().unwrap(), 2);
    }
    assert!(matches!(
        read(&mut owner, /*maximum_bytes*/ 32),
        Err(ObservationError::Io(_))
    ));
    assert_eq!(owner.stream_position().unwrap(), 2);
    let contender = path.contender();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
}
