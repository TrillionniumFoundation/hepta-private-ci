use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

#[path = "product_execution_readback_tests.rs"]
mod readback;

#[path = "product_execution_physical_tests.rs"]
mod physical;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn key(name: &str) -> ProductEvaluationExecutionKeyV1 {
    ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new(name).expect("fixture plan id"),
        binding_digest: digest(name),
    }
}

struct TempJournal(PathBuf);

impl TempJournal {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!(
            "hepta-product-execution-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        )))
    }

    fn create(&self) -> LockedFileProductEvaluationExecutionStoreV1 {
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.0)
            .expect("create fixture file");
        LockedFileProductEvaluationExecutionStoreV1::create(file, digest("owner namespace"))
            .expect("create execution journal")
    }

    fn open(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .expect("reopen fixture file")
    }

    fn recover(
        &self,
        minimum: ProductEvaluationExecutionAnchorV1,
    ) -> Result<LockedFileProductEvaluationExecutionStoreV1, FileError> {
        LockedFileProductEvaluationExecutionStoreV1::recover(
            self.open(),
            digest("owner namespace"),
            minimum,
        )
    }
}

impl Drop for TempJournal {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[test]
fn completed_bytes_and_pending_claim_survive_an_abrupt_child_exit() {
    const TEST: &str = "product_execution_file::tests::completed_bytes_and_pending_claim_survive_an_abrupt_child_exit";
    if let Ok(path) = std::env::var("HEPTA_PRODUCT_EXECUTION_CHILD_PATH") {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("child authorized file");
        let minimum = ProductEvaluationExecutionAnchorV1 {
            sequence: 0,
            history_digest: std::env::var("HEPTA_PRODUCT_EXECUTION_CHILD_ANCHOR")
                .expect("external anchor")
                .parse()
                .expect("anchor digest"),
        };
        let result = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            digest("owner namespace"),
            minimum,
        );
        if std::env::var("HEPTA_PRODUCT_EXECUTION_CHILD_MODE").as_deref() == Ok("busy") {
            assert_eq!(result.err(), Some(FileError::Busy));
            return;
        }
        let mut store = result.expect("child exclusive owner");
        if std::env::var("HEPTA_PRODUCT_EXECUTION_CHILD_MODE").as_deref() == Ok("readback") {
            assert_eq!(
                store.readback(&key("completed")),
                Ok(State::Completed(b"opaque owner evidence".to_vec()))
            );
            let before = store.anchor();
            assert_eq!(
                store.claim(&key("uncertain")),
                Ok(ProductEvaluationExecutionClaimV1::Existing(State::Pending))
            );
            assert_eq!(store.anchor(), before);
            return;
        }
        assert_eq!(
            store.claim(&key("completed")),
            Ok(ProductEvaluationExecutionClaimV1::Claimed)
        );
        store
            .complete(&key("completed"), b"opaque owner evidence")
            .expect("fsync completed bytes");
        assert_eq!(
            store.claim(&key("uncertain")),
            Ok(ProductEvaluationExecutionClaimV1::Claimed)
        );
        // Deliberately omit Rust destructors: persistence cannot depend on Drop.
        std::process::exit(0);
    }

    let temp = TempJournal::new();
    let store = temp.create();
    let minimum = store.anchor();
    let executable = std::env::current_exe().expect("current test executable");
    let run = |mode: &str| {
        Command::new(&executable)
            .args(["--exact", TEST])
            .env("HEPTA_PRODUCT_EXECUTION_CHILD_PATH", &temp.0)
            .env(
                "HEPTA_PRODUCT_EXECUTION_CHILD_ANCHOR",
                minimum.history_digest.to_string(),
            )
            .env("HEPTA_PRODUCT_EXECUTION_CHILD_MODE", mode)
            .status()
            .expect("spawn fresh journal process")
    };
    assert!(run("busy").success());
    drop(store);
    assert!(run("write-and-exit").success());
    assert!(run("readback").success());
    let mut recovered = temp.recover(minimum).expect("recover after child exit");
    assert_eq!(
        recovered.readback(&key("completed")),
        Ok(State::Completed(b"opaque owner evidence".to_vec()))
    );
    let before = recovered.anchor();
    assert_eq!(
        recovered.claim(&key("uncertain")),
        Ok(ProductEvaluationExecutionClaimV1::Existing(State::Pending))
    );
    assert_eq!(recovered.anchor(), before);
}

#[test]
fn plan_binding_and_completed_payload_are_immutable() {
    let temp = TempJournal::new();
    let mut store = temp.create();
    let original = key("plan");
    store.claim(&original).expect("claim operation");
    let pending = store.anchor();
    let mut conflicting = original.clone();
    conflicting.binding_digest = digest("different candidate");
    assert_eq!(store.claim(&conflicting), Err(StoreError::Conflict));
    assert_eq!(store.readback(&conflicting), Err(StoreError::Conflict));
    assert_eq!(store.anchor(), pending);
    store.complete(&original, b"original").expect("completion");
    let completed = store.anchor();
    store.complete(&original, b"original").expect("idempotence");
    assert_eq!(
        store.complete(&original, b"replacement"),
        Err(StoreError::Conflict)
    );
    assert_eq!(store.anchor(), completed);
    assert_eq!(
        store.claim(&original),
        Ok(ProductEvaluationExecutionClaimV1::Existing(
            State::Completed(b"original".to_vec())
        ))
    );
}

#[test]
fn external_minimum_rejects_an_older_or_divergent_valid_journal() {
    let temp = TempJournal::new();
    let mut store = temp.create();
    store.claim(&key("plan")).expect("claim");
    let pending = store.anchor();
    // Read the pending prefix through its original locked owner. Opening a
    // second handle for fs::read fails under Windows' exclusive file lock.
    let original_cursor = store.file.stream_position().expect("original cursor");
    store
        .file
        .seek(SeekFrom::Start(0))
        .expect("seek locked journal");
    let mut backup = Vec::new();
    store
        .file
        .read_to_end(&mut backup)
        .expect("backup pending journal through its owner");
    assert_eq!(backup.len() as u64, store.length);
    store
        .file
        .seek(SeekFrom::Start(original_cursor))
        .expect("restore original cursor");
    store
        .complete(&key("plan"), b"original")
        .expect("completion");
    let minimum = store.anchor();
    drop(store);
    fs::write(&temp.0, &backup).expect("restore older bytes");
    assert_eq!(temp.recover(minimum).err(), Some(FileError::Rollback));
    let mut divergent = temp.recover(pending).expect("original pending prefix");
    divergent
        .complete(&key("plan"), b"alternate")
        .expect("divergent completion");
    drop(divergent);
    assert_eq!(temp.recover(minimum).err(), Some(FileError::Rollback));
}

#[test]
fn a_torn_suffix_is_preserved_and_blocks_recovery() {
    let temp = TempJournal::new();
    let mut store = temp.create();
    store.claim(&key("plan")).expect("durable pending");
    let minimum = store.anchor();
    drop(store);
    let mut file = OpenOptions::new()
        .append(true)
        .open(&temp.0)
        .expect("fixture append");
    file.write_all(&[0, 0]).expect("partial frame length");
    file.sync_all().expect("persist partial frame");
    drop(file);
    let before = fs::read(&temp.0).expect("torn original");
    assert_eq!(temp.recover(minimum).err(), Some(FileError::Corrupt));
    assert_eq!(fs::read(&temp.0).expect("preserved original"), before);
}

#[test]
fn external_length_change_poisoning_cannot_be_cleared_by_restoring_length() {
    let temp = TempJournal::new();
    let mut store = temp.create();
    store.claim(&key("plan")).expect("claim");
    let length = fs::metadata(&temp.0).expect("metadata").len();
    let file = temp.open();
    file.set_len(length + 1).expect("uncertain external write");
    assert_eq!(store.readback(&key("plan")), Err(StoreError::Indeterminate));
    file.set_len(length).expect("restore length");
    assert_eq!(store.claim(&key("plan")), Err(StoreError::Indeterminate));
    assert_eq!(
        store.complete(&key("plan"), b"bytes"),
        Err(StoreError::Indeterminate)
    );
}

#[test]
fn oversized_completion_keeps_the_durable_pending_record() {
    let temp = TempJournal::new();
    let mut store = temp.create();
    store.claim(&key("plan")).expect("claim");
    let minimum = store.anchor();
    assert_eq!(
        store.complete(
            &key("plan"),
            &vec![1; MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 + 1]
        ),
        Err(StoreError::Rejected)
    );
    assert_eq!(store.anchor(), minimum);
    drop(store);
    assert_eq!(
        temp.recover(minimum)
            .expect("recover pending")
            .readback(&key("plan")),
        Ok(State::Pending)
    );
}

#[test]
fn failed_constructor_releases_lock_even_with_a_duplicate_description() {
    let temp = TempJournal::new();
    let store = temp.create();
    let minimum = store.anchor();
    drop(store);
    let file = temp.open();
    let duplicate = file.try_clone().expect("retain open description");
    assert_eq!(
        LockedFileProductEvaluationExecutionStoreV1::create(file, digest("owner namespace")).err(),
        Some(FileError::AlreadyInitialized)
    );
    let recovered = temp.recover(minimum).expect("constructor released lock");
    drop(duplicate);
    assert_eq!(temp.recover(minimum).err(), Some(FileError::Busy));
    drop(recovered);
}
