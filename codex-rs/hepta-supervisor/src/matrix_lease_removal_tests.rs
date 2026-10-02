use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;

use super::MatrixProcessLeaseRemoval;
use crate::ProcessIdentity;
use crate::lease::MATRIX_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::MatrixProcessLease;
use crate::lease::read_matrix_lease;
use crate::lease::write_matrix_lease;

fn lease() -> MatrixProcessLease {
    MatrixProcessLease {
        schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        attached_agent_generation: 1,
        release_id: ReleaseId::parse("candidate").expect("release"),
        binding_revision: 1,
        binding_digest: Sha256Digest::for_bytes(b"binding"),
        process_incarnation: "matrix-cleanup".to_string(),
        plane_epoch: 1,
        identity: ProcessIdentity::new(43, "matrix-cleanup").expect("identity"),
    }
}

#[test]
fn matrix_normal_absence_is_not_exit_cleanup_evidence() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("matrix-lease.json");
    let lease = lease();
    assert!(
        MatrixProcessLeaseRemoval::new(&path, &lease)
            .finish(&path, &lease)
            .is_err()
    );
    MatrixProcessLeaseRemoval::for_failed_publication(&path, &lease)
        .finish(&path, &lease)
        .expect("same-owner failed publication can be absent");
}

#[test]
fn matrix_unlink_sync_retry_requires_the_same_owner_witness() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("matrix-lease.json");
    let lease = lease();
    write_matrix_lease(&path, &lease).expect("lease");
    let mut owner = MatrixProcessLeaseRemoval::new(&path, &lease);
    assert!(
        owner
            .finish_with(&path, &lease, |_| {
                Err(std::io::Error::other("injected sync failure").into())
            })
            .is_err()
    );
    assert!(read_matrix_lease(&path).expect("read").is_none());
    assert!(
        MatrixProcessLeaseRemoval::new(&path, &lease)
            .finish(&path, &lease)
            .is_err()
    );
    owner.finish(&path, &lease).expect("same owner sync retry");
}

#[test]
fn matrix_restored_or_substituted_lease_never_reuses_cleanup_permission() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("matrix-lease.json");
    let expected = lease();
    let mut owner = MatrixProcessLeaseRemoval::for_failed_publication(&path, &expected);
    assert!(
        owner
            .finish_with(&path, &expected, |_| {
                Err(std::io::Error::other("injected absent-path sync failure").into())
            })
            .is_err()
    );
    write_matrix_lease(&path, &expected).expect("restored same-looking lease");
    assert!(owner.finish(&path, &expected).is_err());
    assert_eq!(read_matrix_lease(&path).expect("read"), Some(expected));
}

#[test]
fn matrix_cleanup_rejects_changed_epoch_and_path() {
    let temp = tempfile::tempdir().expect("directory");
    let path = temp.path().join("matrix-lease.json");
    let expected = lease();
    let mut changed = expected.clone();
    changed.plane_epoch += 1;
    write_matrix_lease(&path, &changed).expect("different lifetime");
    let mut owner = MatrixProcessLeaseRemoval::new(&path, &expected);
    assert!(owner.finish(&path, &expected).is_err());
    assert!(
        owner
            .finish(&temp.path().join("other.json"), &expected)
            .is_err()
    );
    assert_eq!(read_matrix_lease(&path).expect("read"), Some(changed));
}
