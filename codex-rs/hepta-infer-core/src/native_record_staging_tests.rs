#![allow(clippy::unwrap_used)]

use super::*;

struct StagingFixture {
    directory: PathBuf,
    journal: PathBuf,
}

impl StagingFixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-record-staging-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("owner.journal"),
            directory,
        }
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.journal, /*capacity*/ 16).unwrap()
    }
}

impl Drop for StagingFixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "principal-1".to_string(),
        worker_generation: 4,
        model: "model-1".to_string(),
        payload_digest: "6".repeat(64),
    }
}

#[test]
fn staged_admission_counts_all_held_records_and_preserves_compacted_history() {
    let fixture = StagingFixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("released"), 1).unwrap();
    let released = owner
        .stop_native_before_dispatch("released", "not sent".to_string())
        .unwrap();
    owner.reserve_native(request("held"), 1).unwrap();
    owner.compact_native_journal().unwrap();
    let metadata = (
        owner.native.checkpoint_generation,
        owner.native.checkpoint_digest.clone(),
        owner.native.archive_chain_digest.clone(),
    );
    let bytes = fs::read(&fixture.journal).unwrap();
    assert_eq!(
        owner.reserve_native(request("next"), 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(fs::read(&fixture.journal).unwrap(), bytes);
    drop(owner);

    let mut owner = fixture.open();
    assert_eq!(
        owner.reserve_native(request("next"), 1),
        Err(Error::CapacityExceeded)
    );
    owner
        .stop_native_before_dispatch("held", "not sent".to_string())
        .unwrap();
    owner.reserve_native(request("next"), 1).unwrap();
    assert_eq!(owner.native_record("released"), Some(&released));
    assert_eq!(owner.native.maximum_in_flight, Some(1));
    assert_eq!(
        (
            owner.native.checkpoint_generation,
            owner.native.checkpoint_digest.clone(),
            owner.native.archive_chain_digest.clone(),
        ),
        metadata
    );
    let expected = owner.native.records.clone();
    drop(owner);
    let reopened = fixture.open();
    assert_eq!(reopened.native.records, expected);
    assert_eq!(reopened.native.maximum_in_flight, Some(1));
}

#[test]
fn late_reducer_failure_does_not_install_mutated_target_or_append() {
    let fixture = StagingFixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("unrelated"), 1).unwrap();
    owner
        .stop_native_before_dispatch("unrelated", "not sent".to_string())
        .unwrap();
    owner.reserve_native(request("target"), 1).unwrap();
    owner.native.records.get_mut("target").unwrap().revision = u64::MAX;
    let expected = owner.native.records.clone();
    let bytes = fs::read(&fixture.journal).unwrap();
    assert_eq!(
        owner.stop_native_before_dispatch("target", "local candidate".to_string()),
        Err(Error::ArithmeticOverflow)
    );
    assert_eq!(owner.native.records, expected);
    assert_eq!(owner.native.maximum_in_flight, Some(1));
    assert_eq!(fs::read(&fixture.journal).unwrap(), bytes);
    assert!(!owner.poisoned);
}

#[test]
fn actual_append_failure_discards_target_and_first_admission_candidates() {
    for first_admission in [false, true] {
        let fixture = StagingFixture::new();
        let mut owner = fixture.open();
        if !first_admission {
            owner.reserve_native(request("unrelated"), 1).unwrap();
            owner
                .stop_native_before_dispatch("unrelated", "not sent".to_string())
                .unwrap();
            owner.reserve_native(request("target"), 1).unwrap();
        }
        let expected = owner.native.records.clone();
        let maximum = owner.native.maximum_in_flight;
        let bytes = fs::read(&fixture.journal).unwrap();
        // Retain the original exclusive lock while replacing the active
        // writer with a real read-only descriptor to the same journal.
        let original = std::mem::replace(&mut owner.file, File::open(&fixture.journal).unwrap());
        let result = if first_admission {
            owner.reserve_native(request("target"), 1)
        } else {
            owner.stop_native_before_dispatch("target", "not sent".to_string())
        };
        assert!(matches!(result, Err(Error::Io(_))));
        assert!(owner.poisoned);
        assert_eq!(owner.native.records, expected);
        assert_eq!(owner.native.maximum_in_flight, maximum);
        assert_eq!(fs::read(&fixture.journal).unwrap(), bytes);
        assert_eq!(
            owner.reserve_native(request("after-failure"), 1),
            Err(Error::WriterUnavailable)
        );
        drop(owner);
        drop(original);
        let reopened = fixture.open();
        assert_eq!(reopened.native.records, expected);
        assert_eq!(reopened.native.maximum_in_flight, maximum);
    }
}

#[test]
fn mismatched_event_identity_and_checkpoint_are_rejected_before_append() {
    let fixture = StagingFixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("target"), 1).unwrap();
    let expected = owner.native.records.clone();
    let bytes = fs::read(&fixture.journal).unwrap();
    assert_eq!(
        owner.commit_native(
            "different",
            Event::Stop {
                request_id: "target".to_string(),
                reason: "not sent".to_string(),
            }
        ),
        Err(Error::AssignmentMismatch)
    );
    assert_eq!(
        owner.commit_native(
            "target",
            Event::CheckpointReference {
                generation: 1,
                checkpoint_path: fixture
                    .directory
                    .join("absent.json")
                    .to_str()
                    .unwrap()
                    .to_string(),
                checkpoint_digest: "a".repeat(64),
                archive_segment_digest: "b".repeat(64),
                archive_chain_digest: "c".repeat(64),
            }
        ),
        Err(Error::InvalidTransition)
    );
    assert_eq!(owner.native.records, expected);
    assert_eq!(owner.native.maximum_in_flight, Some(1));
    assert_eq!(fs::read(&fixture.journal).unwrap(), bytes);
    assert!(!owner.poisoned);
}
