use super::super::tests::Fixture;
use super::super::tests::binding;
use super::super::tests::conflict_record;
use super::super::tests::digest;
use super::super::tests::id;
use super::super::tests::must;
use super::super::tests::record;
use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;

#[path = "run_start_read_only_frame_tests.rs"]
mod frame;

fn anchor(receipt: &RunStartAppendReceipt) -> RunStartAnchor {
    RunStartAnchor {
        sequence: receipt.sequence,
        chain_digest: receipt.chain_digest,
    }
}

fn view(fixture: &Fixture, anchor: RunStartAnchor) -> ReadOnlyRunStartViewV1 {
    must(ReadOnlyRunStartViewV1::open(
        must(File::open(fixture.path())),
        binding(),
        digest("profile"),
        /*max_records*/ 16,
        anchor,
    ))
}

fn replace_bytes(fixture: &Fixture, bytes: &[u8]) {
    let mut file = fixture.file();
    must(file.seek(SeekFrom::Start(0)));
    must(file.write_all(bytes));
    must(file.set_len(bytes.len() as u64));
    must(file.sync_all());
}

#[test]
fn run_start_read_only_coexists_with_actual_writer_and_hides_complete_tail() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let first = record("original", b"objective-one");
    let receipt = must(writer.append(Digest32::ZERO, first.clone()));
    let bytes = must(fs::read(fixture.path()));
    let descriptor = must(File::open(fixture.path()));
    assert!(matches!(
        descriptor.try_lock_shared(),
        Err(TryLockError::WouldBlock)
    ));
    let reader = must(ReadOnlyRunStartViewV1::open(
        descriptor,
        binding(),
        digest("profile"),
        /*max_records*/ 16,
        anchor(&receipt),
    ));
    let expected = RunStartReadOnlyPublicationV1 {
        record: first,
        publication: RunStartPublication {
            sequence: receipt.sequence,
            record_digest: receipt.record_digest,
            chain_digest: receipt.chain_digest,
        },
    };
    assert_eq!(must(reader.read(&id("original"))), Some(expected.clone()));
    assert_eq!(must(fs::read(fixture.path())), bytes);
    must(writer.append(receipt.chain_digest, record("later", b"objective-two")));
    assert_eq!(must(reader.read(&id("later"))), None);
    assert_eq!(must(reader.read(&id("absent"))), None);
    assert_eq!(must(reader.read(&id("original"))), Some(expected));
    assert_eq!(must(writer.records()).len(), 2);
}

#[test]
fn run_start_read_only_requires_existing_read_only_regular_descriptor() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let bytes = must(fs::read(fixture.path()));
    for descriptor in [
        fixture.file(),
        must(OpenOptions::new().write(true).open(fixture.path())),
    ] {
        assert_eq!(
            ReadOnlyRunStartViewV1::open(
                descriptor,
                binding(),
                digest("profile"),
                /*max_records*/ 16,
                anchor(&receipt),
            )
            .err(),
            Some(RunStartStoreError::InvalidSnapshot(
                "existing O_RDONLY descriptor required"
            )),
        );
    }
    let mut directory = fixture.path();
    assert!(directory.pop());
    assert_eq!(
        ReadOnlyRunStartViewV1::open(
            must(File::open(directory)),
            binding(),
            digest("profile"),
            /*max_records*/ 16,
            anchor(&receipt),
        )
        .err(),
        Some(RunStartStoreError::NotRegular),
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn run_start_read_only_binds_header_profile_explicit_anchor_and_record_bound() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("first", b"one")));
    let open = |binding, profile, max_records, anchor| {
        ReadOnlyRunStartViewV1::open(
            must(File::open(fixture.path())),
            binding,
            profile,
            max_records,
            anchor,
        )
        .err()
    };
    assert_eq!(
        open(
            digest("wrong-owner"),
            digest("profile"),
            /*max_records*/ 16,
            anchor(&receipt)
        ),
        Some(RunStartStoreError::BindingMismatch)
    );
    assert_eq!(
        open(
            binding(),
            digest("wrong-profile"),
            /*max_records*/ 16,
            anchor(&receipt)
        ),
        Some(RunStartStoreError::BindingMismatch)
    );
    assert_eq!(
        open(
            binding(),
            Digest32::ZERO,
            /*max_records*/ 16,
            anchor(&receipt)
        ),
        Some(RunStartStoreError::InvalidBinding)
    );
    assert_eq!(
        open(
            binding(),
            digest("profile"),
            /*max_records*/ 0,
            anchor(&receipt)
        ),
        Some(RunStartStoreError::InvalidLimit)
    );
    let wrong = RunStartAnchor {
        sequence: 1,
        chain_digest: digest("wrong-chain"),
    };
    assert_eq!(
        open(binding(), digest("profile"), /*max_records*/ 16, wrong),
        Some(RunStartStoreError::AnchorMismatch)
    );
    let absent = RunStartAnchor {
        sequence: 2,
        chain_digest: receipt.chain_digest,
    };
    assert_eq!(
        open(
            binding(),
            digest("profile"),
            /*max_records*/ 16,
            absent
        ),
        Some(RunStartStoreError::AcknowledgedHistoryMissing)
    );
    must(writer.append(receipt.chain_digest, record("second", b"two")));
    assert_eq!(
        open(
            binding(),
            digest("profile"),
            /*max_records*/ 1,
            anchor(&receipt)
        ),
        Some(RunStartStoreError::Capacity)
    );
}

#[test]
fn run_start_read_only_physical_corruption_then_restore_remains_poisoned() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let original = must(fs::read(fixture.path()));
    let mut corrupt = original.clone();
    corrupt[HEADER + 48] ^= 0x40;
    replace_bytes(&fixture, &corrupt);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(must(fs::read(fixture.path())), corrupt);
    replace_bytes(&fixture, &original);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
    // A fresh handle is not a persistent refusal witness or independent ACK.
    assert!(must(view(&fixture, anchor(&receipt)).read(&id("original"))).is_some());
}

#[test]
fn run_start_read_only_partial_tail_is_never_repaired_or_accepted_after_restore() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let original = must(fs::read(fixture.path()));
    let mut partial = original.clone();
    partial.extend_from_slice(&[0, 1, 2]);
    replace_bytes(&fixture, &partial);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Indeterminate)
    );
    assert_eq!(
        ReadOnlyRunStartViewV1::open(
            must(File::open(fixture.path())),
            binding(),
            digest("profile"),
            /*max_records*/ 16,
            anchor(&receipt),
        )
        .err(),
        Some(RunStartStoreError::Indeterminate)
    );
    assert_eq!(must(fs::read(fixture.path())), partial);
    replace_bytes(&fixture, &original);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn run_start_read_only_observed_complete_tail_cannot_roll_back() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let original = must(fs::read(fixture.path()));
    let reader = view(&fixture, anchor(&receipt));
    must(writer.append(receipt.chain_digest, record("tail", b"tail")));
    assert!(must(reader.read(&id("original"))).is_some());
    let complete = must(fs::read(fixture.path()));
    replace_bytes(&fixture, &original);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Indeterminate)
    );
    replace_bytes(&fixture, &complete);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn run_start_read_only_seen_valid_tail_rewrite_cannot_reopen_same_handle() {
    let fixture = Fixture::new();
    let other = Fixture::new();
    let mut writer = fixture.create();
    let mut other_writer = other.create();
    let first = record("original", b"objective");
    let receipt = must(writer.append(Digest32::ZERO, first.clone()));
    assert_eq!(must(other_writer.append(Digest32::ZERO, first)), receipt);
    must(writer.append(receipt.chain_digest, record("tail", b"left")));
    must(other_writer.append(receipt.chain_digest, record("tail", b"rght")));
    let reader = view(&fixture, anchor(&receipt));
    let original = must(fs::read(fixture.path()));
    let replacement = must(fs::read(other.path()));
    assert_eq!(original.len(), replacement.len());
    assert_ne!(original, replacement);
    replace_bytes(&fixture, &replacement);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Indeterminate)
    );
    replace_bytes(&fixture, &original);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn run_start_read_only_second_physical_read_rejects_real_concurrent_append() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let result = reader.with_observation(|_, _| {
        writer.append(receipt.chain_digest, record("concurrent", b"new-record"))?;
        Ok(())
    });
    assert_eq!(result, Err(RunStartStoreError::Indeterminate));
    assert_eq!(must(writer.records()).len(), 2);
    assert_eq!(
        reader.read(&id("original")),
        Err(RunStartStoreError::Poisoned)
    );
}

#[test]
fn run_start_read_only_validates_conflicts_without_returning_them_as_run_starts() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let first = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let conflict =
        must(writer.append_conflict(first.chain_digest, conflict_record("conflict", b"receipt")));
    let reader = view(&fixture, anchor(&conflict));
    assert_eq!(must(reader.read(&id("conflict"))), None);
    assert!(must(reader.read(&id("original"))).is_some());
    let bytes = must(fs::read(fixture.path()));
    let mut corrupt = bytes.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    replace_bytes(&fixture, &corrupt);
    assert_eq!(
        ReadOnlyRunStartViewV1::open(
            must(File::open(fixture.path())),
            binding(),
            digest("profile"),
            /*max_records*/ 16,
            anchor(&first),
        )
        .err(),
        Some(RunStartStoreError::Corrupt)
    );
    assert_eq!(must(fs::read(fixture.path())), corrupt);
}

#[test]
fn run_start_read_only_descriptor_does_not_claim_path_replacement_detection() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let receipt = must(writer.append(Digest32::ZERO, record("original", b"objective")));
    let reader = view(&fixture, anchor(&receipt));
    let expected = must(reader.read(&id("original")));
    let retained = fixture.path().with_file_name("original-inode");
    must(fs::rename(fixture.path(), &retained));
    must(fs::write(fixture.path(), b"different-path-object"));
    assert_eq!(must(reader.read(&id("original"))), expected);
    assert_eq!(must(fs::read(fixture.path())), b"different-path-object");
    assert_eq!(
        must(must(File::open(retained)).metadata()).ino(),
        must(reader.file.metadata()).ino()
    );
}
