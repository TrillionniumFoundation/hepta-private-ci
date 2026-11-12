//! Actual files and owner appends; the prefix is data, never an ACK.

use super::*;

fn prefix(fixture: &Fixture) -> Result<OriginalRunStartPrefixV1, RunStartStoreError> {
    observe_original_run_start_prefix_v1(
        &must(File::open(fixture.path())),
        binding(),
        /*max_records*/ 16,
    )
}

#[test]
fn run_start_prefix_observes_empty_header_and_complete_multi_profile_history() {
    let fixture = Fixture::new();
    assert_eq!(
        must(prefix(&fixture)),
        OriginalRunStartPrefixV1 {
            length: 0,
            digest: Digest32::of_bytes(&[]),
        }
    );
    let mut writer = fixture.create();
    let header = must(fs::read(fixture.path()));
    assert_eq!(must(prefix(&fixture)).length, HEADER as u64);
    let first = must(writer.append(Digest32::ZERO, record("one", b"one")));
    let mut different = record("two", b"two");
    different.admission.profile_digest = digest("second-profile");
    must(writer.append(first.chain_digest, different));
    let bytes = must(fs::read(fixture.path()));
    assert_ne!(bytes, header);
    let descriptor = must(File::open(fixture.path()));
    assert!(matches!(
        descriptor.try_lock_shared(),
        Err(TryLockError::WouldBlock)
    ));
    assert_eq!(
        must(observe_original_run_start_prefix_v1(
            &descriptor,
            binding(),
            /*max_records*/ 16,
        )),
        OriginalRunStartPrefixV1 {
            length: bytes.len() as u64,
            digest: Digest32::of_bytes(&bytes),
        }
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
    assert_eq!(must(writer.records()).len(), 2);
}

#[test]
fn run_start_prefix_rejects_partial_header_and_partial_original_frame_without_repair() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let first = must(writer.append(Digest32::ZERO, record("one", b"one")));
    let complete_length = must(fs::metadata(fixture.path())).len() as usize;
    must(writer.append(first.chain_digest, record("two", b"two")));
    let complete = must(fs::read(fixture.path()));
    for length in [1, HEADER - 1, complete_length + 1, complete.len() - 1] {
        let partial = &complete[..length];
        replace_bytes(&fixture, partial);
        assert!(prefix(&fixture).is_err());
        assert_eq!(must(fs::read(fixture.path())), partial);
    }
    replace_bytes(&fixture, &complete);
    assert_eq!(must(prefix(&fixture)).length, complete.len() as u64);
}

#[test]
fn run_start_prefix_requires_original_readonly_binding_and_bounded_complete_history() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    must(writer.append(Digest32::ZERO, record("one", b"one")));
    let before = must(fs::read(fixture.path()));
    assert!(
        observe_original_run_start_prefix_v1(&fixture.file(), binding(), /*max_records*/ 16)
            .is_err()
    );
    let readonly = must(File::open(fixture.path()));
    assert_eq!(
        observe_original_run_start_prefix_v1(&readonly, digest("other-owner"), 16),
        Err(RunStartStoreError::BindingMismatch)
    );
    assert_eq!(
        observe_original_run_start_prefix_v1(&readonly, binding(), 0),
        Err(RunStartStoreError::InvalidLimit)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
    must(fixture.file().set_len(MAX_FILE_BYTES + 1));
    assert_eq!(prefix(&fixture), Err(RunStartStoreError::Capacity));
    assert_eq!(must(fs::metadata(fixture.path())).len(), MAX_FILE_BYTES + 1);
}

#[test]
fn run_start_prefix_and_new_frame_share_exact_original_bytes_without_old_ack() {
    let fixture = Fixture::new();
    let mut writer = fixture.create();
    let mut old = record("old", b"old");
    old.admission.profile_digest = digest("old-profile");
    let first = must(writer.append(Digest32::ZERO, old));
    let original = must(prefix(&fixture));
    let receipt = must(writer.append(first.chain_digest, record("new", b"new")));
    let reader = view(&fixture, anchor(&receipt));
    let observed = match must(reader.read_with_frame_at_original_prefix(
        &id("new"),
        original.length,
        original.digest,
    )) {
        Some(observed) => observed,
        None => panic!("actual appended frame missing"),
    };
    assert_eq!(observed.frame_start, original.length);
    assert_eq!(observed.frame_end, observed.observed_length);
    assert_eq!(
        observed.observed.publication.record_digest,
        receipt.record_digest
    );
    assert!(reader.read_with_frame(&id("old")).is_err());
}
