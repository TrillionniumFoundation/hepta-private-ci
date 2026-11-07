use std::os::unix::fs::symlink;
use std::sync::mpsc;
use std::time::Duration;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::QualificationResult;
use crate::release_authority_store::AuthorityFiles;
use crate::release_authority_store::read_private;
use crate::release_authority_tests::Fixture;

#[test]
fn cold_publication_journal_rollback_is_rejected_against_retained_future_frontier()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.allow(&id)?;
    let journal = fixture.journal();
    // Each synchronous method has returned and released its File lock. There
    // is no SQLite store in this publication component and no live writer.
    let old = std::fs::read(&journal)?;
    fixture.registry.revoke_release(&fixture.agent, &id)?;
    let retained = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
    );
    let Fixture {
        registry,
        publisher,
        root,
        _temp,
        ..
    } = fixture;
    drop(registry);
    std::fs::write(&journal, &old)?;
    std::fs::File::open(&journal)?.sync_all()?;
    for _ in 0..2 {
        assert!(matches!(
            FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
            Err(FleetRegistryError::ReleaseAuthorityRollback)
        ));
        assert_eq!((publisher.frontier()?, publisher.cas_attempts()), retained);
        assert_eq!(std::fs::read(&journal)?, old);
    }
    Ok(())
}

#[test]
fn lost_success_ack_fences_ordinary_open_until_exact_committed_proposal_is_completed()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    let journal = fixture.journal();
    let previous = std::fs::read(&journal)?;
    fixture.publisher.drop_next_committed_cas_reply();
    assert!(matches!(
        fixture.registry.allow_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(std::fs::read(&journal)?, previous);
    assert!(matches!(
        fixture.registry.admit_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let retained = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
    );
    let Fixture {
        registry,
        publisher,
        root,
        agent,
        _temp,
        ..
    } = fixture;
    drop(registry);
    assert!(matches!(
        FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let recovered =
        FleetRegistry::recover_completed_release_update(root.clone(), publisher.config())?;
    assert_eq!((publisher.frontier()?, publisher.cas_attempts()), retained);
    // The CAS succeeded before the local allow projection was created. Its
    // idempotent projection may now complete without another external CAS.
    recovered.allow_release(&agent, &id)?;
    assert_eq!((publisher.frontier()?, publisher.cas_attempts()), retained);
    assert!(recovered.resolve_release(&agent, &id).is_ok());
    drop(recovered);
    assert!(
        FleetRegistry::open_existing_with_release_authority(root, publisher.config())?
            .resolve_release(&agent, &id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn observing_old_frontier_after_uncertain_cas_never_authorizes_retry_or_erasure()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    let journal = fixture.journal();
    let before = fixture.publisher.frontier()?;
    fixture.publisher.drop_next_cas_without_commit();
    assert!(matches!(
        fixture.registry.allow_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert_eq!(fixture.publisher.frontier()?, before);
    let directory = journal.parent().ok_or("missing owner directory")?;
    let retained = (
        std::fs::read(directory.join("attempt.v1.json"))?,
        std::fs::read(directory.join("proposal.v1.json"))?,
        std::fs::read(&journal)?,
        fixture.publisher.cas_attempts(),
    );
    let Fixture {
        registry,
        publisher,
        root,
        _temp,
        ..
    } = fixture;
    drop(registry);
    for _ in 0..2 {
        assert!(matches!(
            FleetRegistry::recover_completed_release_update(root.clone(), publisher.config()),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        assert!(matches!(
            FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
            Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
        ));
        assert_eq!(
            (
                std::fs::read(directory.join("attempt.v1.json"))?,
                std::fs::read(directory.join("proposal.v1.json"))?,
                std::fs::read(&journal)?,
                publisher.cas_attempts()
            ),
            retained
        );
        assert_eq!(publisher.frontier()?, before);
    }
    Ok(())
}

#[test]
fn completed_only_recovery_rejects_substituted_proposal_and_dangling_attempt()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.publisher.drop_next_committed_cas_reply();
    assert!(matches!(
        fixture.registry.allow_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    let directory = fixture
        .journal()
        .parent()
        .ok_or("missing owner directory")?
        .to_path_buf();
    let retained = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
    );
    let Fixture {
        registry,
        publisher,
        root,
        _temp,
        ..
    } = fixture;
    drop(registry);
    let proposal = directory.join("proposal.v1.json");
    let mut bytes = std::fs::read(&proposal)?;
    bytes.push(b' ');
    std::fs::write(&proposal, &bytes)?;
    assert!(matches!(
        FleetRegistry::recover_completed_release_update(root.clone(), publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRollback)
    ));
    std::fs::rename(
        directory.join("attempt.v1.json"),
        directory.join("retained-attempt.json"),
    )?;
    symlink("missing-attempt", directory.join("attempt.v1.json"))?;
    assert!(matches!(
        FleetRegistry::open_existing_with_release_authority(root.clone(), publisher.config()),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    assert!(FleetRegistry::recover_completed_release_update(root, publisher.config()).is_err());
    assert_eq!((publisher.frontier()?, publisher.cas_attempts()), retained);
    assert!(
        std::fs::symlink_metadata(directory.join("attempt.v1.json"))?
            .file_type()
            .is_symlink()
    );
    Ok(())
}

#[test]
fn private_owner_rejects_fifo_without_blocking_and_any_pending_inode_fences()
-> QualificationResult<()> {
    let temp = tempfile::tempdir()?;
    let directory = temp.path().canonicalize()?.join("owner");
    let files = AuthorityFiles::create(directory.clone())?;
    let fifo = directory.join("journal.v1.json");
    assert!(
        std::process::Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(&fifo)
            .status()?
            .success()
    );
    let (send, receive) = mpsc::sync_channel(1);
    let worker = std::thread::spawn(move || {
        let _ = send.send(read_private(&fifo, 1024));
    });
    assert!(matches!(
        receive.recv_timeout(Duration::from_secs(1))?,
        Err(FleetRegistryError::Invalid(_))
    ));
    worker.join().map_err(|_| "FIFO reader panicked")?;
    symlink("missing-target", directory.join("attempt.v1.json"))?;
    assert!(matches!(
        files.lock(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    std::fs::remove_file(directory.join("attempt.v1.json"))?;
    symlink("missing-target", directory.join("proposal.v1.json"))?;
    assert!(matches!(
        files.lock(),
        Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired)
    ));
    Ok(())
}
