use std::fmt::Debug;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tempfile::tempdir;

use super::DurableNduProjectionError;
use super::DurableNduProjectionStoreV1;
use super::NduProjectionAppendDispositionV1;
use super::NduProjectionRecoveryV1;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn create_file(path: &Path) -> File {
    must(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path),
    )
}

fn open_file(path: &Path) -> File {
    must(OpenOptions::new().read(true).write(true).open(path))
}

#[test]
fn durable_store_recovers_only_from_current_acknowledged_anchor() {
    let directory = must(tempdir());
    let path = directory.path().join("projection.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store = must(DurableNduProjectionStoreV1::create(
        create_file(&path),
        binding,
        16,
    ));
    let projection_receipt = must(store.append_projection(
        None,
        NduProjectionKindV1::Preference,
        digest("projection-op"),
        objective,
        subject,
        projection,
    ));
    let selection_receipt = must(store.select_projection(
        Some(projection_receipt.store_anchor),
        digest("selection-op"),
        objective,
        subject,
        projection,
    ));
    let anchor = selection_receipt.store_anchor;
    drop(store);

    let recovered = must(DurableNduProjectionStoreV1::recover(
        open_file(&path),
        binding,
        16,
        NduProjectionRecoveryV1::Acknowledged(anchor),
    ));
    assert_eq!(
        must(recovered.journal()).selected_projection_digest(objective, subject),
        Some(projection)
    );
    assert_eq!(must(recovered.current_anchor()), Some(anchor));
}

#[test]
fn complete_unwitnessed_tail_fails_closed() {
    let directory = must(tempdir());
    let path = directory.path().join("unwitnessed.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");

    let mut store = must(DurableNduProjectionStoreV1::create(
        create_file(&path),
        binding,
        16,
    ));
    let first = must(store.append_projection(
        None,
        NduProjectionKindV1::Preference,
        digest("op-1"),
        objective,
        subject,
        digest("projection-1"),
    ));
    let _second = must(store.append_projection(
        Some(first.store_anchor),
        NduProjectionKindV1::Preference,
        digest("op-2"),
        objective,
        subject,
        digest("projection-2"),
    ));
    drop(store);

    assert_eq!(
        must_err(DurableNduProjectionStoreV1::recover(
            open_file(&path),
            binding,
            16,
            NduProjectionRecoveryV1::Acknowledged(first.store_anchor),
        )),
        DurableNduProjectionError::UnwitnessedTail
    );
}

#[test]
fn anchored_recovery_repairs_only_an_incomplete_tail() {
    let directory = must(tempdir());
    let path = directory.path().join("incomplete.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");

    let mut store = must(DurableNduProjectionStoreV1::create(
        create_file(&path),
        binding,
        16,
    ));
    let receipt = must(store.append_projection(
        None,
        NduProjectionKindV1::Preference,
        digest("op-1"),
        objective,
        subject,
        digest("projection-1"),
    ));
    let anchor = receipt.store_anchor;
    drop(store);

    {
        let mut file = must(OpenOptions::new().append(true).open(&path));
        must(file.write_all(b"partial-record"));
        must(file.sync_all());
    }

    let mut recovered = must(DurableNduProjectionStoreV1::recover(
        open_file(&path),
        binding,
        16,
        NduProjectionRecoveryV1::Acknowledged(anchor),
    ));
    let backup = must(recovered.backup());
    assert_eq!(backup.store_anchor, Some(anchor));
    assert_eq!(
        backup.encoded_bytes,
        std::fs::metadata(&path)
            .map(|metadata| metadata.len() as usize)
            .unwrap_or(usize::MAX)
    );
}

#[test]
fn backup_restore_is_digest_and_anchor_bound() {
    let directory = must(tempdir());
    let path = directory.path().join("source.store");
    let restored_path = directory.path().join("restored.store");
    let tampered_path = directory.path().join("tampered.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store = must(DurableNduProjectionStoreV1::create(
        create_file(&path),
        binding,
        16,
    ));
    let projection_receipt = must(store.append_projection(
        None,
        NduProjectionKindV1::Utility,
        digest("projection-op"),
        objective,
        subject,
        projection,
    ));
    let _selection = must(store.select_projection(
        Some(projection_receipt.store_anchor),
        digest("selection-op"),
        objective,
        subject,
        projection,
    ));
    let backup = must(store.backup());

    let restored = must(DurableNduProjectionStoreV1::restore_backup(
        create_file(&restored_path),
        16,
        backup.clone(),
    ));
    assert_eq!(
        must(restored.journal()).selected_projection_digest(objective, subject),
        Some(projection)
    );

    let mut tampered = backup;
    let last = tampered.bytes.len().saturating_sub(1);
    tampered.bytes[last] ^= 1;
    assert_eq!(
        must_err(DurableNduProjectionStoreV1::restore_backup(
            create_file(&tampered_path),
            16,
            tampered,
        )),
        DurableNduProjectionError::BackupMismatch
    );
}

#[test]
fn validated_reference_journal_migrates_without_rewriting_history() {
    let directory = must(tempdir());
    let path = directory.path().join("migrated.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-op"),
        objective,
        subject,
        projection,
    ));
    must(journal.select_projection(
        digest("selection-op"),
        objective,
        subject,
        projection,
    ));
    let expected = journal.clone();

    let store = must(DurableNduProjectionStoreV1::migrate_reference(
        create_file(&path),
        binding,
        16,
        journal,
    ));
    assert_eq!(must(store.journal()), &expected);
    assert!(must(store.current_anchor()).is_some());
}

#[test]
fn retention_ceiling_allows_idempotent_replay_but_blocks_new_record() {
    let directory = must(tempdir());
    let path = directory.path().join("bounded.store");
    let binding = digest("store-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store = must(DurableNduProjectionStoreV1::create(
        create_file(&path),
        binding,
        1,
    ));
    let first = must(store.append_projection(
        None,
        NduProjectionKindV1::Preference,
        digest("projection-op"),
        objective,
        subject,
        projection,
    ));
    let replay = must(store.append_projection(
        Some(first.store_anchor),
        NduProjectionKindV1::Preference,
        digest("projection-op"),
        objective,
        subject,
        projection,
    ));
    assert_eq!(
        replay.disposition,
        NduProjectionAppendDispositionV1::IdempotentReplay
    );
    assert_eq!(replay.store_anchor, first.store_anchor);

    assert_eq!(
        must_err(store.revoke_projection(
            Some(first.store_anchor),
            digest("revocation-op"),
            objective,
            subject,
            projection,
        )),
        DurableNduProjectionError::Capacity
    );
}
