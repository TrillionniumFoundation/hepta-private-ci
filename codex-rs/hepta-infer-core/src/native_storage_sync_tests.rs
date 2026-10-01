use super::*;

struct StorageFixture {
    directory: PathBuf,
}

impl StorageFixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory =
            std::env::temp_dir().join(format!("hepta-storage-sync-{}-{nonce}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        Self { directory }
    }
}

impl Drop for StorageFixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[test]
fn identical_content_addressed_reuse_preserves_the_existing_object() {
    let fixture = StorageFixture::new();
    let path = fixture.directory.join("object");
    let bytes = b"committed predecessor segment";
    write_content_addressed(&path, bytes).unwrap();
    for _ in 0..3 {
        write_content_addressed(&path, bytes).unwrap();
    }
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(
        write_content_addressed(&path, b"different segment"),
        Err(Error::CorruptJournal("content-address collision"))
    );
    assert_eq!(fs::read(&path).unwrap(), bytes);
}

#[cfg(target_os = "linux")]
#[test]
fn identical_reuse_requires_a_successful_real_file_flush() {
    // A real kernel file supplies readable stable bytes but does not support
    // writable-file durability. The earlier compare-only path returned Ok.
    let path = Path::new("/proc/version");
    let bytes = fs::read(path).unwrap();
    assert!(matches!(
        write_content_addressed(path, &bytes),
        Err(Error::Io(_))
    ));
    assert_eq!(fs::read(path).unwrap(), bytes);
}

#[test]
fn maintenance_retry_reuses_the_synced_archive_and_commits_one_generation() {
    let fixture = StorageFixture::new();
    let path = fixture.directory.join("owner.journal");
    let mut owner = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    owner
        .reserve_native(
            NativeRequest {
                request_id: "request-1".to_string(),
                principal_id: "principal-1".to_string(),
                worker_generation: 4,
                model: "model-1".to_string(),
                payload_digest: "a".repeat(64),
            },
            /*maximum_in_flight*/ 1,
        )
        .unwrap();
    let released = owner
        .stop_native_before_dispatch("request-1", "not dispatched".to_string())
        .unwrap();
    let original = fs::read(&path).unwrap();
    let digest = sha256_hex(b"hepta.inference-control.archive-segment.v1\0", &original);
    let archive = sibling_directory(&owner.path, "archive").join(format!("{digest}.journal"));
    let mut failpoint = |stage| {
        if stage == NativeMaintenanceStage::AfterArchiveSync {
            Err(Error::Io(
                "interrupted before checkpoint publication".to_string(),
            ))
        } else {
            Ok(())
        }
    };
    assert!(matches!(
        owner.compact_native_journal_with_failpoint(/*now_unix_ms*/ 1, &mut failpoint),
        Err(Error::Io(_))
    ));
    assert_eq!(fs::read(&archive).unwrap(), original);
    drop(owner);
    let mut owner = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let receipt = owner.compact_native_journal().unwrap();
    assert_eq!(receipt.generation, 1);
    assert_eq!(receipt.archive_segment_digest, digest);
    assert_eq!(fs::read(&archive).unwrap(), original);
    drop(owner);
    let reopened = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&released));
}
