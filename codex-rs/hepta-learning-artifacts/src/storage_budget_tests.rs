use super::*;

use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

struct Fixture(std::path::PathBuf);

impl Fixture {
    fn new() -> Result<(Self, File), Box<dyn Error>> {
        let path = std::env::temp_dir().join(format!(
            "hepta-artifact-read-budget-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed),
        ));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)?;
        Ok((Self(path), file))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[test]
fn wrong_exact_length_is_rejected_before_any_seek_or_read() -> Result<(), Box<dyn Error>> {
    for (limit, mismatch) in [
        (MAX_SNAPSHOT, ArtifactStorageError::Corrupt),
        (MAX_PAYLOAD, ArtifactStorageError::PayloadMismatch),
    ] {
        let (_fixture, mut file) = Fixture::new()?;
        file.set_len(limit as u64)?;
        file.seek(SeekFrom::Start(7))?;
        // This transient clone only observes the shared cursor; it is not
        // prelocked or used concurrently with the reader.
        let mut cursor = file.try_clone()?;
        assert_eq!(
            read_bounded(file, limit, /*expected_bytes*/ 1, mismatch),
            Err(mismatch)
        );
        assert_eq!(cursor.stream_position()?, 7);
        cursor.try_lock()?;
        cursor.unlock()?;
    }
    Ok(())
}

#[test]
fn short_nonempty_file_is_also_rejected_without_reading() -> Result<(), Box<dyn Error>> {
    let (_fixture, mut file) = Fixture::new()?;
    file.write_all(b"x")?;
    let mut cursor = file.try_clone()?;
    assert_eq!(
        read_bounded(
            file,
            MAX_PAYLOAD,
            /*expected_bytes*/ 2,
            ArtifactStorageError::PayloadMismatch
        ),
        Err(ArtifactStorageError::PayloadMismatch),
    );
    assert_eq!(cursor.stream_position()?, 1);
    Ok(())
}

#[test]
fn exact_file_is_read_from_start_even_with_a_nonzero_cursor() -> Result<(), Box<dyn Error>> {
    let (_fixture, mut file) = Fixture::new()?;
    file.write_all(b"exact bytes")?;
    assert_eq!(
        read_bounded(
            file,
            MAX_PAYLOAD,
            /*expected_bytes*/ 11,
            ArtifactStorageError::PayloadMismatch
        )?,
        b"exact bytes",
    );
    Ok(())
}

#[test]
fn global_ceiling_and_empty_payload_keep_capacity_semantics() -> Result<(), Box<dyn Error>> {
    for size in [0, MAX_PAYLOAD as u64 + 1] {
        let (_fixture, file) = Fixture::new()?;
        file.set_len(size)?;
        assert_eq!(
            read_bounded(
                file,
                MAX_PAYLOAD,
                /*expected_bytes*/ 1,
                ArtifactStorageError::PayloadMismatch
            ),
            Err(ArtifactStorageError::Capacity),
        );
    }
    let (_fixture, file) = Fixture::new()?;
    assert_eq!(
        read_bounded(
            file,
            MAX_PAYLOAD,
            MAX_PAYLOAD as u64 + 1,
            ArtifactStorageError::PayloadMismatch
        ),
        Err(ArtifactStorageError::Capacity),
    );
    Ok(())
}

#[test]
fn empty_snapshot_keeps_corrupt_semantics() -> Result<(), Box<dyn Error>> {
    let (_fixture, file) = Fixture::new()?;
    assert_eq!(
        read_bounded(
            file,
            MAX_SNAPSHOT,
            /*expected_bytes*/ 1,
            ArtifactStorageError::Corrupt
        ),
        Err(ArtifactStorageError::Corrupt),
    );
    Ok(())
}

#[test]
fn pre_read_and_post_read_metadata_use_the_same_error_priority() {
    // Both metadata observations use this helper. This is a deterministic
    // classification test, not a claim of an executed concurrent-write race.
    for (limit, mismatch) in [
        (MAX_SNAPSHOT, ArtifactStorageError::Corrupt),
        (MAX_PAYLOAD, ArtifactStorageError::PayloadMismatch),
    ] {
        assert_eq!(
            validate_read_length(limit as u64 + 1, 1, limit, mismatch),
            Err(ArtifactStorageError::Capacity),
        );
        assert_eq!(validate_read_length(2, 1, limit, mismatch), Err(mismatch));
        assert_eq!(validate_read_length(1, 1, limit, mismatch), Ok(()));
    }
    assert_eq!(
        validate_read_length(0, 1, MAX_PAYLOAD, ArtifactStorageError::PayloadMismatch),
        Err(ArtifactStorageError::Capacity),
    );
    assert_eq!(
        validate_read_length(0, 1, MAX_SNAPSHOT, ArtifactStorageError::Corrupt),
        Err(ArtifactStorageError::Corrupt),
    );
}
