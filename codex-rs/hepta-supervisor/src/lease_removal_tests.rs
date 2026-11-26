use std::path::Path;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

use super::ProcessLeaseRemoval;
use crate::ProcessIdentity;
use crate::SupervisorError;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::lease_path;
use crate::lease::read_lease;
use crate::lease::remove_lease;
use crate::lease::write_lease;

fn lease() -> Result<ProcessLease> {
    Ok(ProcessLease {
        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        spawn_generation: 1,
        release_id: ReleaseId::parse("exit-removal-test")?,
        identity: ProcessIdentity::new(/*system_id*/ 42, "exit-removal-test")?,
    })
}

fn failed_sync(_root: &Path) -> Result<(), SupervisorError> {
    Err(std::io::Error::other("injected directory sync failure").into())
}

#[test]
fn failed_sync_after_unlink_is_retryable_only_with_the_same_witness() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(
        removal
            .finish_with(root.path(), &expected, failed_sync)
            .is_err()
    );
    assert!(read_lease(root.path())?.is_none());
    assert!(remove_lease(root.path(), &expected).is_err());
    removal.finish(root.path(), &expected)?;
    removal.finish(root.path(), &expected)?;
    Ok(())
}

#[test]
fn every_retry_rechecks_directory_durability() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    let mut failures = 0;
    for _ in 0..3 {
        assert!(
            removal
                .finish_with(root.path(), &expected, |path| {
                    failures += 1;
                    failed_sync(path)
                })
                .is_err()
        );
    }
    assert_eq!(failures, 3);
    removal.finish(root.path(), &expected)?;
    Ok(())
}

#[test]
fn an_initially_missing_lease_never_authorizes_removal_completion() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    for _ in 0..2 {
        assert!(
            removal
                .finish_with(root.path(), &expected, |_| {
                    panic!("missing lease cannot reach sync")
                })
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn a_fresh_witness_cannot_infer_an_old_unlink_from_absence() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(
        removal
            .finish_with(root.path(), &expected, failed_sync)
            .is_err()
    );
    drop(removal);
    let mut fresh = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(fresh.finish(root.path(), &expected).is_err());
    Ok(())
}

#[test]
fn changed_process_identity_is_not_removed() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    let mut actual = expected.clone();
    actual.identity = ProcessIdentity::new(/*system_id*/ 43, "replacement")?;
    write_lease(root.path(), &actual)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(removal.finish(root.path(), &expected).is_err());
    assert_eq!(read_lease(root.path())?, Some(actual));
    Ok(())
}

#[test]
fn removed_lease_reappearing_with_the_same_identity_is_not_deleted_again() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(
        removal
            .finish_with(root.path(), &expected, failed_sync)
            .is_err()
    );
    write_lease(root.path(), &expected)?;
    assert!(removal.finish(root.path(), &expected).is_err());
    assert_eq!(read_lease(root.path())?, Some(expected));
    Ok(())
}

#[test]
fn witness_rejects_a_different_root_or_expected_generation() -> Result<()> {
    let root = tempfile::tempdir()?;
    let other = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    write_lease(other.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    let mut changed = expected.clone();
    changed.spawn_generation += 1;
    assert!(removal.finish(root.path(), &changed).is_err());
    assert!(removal.finish(other.path(), &expected).is_err());
    assert_eq!(read_lease(root.path())?, Some(expected.clone()));
    assert_eq!(read_lease(other.path())?, Some(expected.clone()));
    removal.finish(root.path(), &expected)?;
    assert_eq!(read_lease(other.path())?, Some(expected));
    Ok(())
}

#[test]
fn malformed_recreated_lease_is_preserved_and_rejected() -> Result<()> {
    let root = tempfile::tempdir()?;
    let expected = lease()?;
    write_lease(root.path(), &expected)?;
    let mut removal = ProcessLeaseRemoval::new(root.path(), &expected);
    assert!(
        removal
            .finish_with(root.path(), &expected, failed_sync)
            .is_err()
    );
    let path = lease_path(root.path());
    std::fs::write(&path, b"{torn")?;
    assert!(removal.finish(root.path(), &expected).is_err());
    assert_eq!(std::fs::read(path)?, b"{torn");
    Ok(())
}
