use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;

use super::ProcessLeaseRemoval;
use crate::ProcessIdentity;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;

fn lease() -> ProcessLease {
    ProcessLease {
        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        spawn_generation: 1,
        release_id: ReleaseId::parse("candidate").expect("release"),
        identity: ProcessIdentity::new(42, "failed-publication").expect("identity"),
    }
}

#[test]
fn unpublished_absence_requires_explicit_launch_witness() {
    let root = tempfile::tempdir().expect("directory");
    let expected = lease();
    assert!(
        ProcessLeaseRemoval::new(root.path(), &expected)
            .finish(root.path(), &expected)
            .is_err()
    );
    let mut owner = ProcessLeaseRemoval::for_failed_publication(root.path(), &expected);
    owner
        .finish(root.path(), &expected)
        .expect("absent unpublished lease");
    owner
        .finish(root.path(), &expected)
        .expect("same owner retry");
}

#[test]
fn unpublished_absence_sync_failure_cannot_authorize_reappearing_lease() {
    let root = tempfile::tempdir().expect("directory");
    let expected = lease();
    let mut owner = ProcessLeaseRemoval::for_failed_publication(root.path(), &expected);
    assert!(
        owner
            .finish_with(root.path(), &expected, |_| {
                Err(std::io::Error::other("injected directory sync failure").into())
            })
            .is_err()
    );
    write_lease(root.path(), &expected).expect("restore same-looking lease");
    assert!(owner.finish(root.path(), &expected).is_err());
    assert_eq!(read_lease(root.path()).expect("read"), Some(expected));
}

#[test]
fn unpublished_exact_unlink_retains_same_owner_sync_retry() {
    let root = tempfile::tempdir().expect("directory");
    let expected = lease();
    write_lease(root.path(), &expected).expect("partially published lease");
    let mut owner = ProcessLeaseRemoval::for_failed_publication(root.path(), &expected);
    assert!(
        owner
            .finish_with(root.path(), &expected, |_| {
                Err(std::io::Error::other("injected directory sync failure").into())
            })
            .is_err()
    );
    assert!(read_lease(root.path()).expect("read").is_none());
    owner
        .finish(root.path(), &expected)
        .expect("same owner completes sync");
    // A reconstructed ordinary witness still cannot infer the previous unlink.
    assert!(
        ProcessLeaseRemoval::new(root.path(), &expected)
            .finish(root.path(), &expected)
            .is_err()
    );
}
