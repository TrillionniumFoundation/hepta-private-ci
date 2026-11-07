use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use super::*;

static NEXT: AtomicU64 = AtomicU64::new(0);
type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Directory(PathBuf);
impl Directory {
    fn new() -> TestResult<Self> {
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-owned-control-{}-{id}", std::process::id()));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn request(id: &str) -> InferenceRequest {
    InferenceRequest {
        request_id: id.into(),
        principal_id: "file-owner".into(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        maximum_tokens: 16,
        deadline_ms: 1000,
        semantic_digest: "3".repeat(64),
    }
}

#[test]
fn supplied_file_replays_from_start_and_does_not_reopen_a_replaced_path() -> TestResult {
    let directory = Directory::new()?;
    let path = directory.0.join("control");
    let moved = directory.0.join("retained-inode");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)?;
    let mut control = DurableInferenceControl::open_file(file, &path, /*capacity*/ 8)?;
    let first = control.submit(10, request("first"))?;
    drop(control);
    let mut file = OpenOptions::new().read(true).append(true).open(&path)?;
    let mut shared_offset = file.try_clone()?;
    file.seek(SeekFrom::End(0))?;
    fs::rename(&path, &moved)?;
    fs::write(&path, b"replacement must remain untouched")?;
    let mut control = DurableInferenceControl::open_file(file, &path, /*capacity*/ 8)?;
    assert_eq!(
        control.get("first").map(|r| r.revision),
        Some(first.revision)
    );
    shared_offset.rewind()?;
    control.submit(11, request("second"))?;
    drop(shared_offset);
    drop(control);
    assert_eq!(fs::read(&path)?, b"replacement must remain untouched");
    let file = OpenOptions::new().read(true).append(true).open(&moved)?;
    let control = DurableInferenceControl::open_file(file, &moved, /*capacity*/ 8)?;
    assert!(control.get("first").is_some());
    assert!(control.get("second").is_some());
    Ok(())
}

#[test]
fn supplied_descriptor_requires_actual_read_and_append_flags_before_replay() -> TestResult {
    let directory = Directory::new()?;
    let path = directory.0.join("control");
    let mut original = DurableInferenceControl::open(&path, /*capacity*/ 8)?;
    original.submit(10, request("retained"))?;
    drop(original);
    let bytes = fs::read(&path)?;
    for file in [
        OpenOptions::new().read(true).open(&path)?,
        OpenOptions::new().read(true).write(true).open(&path)?,
        OpenOptions::new().append(true).open(&path)?,
    ] {
        assert!(matches!(
            DurableInferenceControl::open_file(file, &path, /*capacity*/ 8),
            Err(Error::CorruptJournal(
                "journal requires O_RDWR and O_APPEND"
            ))
        ));
        assert_eq!(fs::read(&path)?, bytes);
    }
    let original = DurableInferenceControl::open(&path, /*capacity*/ 8)?;
    assert!(original.get("retained").is_some());
    Ok(())
}

#[test]
fn supplied_file_keeps_the_existing_exclusive_writer_and_corruption_checks() -> TestResult {
    let directory = Directory::new()?;
    let path = directory.0.join("control");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)?;
    let control = DurableInferenceControl::open_file(file, &path, /*capacity*/ 8)?;
    let second = OpenOptions::new().read(true).append(true).open(&path)?;
    assert!(matches!(
        DurableInferenceControl::open_file(second, &path, /*capacity*/ 8),
        Err(Error::WriterUnavailable)
    ));
    drop(control);
    fs::write(&path, b"unwitnessed truncated event")?;
    let original = fs::read(&path)?;
    let file = OpenOptions::new().read(true).append(true).open(&path)?;
    assert!(matches!(
        DurableInferenceControl::open_file(file, &path, /*capacity*/ 8),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(fs::read(path)?, original);
    Ok(())
}

#[test]
fn supplied_file_treats_proc_and_missing_parent_paths_as_diagnostic_labels() -> TestResult {
    let directory = Directory::new()?;
    let missing_parent = directory.0.join("absent-diagnostic-parent");
    for index in 0..2 {
        let path = directory.0.join(format!("control-{index}"));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .append(true)
            .open(&path)?;
        // The host, not the diagnostic label, owns directory-entry durability.
        File::open(&directory.0)?.sync_all()?;
        let label = if index == 0 {
            PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()))
        } else {
            missing_parent.join("not-a-journal")
        };
        let mut control = DurableInferenceControl::open_file(file, &label, /*capacity*/ 8)?;
        assert_eq!(control.journal_path(), label);
        let receipt = control.submit(10, request("retained"))?;
        drop(control);
        let bytes = fs::read(&path)?;
        assert!(!bytes.is_empty());
        let file = OpenOptions::new().read(true).append(true).open(&path)?;
        let control = DurableInferenceControl::open_file(file, &label, /*capacity*/ 8)?;
        assert_eq!(
            control.get("retained").map(|r| r.revision),
            Some(receipt.revision)
        );
        assert_eq!(fs::read(&path)?, bytes);
        assert!(!missing_parent.exists());
    }
    Ok(())
}

#[test]
fn path_constructor_still_requires_its_actual_parent_sync() -> TestResult {
    let directory = Directory::new()?;
    let path = directory.0.join("control");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .append(true)
        .open(&path)?;
    let alias = PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()));
    let actual = file.metadata()?;
    let resolved = File::open(&alias)?.metadata()?;
    assert_eq!(
        (actual.dev(), actual.ino()),
        (resolved.dev(), resolved.ino())
    );
    // procfs can name this real file, but cannot durably sync directory entries.
    // Path-based construction must retain that failure, not silently bypass it.
    let sync_error = match File::open("/proc/self/fd")?.sync_all() {
        Err(error) => error.to_string(),
        Ok(()) => panic!("procfs unexpectedly supports directory-entry sync"),
    };
    assert!(matches!(
        DurableInferenceControl::open(&alias, /*capacity*/ 8),
        Err(Error::Io(message)) if message == sync_error
    ));
    assert!(fs::read(path)?.is_empty());
    Ok(())
}
