//! Non-Unix lease persistence must not mint an Applied or Prepared receipt:
//! there is no audited replacement for fsync of the parent directory.

use super::*;

#[test]
fn unsupported_directory_commit_fails_before_state_or_files_are_published() {
    let temp = tempfile::tempdir().expect("temporary root");
    let journal = temp.path().join("lease-registry.json");
    let mut owner = DurableLeaseRegistryV1::open(&journal).expect("empty reader");
    assert_eq!(
        owner.prepare_issue("op:issue:1".into(), [3; 32]),
        Err(LeaseRegistryErrorV1::Unavailable),
    );
    assert!(owner.operation("op:issue:1").is_none());
    assert!(!journal.exists());
    assert!(!temp.path().join("lease-registry.json.next").exists());
}
