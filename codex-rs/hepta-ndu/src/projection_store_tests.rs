#![cfg(unix)]

use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use super::CURRENT_FILE;
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::decode_pointer;
use super::read_bounded;
use crate::NduProjectionKindV1;

static TEST_NONCE: AtomicU64 = AtomicU64::new(1);

struct TestRoot(PathBuf);

impl TestRoot {
    fn new(label: &str) -> Self {
        let nonce = TEST_NONCE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "codex-hepta-ndu-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("create private test root");
        Self(root)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TestRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn durable_store_round_trips_and_fences_a_second_writer() {
    let root = TestRoot::new("round-trip");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store = NduProjectionStoreV1::open(root.path()).expect("open writer");
    assert_eq!(
        NduProjectionStoreV1::open(root.path()).expect_err("second writer must be fenced"),
        NduProjectionStoreError::Busy
    );
    store
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-identity"),
            objective,
            subject,
            projection,
        )
        .expect("append projection");
    store
        .select_projection(digest("selection-identity"), objective, subject, projection)
        .expect("select projection");
    let committed = store.current_snapshot_digest();
    assert!(!committed.is_zero());
    drop(store);

    let reopened = NduProjectionStoreV1::open(root.path()).expect("reopen durable store");
    assert_eq!(reopened.current_snapshot_digest(), committed);
    assert_eq!(
        reopened
            .journal()
            .selected_projection_digest(objective, subject),
        Some(projection)
    );
}

#[test]
fn backup_restores_only_into_an_empty_store() {
    let source = TestRoot::new("backup-source");
    let target = TestRoot::new("backup-target");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut source_store = NduProjectionStoreV1::open(source.path()).expect("open source");
    source_store
        .append_projection(
            NduProjectionKindV1::Utility,
            digest("projection-identity"),
            objective,
            subject,
            projection,
        )
        .expect("append projection");
    source_store
        .select_projection(digest("selection-identity"), objective, subject, projection)
        .expect("select projection");
    let backup = source_store.export_backup();
    drop(source_store);

    let restored = NduProjectionStoreV1::restore_into_empty(target.path(), &backup)
        .expect("restore backup");
    assert_eq!(
        restored
            .journal()
            .selected_projection_digest(objective, subject),
        Some(projection)
    );
    drop(restored);

    assert_eq!(
        NduProjectionStoreV1::restore_into_empty(target.path(), &backup)
            .expect_err("restore may not overwrite an existing store"),
        NduProjectionStoreError::NotEmpty
    );
}

#[test]
fn current_pointer_ignores_orphan_snapshot_from_interrupted_publication() {
    let root = TestRoot::new("orphan");
    let mut store = NduProjectionStoreV1::open(root.path()).expect("open writer");
    store
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("identity"),
            digest("objective"),
            digest("subject"),
            digest("projection"),
        )
        .expect("commit current snapshot");
    let current = store.current_snapshot_digest();
    drop(store);

    fs::write(
        root.path().join(format!(
            "journal-{:016}-{}.bin",
            4096,
            digest("orphan-name")
        )),
        b"orphan incomplete bytes",
    )
    .expect("write orphan fixture");

    let reopened = NduProjectionStoreV1::open(root.path()).expect("reopen via CURRENT only");
    assert_eq!(reopened.current_snapshot_digest(), current);
    assert_eq!(reopened.journal().entries().len(), 1);
}

#[test]
fn tampered_current_snapshot_fails_closed() {
    let root = TestRoot::new("tamper");
    let mut store = NduProjectionStoreV1::open(root.path()).expect("open writer");
    store
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("identity"),
            digest("objective"),
            digest("subject"),
            digest("projection"),
        )
        .expect("commit snapshot");
    drop(store);

    let pointer = read_bounded(&root.path().join(CURRENT_FILE), 512).expect("read pointer");
    let (_, _, filename) = decode_pointer(&pointer).expect("decode pointer");
    let snapshot = root.path().join(filename);
    let mut bytes = fs::read(&snapshot).expect("read snapshot");
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    fs::write(snapshot, bytes).expect("tamper current snapshot");

    assert_eq!(
        NduProjectionStoreV1::open(root.path()).expect_err("tampered snapshot must reject"),
        NduProjectionStoreError::CorruptSnapshot
    );
}

#[test]
fn snapshot_retention_is_bounded_after_current_pointer_is_durable() {
    let root = TestRoot::new("retention");
    let mut store = NduProjectionStoreV1::open(root.path()).expect("open writer");
    for index in 0..6 {
        store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest(&format!("identity-{index}")),
                digest("objective"),
                digest("subject"),
                digest(&format!("projection-{index}")),
            )
            .expect("append retained snapshot");
    }
    let count = fs::read_dir(root.path())
        .expect("read root")
        .filter_map(Result::ok)
        .filter(|entry| {
            entry
                .file_name()
                .to_str()
                .is_some_and(|name| name.starts_with("journal-") && name.ends_with(".bin"))
        })
        .count();
    assert!(count <= 2, "retained snapshot count: {count}");
}