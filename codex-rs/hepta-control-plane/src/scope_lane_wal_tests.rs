use std::fmt::Debug;
use std::fs::OpenOptions;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::tempdir;

use super::ScopeLaneFileWalV1;
use super::ScopeLaneWalError;
use super::ScopeLaneWalV1;
use super::ScopeOwnerEnvelopeV1;

fn must<T, E: Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("unexpected result: {error:?}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn generation(value: u64) -> Generation {
    must(Generation::new(value))
}

fn envelope(scope: &str, owner: &str, generation_value: u64, suffix: &str) -> ScopeOwnerEnvelopeV1 {
    must(ScopeOwnerEnvelopeV1::new(
        digest(scope),
        id(owner),
        generation(generation_value),
        digest(&format!("message:{suffix}")),
        digest(&format!("payload:{suffix}")),
    ))
}

#[test]
fn scope_lanes_are_independent_and_fenced() {
    let mut wal = ScopeLaneWalV1::new();
    let first = envelope("scope-a", "owner-a", 1, "first");
    let second_scope = envelope("scope-b", "owner-b", 1, "second-scope");
    let next_generation = envelope("scope-a", "owner-a", 2, "next-generation");
    let first_receipt = must(wal.append(first.clone()));
    let second_receipt = must(wal.append(second_scope));
    let next_receipt = must(wal.append(next_generation));

    assert_eq!(wal.lane_count(), 2);
    assert_eq!(wal.record_count(), 3);
    assert_eq!(first_receipt.sequence, 1);
    assert_eq!(second_receipt.sequence, 1);
    assert_eq!(next_receipt.sequence, 2);
    assert_eq!(first_receipt.authority.flags().wire_mask(), 0);
    assert_eq!(wal.append(first).expect("idempotent append"), first_receipt);

    let owner_conflict = envelope("scope-a", "owner-b", 3, "owner-conflict");
    assert_eq!(
        wal.append(owner_conflict),
        Err(ScopeLaneWalError::OwnerConflict)
    );
    let generation_regression = envelope("scope-a", "owner-a", 1, "regression");
    assert_eq!(
        wal.append(generation_regression),
        Err(ScopeLaneWalError::GenerationRegression)
    );
}

#[test]
fn export_reopen_roundtrip_and_bad_frame_rejection() {
    let mut wal = ScopeLaneWalV1::new();
    must(wal.append(envelope("scope-a", "owner-a", 1, "first")));
    must(wal.append(envelope("scope-a", "owner-a", 1, "second")));
    must(wal.append(envelope("scope-b", "owner-b", 1, "other")));
    let bytes = wal.export_bytes();
    let reopened = must(ScopeLaneWalV1::reopen(&bytes));
    assert_eq!(reopened, wal);

    let mut corrupted = bytes;
    let body_offset = 16 + 4;
    corrupted[body_offset] ^= 0x01;
    assert_eq!(
        ScopeLaneWalV1::reopen(&corrupted),
        Err(ScopeLaneWalError::CorruptFrame)
    );

    let mut bad_chain = wal.export_bytes();
    let first_body_start = 16 + 4;
    let first_body_len =
        u32::from_be_bytes(bad_chain[16..20].try_into().expect("frame length bytes")) as usize;
    let first_entry_digest = first_body_start + first_body_len - 32;
    bad_chain[first_entry_digest] ^= 0x01;
    let first_checksum = first_body_start + first_body_len;
    let checksum =
        Digest32::of_bytes(&bad_chain[first_body_start..first_body_start + first_body_len]);
    bad_chain[first_checksum..first_checksum + 32].copy_from_slice(checksum.as_array());
    assert_eq!(
        ScopeLaneWalV1::reopen(&bad_chain),
        Err(ScopeLaneWalError::CorruptEntryDigest)
    );
}

#[test]
fn file_wal_syncs_frames_and_repairs_torn_tail() {
    let directory = must(tempdir());
    let path = directory.path().join("scope-lanes.wal");
    {
        let mut wal = must(ScopeLaneFileWalV1::open(&path));
        must(wal.append(envelope("scope-a", "owner-a", 1, "first")));
        must(wal.append(envelope("scope-a", "owner-a", 1, "second")));
        let size_before_duplicate = must(std::fs::metadata(&path)).len();
        must(wal.append(envelope("scope-a", "owner-a", 1, "second")));
        assert_eq!(must(std::fs::metadata(&path)).len(), size_before_duplicate);
    }

    let complete_len = must(std::fs::metadata(&path)).len();
    {
        let mut append = must(OpenOptions::new().append(true).open(&path));
        append
            .write_all(&[0, 0, 0, 64, 0xaa, 0xbb])
            .expect("torn tail");
        append.flush().expect("flush torn tail");
    }
    {
        let wal = must(ScopeLaneFileWalV1::open(&path));
        assert_eq!(wal.wal().record_count(), 2);
    }
    assert_eq!(must(std::fs::metadata(&path)).len(), complete_len);
}

#[test]
fn file_wal_repairs_incomplete_length_before_new_commits() {
    let directory = must(tempdir());
    let path = directory.path().join("partial-length-scope-lanes.wal");
    {
        let mut writer = must(ScopeLaneFileWalV1::open(&path));
        must(writer.append(envelope("scope-a", "owner-a", 1, "first")));
    }
    let committed_len = must(std::fs::metadata(&path)).len();
    {
        let mut interrupted = must(OpenOptions::new().append(true).open(&path));
        must(interrupted.write_all(&[0, 0, 0]));
        must(interrupted.sync_all());
    }

    // Reopening must truncate an incomplete frame-length prefix on Windows
    // as well as Unix, and it must not acknowledge the uncommitted tail.
    let mut recovered = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(must(std::fs::metadata(&path)).len(), committed_len);
    assert_eq!(recovered.wal().record_count(), 1);
    must(recovered.append(envelope("scope-a", "owner-a", 1, "second")));
    drop(recovered);
    let reopened = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(reopened.wal().record_count(), 2);
}

#[cfg(windows)]
#[test]
fn file_wal_windows_recovery_truncates_partial_body_before_next_commit() {
    let directory = must(tempdir());
    let path = directory.path().join("windows-torn-scope-lanes.wal");
    {
        let mut writer = must(ScopeLaneFileWalV1::open(&path));
        let receipt = must(writer.append(envelope("scope-a", "owner-a", 1, "first")));
        assert_eq!(receipt.sequence, 1);
    }
    let committed_len = must(std::fs::metadata(&path)).len();
    {
        let mut interrupted = must(OpenOptions::new().append(true).open(&path));
        // A complete length prefix but incomplete body must never be replayed.
        must(interrupted.write_all(&[0, 0, 0, 64, 0xaa]));
        must(interrupted.sync_all());
    }

    let mut recovered = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(must(std::fs::metadata(&path)).len(), committed_len);
    assert_eq!(recovered.wal().record_count(), 1);
    let receipt = must(recovered.append(envelope("scope-a", "owner-a", 1, "second")));
    assert_eq!(receipt.sequence, 2);
    drop(recovered);

    let reopened = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(reopened.wal().record_count(), 2);
}

#[test]
fn incremental_scope_lanes_replay_many_distinct_committed_frames() {
    let directory = must(tempdir());
    let path = directory.path().join("incremental-scope-lanes.wal");
    {
        let mut writer = must(ScopeLaneFileWalV1::open(&path));
        for index in 0..64 {
            let scope = if index % 2 == 0 { "scope-a" } else { "scope-b" };
            let owner = if index % 2 == 0 { "owner-a" } else { "owner-b" };
            let candidate = envelope(scope, owner, 1, &format!("entry-{index}"));
            let receipt = must(writer.append(candidate.clone()));
            assert_eq!(receipt.sequence, index / 2 + 1);
            assert_eq!(must(writer.append(candidate)), receipt);
        }
        assert_eq!(writer.wal().lane_count(), 2);
        assert_eq!(writer.wal().record_count(), 64);
    }
    let reopened = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(reopened.wal().lane_count(), 2);
    assert_eq!(reopened.wal().record_count(), 64);
}

#[test]
fn poisoned_scope_writer_cannot_acknowledge_even_an_old_duplicate() {
    let directory = must(tempdir());
    let path = directory.path().join("poisoned-scope-lanes.wal");
    let first = envelope("scope-a", "owner-a", 1, "first");
    let mut writer = must(ScopeLaneFileWalV1::open(&path));
    must(writer.append(first.clone()));
    let durable_len = must(std::fs::metadata(&path)).len();

    // Model an incomplete write/fsync: the live handle must be permanently
    // fenced until the locked file is reopened and validated.
    writer.poisoned = true;
    assert_eq!(
        writer.append(envelope("scope-a", "owner-a", 1, "second")),
        Err(ScopeLaneWalError::Poisoned)
    );
    assert_eq!(
        writer.append(first.clone()),
        Err(ScopeLaneWalError::Poisoned)
    );
    assert_eq!(must(std::fs::metadata(&path)).len(), durable_len);
    drop(writer);

    let mut recovered = must(ScopeLaneFileWalV1::open(&path));
    assert_eq!(recovered.wal().record_count(), 1);
    must(recovered.append(envelope("scope-a", "owner-a", 1, "second")));
    assert_eq!(recovered.wal().record_count(), 2);
}
